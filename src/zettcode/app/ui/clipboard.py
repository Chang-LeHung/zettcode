"""Read an image off the system clipboard, or out of a paste.

A terminal cannot hand an application the bytes of a pasted image, so the shell
asks the desktop instead. macOS hands the pasteboard over in-process through the
Objective-C runtime, with ``osascript`` kept as the fallback that can coerce a
format the pasteboard does not store directly; Linux asks ``wl-paste`` or
``xclip`` for whichever image type the clipboard advertises. A machine with
neither tool — or a clipboard holding text — simply has no image to attach, and
a terminal that pastes the picture *as text* instead (VS Code sends base64) is
covered by :func:`image_from_paste` further down.

The bytes are read back into memory, because that is what the runtime's
multimodal message wants: nothing is left behind in the workspace.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import ctypes.util
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from ctypes import c_char_p, c_ulong, c_void_p
from functools import lru_cache
from pathlib import Path
from subprocess import CompletedProcess

#: What one clipboard command looks like: argv in, its result out.
Runner = Callable[[Sequence[str]], "CompletedProcess[bytes]"]

#: Media type of an image the desktop path had to normalise: PNG is what both
#: platforms write, and the conversion on macOS exists to keep that true.
PNG = "image/png"

#: The image types a multimodal message accepts, and the bytes each one starts
#: with. A clipboard can offer more formats than this; the rest are ignored
#: rather than sent to a model that would reject them.
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

#: macOS pasteboard flavours, preferred first. ``PNGf`` is what a screenshot is;
#: a browser often offers only TIFF. Asking the system for a flavour makes it
#: coerce whatever it holds, so a HEIC or BMP screen capture still arrives as a
#: PNG.
_MACOS_FLAVOURS = ("PNGf", "TIFF")

#: Pasteboard types read straight out of the running process, most widely
#: accepted first. ``dataForType:`` returns a type only when it is really there,
#: which is what makes this path fast but incomplete: anything else falls back
#: to AppleScript, which coerces.
_PASTEBOARD_UTIS = ("public.png", "public.jpeg", "public.webp", "com.compuserve.gif", "public.tiff")

#: The magic bytes a TIFF starts with, either endianness.
_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*")

#: ``osascript`` prints AppleScript data as ``«data <four-char code><hex>»``.
_APPLE_DATA = re.compile(r"^«data [0-9A-Za-z]{4}([0-9A-Fa-f]+)»$")

#: Image types tried on Linux, most widely accepted first.
_LINUX_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

#: A ``data:`` URI that carries an image as base64, the way a page or an editor
#: copies one into a text clipboard.
_DATA_URI = re.compile(r"^data:image/[\w.+-]+;base64,", re.IGNORECASE)

#: Shorter base64 cannot hold a real image, so it is left as text even when it
#: happens to decode.
_MIN_BASE64 = 64


def read_image(*, runner: Runner | None = None, system: str | None = None) -> tuple[bytes, str] | None:
    """Return the clipboard's image as ``(bytes, media type)``, or None.

    Args:
        runner: Runs one clipboard command; injectable so tests can describe a
            desktop instead of owning one. Injecting one also keeps the
            in-process macOS pasteboard reader out of the way, so a test never
            depends on the machine's real clipboard.
        system: Platform to read from; ``sys.platform`` by default.
    """
    run = _run if runner is None else runner
    platform = sys.platform if system is None else system
    if platform == "darwin":
        return _macos_image(run, native=runner is None)
    if platform.startswith("linux"):
        return _x11_image(run)
    return None


def _run(argv: Sequence[str]) -> CompletedProcess[bytes]:
    """Run one clipboard command, capturing its output and swallowing failures."""
    return subprocess.run(list(argv), capture_output=True, check=False)


def _macos_image(runner: Runner, *, native: bool) -> tuple[bytes, str] | None:
    """Return whatever picture the pasteboard holds, fastest way first.

    The in-process reader hands back a flavour exactly as it is stored, which
    takes about a millisecond. AppleScript is asked only when that finds
    nothing, because its clipboard coercion also covers formats the pasteboard
    does not expose as a raw type — a HEIC or BMP capture — at the price of
    starting a helper program.
    """
    if native:
        reader = _pasteboard_reader()
        if reader is not None:
            data = reader()
            if data is not None:
                image = _image_from_bytes(data, runner)
                if image is not None:
                    return image
                # Data of a flavour this build cannot read: let AppleScript
                # coerce it rather than reporting no picture at all.
    return _script_image(runner)


def _script_image(runner: Runner) -> tuple[bytes, str] | None:
    """Ask AppleScript for the clipboard's picture and sniff what comes back.

    AppleScript is asked for the *data*, not told to write a file: ``write``
    copies a multi-megabyte image through AppleScript's own file API and takes
    seconds, while ``get the clipboard as`` returns it in one step.
    """
    for flavour in _MACOS_FLAVOURS:
        data = _apple_data(runner, flavour)
        if data is None:
            continue
        image = _image_from_bytes(data, runner)
        if image is not None:
            return image
    return None


def _image_from_bytes(data: bytes, runner: Runner) -> tuple[bytes, str] | None:
    """Return the image these bytes are, converting a TIFF the model will not take."""
    sniffed = _sniff(data)
    if sniffed is not None:
        return sniffed
    if data.startswith(_TIFF_SIGNATURES):
        return _convert_tiff(runner, data)
    return None


def _apple_data(runner: Runner, flavour: str) -> bytes | None:
    """Return one clipboard flavour as raw bytes, or None when it is absent."""
    result = runner(["osascript", "-e", f"get the clipboard as \u00abclass {flavour}\u00bb"])
    if result.returncode != 0:
        return None
    # The guillemets around the data are non-ASCII, so this is UTF-8, not ASCII.
    match = _APPLE_DATA.match(result.stdout.decode("utf-8", "replace").strip())
    if match is None:
        return None
    try:
        return bytes.fromhex(match.group(1))
    except ValueError:
        return None


def _convert_tiff(runner: Runner, data: bytes) -> tuple[bytes, str] | None:
    """Turn a TIFF the clipboard offered into a PNG the model will take."""
    with tempfile.TemporaryDirectory(prefix="zettcode-clipboard-") as directory:
        source = Path(directory) / "clipboard.tiff"
        source.write_bytes(data)
        converted = Path(directory) / "converted.png"
        if runner(["sips", "-s", "format", "png", str(source), "--out", str(converted)]).returncode != 0:
            return None
        if not converted.is_file():
            return None
        return converted.read_bytes(), PNG


@lru_cache(maxsize=1)
def _pasteboard_reader() -> Callable[[], bytes | None] | None:
    """Return the in-process macOS pasteboard reader, binding it on first use.

    ``osascript`` costs a third of a second even for a tiny picture — the
    helper program and AppleScript's clipboard coercion are the price, not the
    bytes — while the Objective-C runtime is already in the process. Nothing is
    guaranteed to be there, so a reader that cannot be bound is ``None`` and
    the caller falls back to the script.
    """
    if sys.platform != "darwin":
        return None
    library = ctypes.util.find_library("objc")
    if library is None:
        return None
    try:
        runtime = ctypes.CDLL(library)
        # AppKit has to be loaded before its classes can be looked up.
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        runtime.objc_getClass.restype = c_void_p
        runtime.objc_getClass.argtypes = [c_char_p]
        runtime.sel_registerName.restype = c_void_p
        runtime.sel_registerName.argtypes = [c_char_p]
        runtime.objc_autoreleasePoolPush.restype = c_void_p
        runtime.objc_autoreleasePoolPush.argtypes = []
        runtime.objc_autoreleasePoolPop.restype = None
        runtime.objc_autoreleasePoolPop.argtypes = [c_void_p]
    except AttributeError, OSError:
        return None

    def send(
        receiver: object, selector: bytes, *args: object, restype: object = c_void_p, argtypes: tuple = ()
    ) -> object:
        """Send one Objective-C message with the signature that call needs."""
        runtime.objc_msgSend.restype = restype
        runtime.objc_msgSend.argtypes = (c_void_p, c_void_p, *argtypes)
        return runtime.objc_msgSend(receiver, runtime.sel_registerName(selector), *args)

    def read() -> bytes | None:
        """Return the first image flavour the pasteboard holds, or None."""
        # Autoreleased objects — the NSData that is handed back, the strings
        # asked for — are freed here instead of piling up in a long-running
        # process with no pool of its own.
        pool = runtime.objc_autoreleasePoolPush()
        try:
            board = send(runtime.objc_getClass(b"NSPasteboard"), b"generalPasteboard")
            for uti in _PASTEBOARD_UTIS:
                name = send(
                    runtime.objc_getClass(b"NSString"),
                    b"stringWithUTF8String:",
                    uti.encode(),
                    argtypes=(c_char_p,),
                )
                data = send(board, b"dataForType:", name, argtypes=(c_void_p,))
                if not data:
                    continue
                length = send(data, b"length", restype=c_ulong)
                return ctypes.string_at(send(data, b"bytes"), length)
            return None
        finally:
            runtime.objc_autoreleasePoolPop(pool)

    return read


def _x11_image(runner: Runner) -> tuple[bytes, str] | None:
    """Read the first image an X11 or Wayland clipboard offers.

    ``wl-paste`` needs a Wayland session and ``xclip`` an X server, so both are
    tried. Each clipboard advertises the types it holds, which is what lets a
    JPEG or WebP be read as itself instead of being asked for a PNG and giving
    up; a tool that cannot list types is still asked for PNG.
    """
    for base, list_argv, flag in (
        (["wl-paste", "--no-newline"], ["wl-paste", "--list-types"], "--type"),
        (
            ["xclip", "-selection", "clipboard", "-o"],
            ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
            "-t",
        ),
    ):
        for media_type in _offered_types(runner, list_argv) or (PNG,):
            if media_type not in _LINUX_TYPES:
                continue
            result = runner([*base, flag, media_type])
            if result.returncode != 0 or not result.stdout:
                continue
            return _sniff(result.stdout) or (result.stdout, media_type)
    return None


def _offered_types(runner: Runner, argv: Sequence[str]) -> tuple[str, ...]:
    """Return the image types a clipboard tool says are on the clipboard."""
    result = runner(argv)
    if result.returncode != 0:
        return ()
    text = result.stdout.decode("utf-8", "replace")
    return tuple(line.strip() for line in text.splitlines() if line.strip().startswith("image/"))


def image_from_paste(text: str) -> tuple[bytes, str] | None:
    """Return the image a pasted payload carries, if it carries one.

    A terminal cannot paste an image as bytes, but it can paste one as text:
    VS Code turns a clipboard image into base64, warns about the size, and
    sends the characters, and a copied ``data:image/...;base64,`` URI is the
    same idea. Recognising both turns one paste key into the same ``[image #N]``
    chip as :func:`read_image`, instead of a wall of characters standing in for
    a picture.

    Only a payload whose decoded bytes start like a known image format counts,
    so ordinary text that merely looks like base64 stays text.
    """
    payload = text.strip()
    if _DATA_URI.match(payload):
        payload = payload.split(",", 1)[1]
    payload = "".join(payload.split())
    if len(payload) < _MIN_BASE64:
        return None
    try:
        data = base64.b64decode(payload, validate=True)
    except binascii.Error, ValueError:
        return None
    return _sniff(data)


def _sniff(data: bytes) -> tuple[bytes, str] | None:
    """Return ``data`` and its media type when it starts like a known image."""
    for signature, media_type in SIGNATURES:
        if data.startswith(signature):
            return data, media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, "image/webp"
    return None
