"""Reading an image off the clipboard, per platform."""

from __future__ import annotations

import base64
from pathlib import Path
from subprocess import CompletedProcess


def _completed(argv, code: int = 0, stdout: bytes = b"") -> CompletedProcess[bytes]:
    return CompletedProcess(list(argv), code, stdout, b"")


def _apple_data(data: bytes, flavour: str = "PNGf") -> bytes:
    """Spell one clipboard flavour the way ``osascript`` prints it."""
    return f"\u00abdata {flavour}{data.hex().upper()}\u00bb\n".encode()


def test_macos_reads_the_png_the_clipboard_offers():
    from zettcode.app.ui.clipboard import read_image

    png = b"\x89PNG\r\n\x1a\n" + b"pixels"

    def runner(argv):
        assert argv[0] == "osascript"
        return _completed(argv, 0, _apple_data(png))

    assert read_image(runner=runner, system="darwin") == (png, "image/png")


def test_macos_converts_a_tiff_when_there_is_no_png():
    from zettcode.app.ui.clipboard import read_image

    def runner(argv):
        if argv[0] == "osascript":
            if "PNGf" in argv[2]:
                return _completed(argv, 1)
            return _completed(argv, 0, _apple_data(b"II*\x00tiff-bytes", "TIFF"))
        Path(argv[-1]).write_bytes(b"converted-bytes")
        return _completed(argv)

    assert read_image(runner=runner, system="darwin") == (b"converted-bytes", "image/png")


def test_a_clipboard_without_an_image_answers_none():
    from zettcode.app.ui.clipboard import read_image

    assert read_image(runner=lambda argv: _completed(argv, 1), system="darwin") is None
    assert read_image(runner=lambda argv: _completed(argv, 1), system="linux") is None
    assert read_image(runner=lambda argv: _completed(argv, 1), system="win32") is None


def test_linux_uses_whichever_clipboard_tool_answers():
    from zettcode.app.ui.clipboard import read_image

    calls: list[str] = []

    def runner(argv):
        calls.append(argv[0])
        if argv[0] == "wl-paste":
            return _completed(argv, 1)
        if "TARGETS" in argv:
            return _completed(argv, 0, b"image/png\ntext/plain\n")
        return _completed(argv, 0, b"\x89PNG\r\n\x1a\npng-bytes")

    image = read_image(runner=runner, system="linux")

    assert image == (b"\x89PNG\r\n\x1a\npng-bytes", "image/png")
    assert sorted(set(calls)) == ["wl-paste", "xclip"]


def test_linux_reads_the_type_the_clipboard_advertises():
    """A JPEG clipboard is a JPEG, not a PNG request that fails."""
    from zettcode.app.ui.clipboard import read_image

    asked: list[list[str]] = []

    def runner(argv):
        asked.append(list(argv))
        if "--list-types" in argv:
            return _completed(argv, 0, b"text/plain\nimage/jpeg\n")
        return _completed(argv, 0, b"\xff\xd8\xffjpeg-bytes")

    assert read_image(runner=runner, system="linux") == (b"\xff\xd8\xffjpeg-bytes", "image/jpeg")
    assert ["--type", "image/jpeg"] == asked[-1][-2:]


def test_a_pasted_base64_image_is_read_back_as_an_image():
    """A terminal that cannot paste bytes may paste the picture as base64 text."""
    from zettcode.app.ui.clipboard import image_from_paste

    data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 20
    assert image_from_paste(base64.b64encode(data).decode()) == (data, "image/png")
    assert image_from_paste("data:image/png;base64," + base64.b64encode(data).decode()) == (data, "image/png")
    # Terminals wrap a long paste, so newlines inside the payload are ignored.
    wrapped = base64.b64encode(data).decode()
    assert image_from_paste("\n".join(wrapped[i : i + 20] for i in range(0, len(wrapped), 20)))[1] == "image/png"


def test_a_paste_that_is_not_an_image_stays_text():
    from zettcode.app.ui.clipboard import image_from_paste

    assert image_from_paste("hello world") is None
    assert image_from_paste(base64.b64encode(b"just some words, not a picture").decode()) is None
    assert image_from_paste("data:text/plain;base64," + base64.b64encode(b"nope" * 40).decode()) is None


def test_the_in_process_pasteboard_reader_never_raises():
    """It is an optimisation: binding it may fail, reading may find nothing."""
    from zettcode.app.ui.clipboard import _pasteboard_reader

    reader = _pasteboard_reader()

    assert reader is None or reader() is None or isinstance(reader(), bytes)
