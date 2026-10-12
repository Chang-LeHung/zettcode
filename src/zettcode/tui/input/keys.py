"""Byte sequences terminals use to report keys and modifiers.

Two families are decoded here. The fixed table below covers what a terminal sends
without being asked. The rest is the *modified* encoding, which a terminal has to be
asked for: ``CSI <code> ; <modifiers> u`` (the kitty protocol, requested in
``Terminal._enter_sequences``) and ``CSI 27 ; <modifiers> ; <code> ~`` (xterm's
``modifyOtherKeys``, which some terminals are configured for). Without one of those,
a terminal cannot report Shift-Enter at all: it sends the same carriage return as
Enter, and no decoder can tell them apart.
"""

from __future__ import annotations

# Terminals do not send "up"; they send a Control Sequence Introducer (CSI,
# ``ESC [``) followed by parameters. These are the two families worth knowing:
# letter-final sequences (``CSI A`` is up) and tilde-final ones (``CSI 3 ~`` is
# delete), plus the modifier form ``CSI 1 ; <modifier> <letter>``.
KEY_SEQUENCES: dict[bytes, str] = {
    # CSI A-D: the four arrows in normal cursor-key mode.
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
    # CSI H / F: Home and End, with the tilde spellings some terminals prefer.
    b"\x1b[H": "home",
    b"\x1b[F": "end",
    b"\x1b[1~": "home",
    b"\x1b[4~": "end",
    # CSI n ~: the keys that have no letter of their own.
    b"\x1b[5~": "page_up",
    b"\x1b[6~": "page_down",
    b"\x1b[3~": "delete",
    b"\x1b[2~": "insert",
    b"\x1b[Z": "backtab",  # CSI Z: Shift-Tab
    # CSI 1 ; m <letter>, where m encodes the modifiers: 3 = Alt, 5 = Ctrl.
    b"\x1b[1;5D": "ctrl_left",
    b"\x1b[1;5C": "ctrl_right",
    b"\x1b[1;3D": "alt_left",
    b"\x1b[1;3C": "alt_right",
    b"\x1b[1;5H": "ctrl_home",
    b"\x1b[1;5F": "ctrl_end",
}

CONTROL_KEYS: dict[int, str] = {
    0x01: "ctrl_a",
    0x02: "ctrl_b",
    0x03: "ctrl_c",
    0x04: "ctrl_d",
    0x05: "ctrl_e",
    0x06: "ctrl_f",
    0x07: "ctrl_g",
    0x09: "tab",
    0x0A: "enter",
    0x0B: "ctrl_k",
    0x0C: "ctrl_l",
    0x0D: "enter",
    0x0E: "ctrl_n",
    0x10: "ctrl_p",
    0x12: "ctrl_r",
    0x14: "ctrl_t",
    0x15: "ctrl_u",
    0x16: "ctrl_v",
    0x17: "ctrl_w",
    0x19: "ctrl_y",
    0x1A: "ctrl_z",
    0x1F: "ctrl_underscore",
    0x7F: "backspace",
    0x08: "backspace",
}


#: Modifier bits of a modified key, most significant first: the parameter a terminal
#: reports is one plus a mask, and the lock bits above these are dropped — whether a
#: program sees Ctrl depends on Caps Lock, which is not a modifier anyone binds.
MODIFIER_BITS = ((8, "super"), (4, "ctrl"), (2, "alt"), (1, "shift"))

#: Keys the modified encoding names by code point instead of by character.
NAMED_CODES: dict[int, str] = {
    8: "backspace",
    9: "tab",
    10: "enter",
    13: "enter",
    27: "escape",
    32: "space",
    127: "backspace",
}

#: Tilde-final keys, by the number in front of the tilde.
TILDE_KEYS: dict[int, str] = {
    1: "home",
    2: "insert",
    3: "delete",
    4: "end",
    5: "page_up",
    6: "page_down",
}

#: Letter-final keys: the arrows and the Home/End family.
LETTER_KEYS: dict[bytes, str] = {
    b"A": "up",
    b"B": "down",
    b"C": "right",
    b"D": "left",
    b"F": "end",
    b"H": "home",
    b"P": "f1",
    b"Q": "f2",
    b"R": "f3",
    b"S": "f4",
    b"Z": "backtab",
}

#: Longest modifier parameter this decoder reads. A terminal may report more bits
#: than there are names for; the extra ones are ignored rather than fatal.
_MODIFIER_LIMIT = 256


def split_csi(data: bytes) -> tuple[bytes, bytes, int] | None:
    """Return ``(parameters, final, length)`` of one complete control sequence.

    A control sequence is ``ESC [``, then parameter and intermediate bytes — all of
    them below ``@`` — and a final byte at or above it (ECMA-48). A sequence whose
    final byte has not arrived is not returned: the caller keeps waiting for it,
    which is what a sequence split across two reads looks like.

    Returns:
        The parts and the number of bytes they take, or ``None`` when ``data`` does
        not hold a complete control sequence.
    """
    if not data.startswith(b"\x1b["):
        return None
    index = 2
    while index < len(data) and data[index] < 0x40:
        index += 1
    if index >= len(data):
        return None
    return data[2:index], data[index : index + 1], index + 1


def modifiers_of(parameter: bytes) -> tuple[bool, bool, bool, bool]:
    """Return the (shift, alt, ctrl, super) flags one modifier parameter carries.

    An empty parameter means one, which is "no modifiers": every terminal omits it
    rather than writing a one.
    """
    # A terminal that reports event types writes "3:1" — the modifiers, then what the
    # key did — and only the part before the colon says which modifiers are held.
    parameter = parameter.split(b":")[0]
    try:
        value = int(parameter) if parameter else 1
    except ValueError:
        return (False, False, False, False)
    mask = max(0, min(value, _MODIFIER_LIMIT) - 1)
    flags = {name: bool(mask & bit) for bit, name in MODIFIER_BITS}
    return (flags["shift"], flags["alt"], flags["ctrl"], flags["super"])


def modified(base: str, *, shift: bool = False, alt: bool = False, ctrl: bool = False, super_: bool = False) -> str:
    """Return the key name a modified key is spelled with, as its bindings expect.

    The prefixes are the ones this framework already uses — ``shift_enter``,
    ``alt_backspace``, ``ctrl_left`` — so a key reached through the modified
    encoding lands on the same binding as one reached through the fixed table.
    Shift-Tab keeps its own name, which is what the table calls it.
    """
    if base == "tab" and shift and not (alt or ctrl or super_):
        return "backtab"
    prefix = "".join(name for name, on in (("ctrl", ctrl), ("alt", alt), ("shift", shift), ("super", super_)) if on)
    return f"{prefix}_{base}" if prefix else base


def control_name(character: str) -> str:
    """Return the name a Ctrl-<character> would have arrived as without the encoding.

    A terminal that cannot say "Ctrl-C" sends byte 3, and this framework already has
    a name for every one of those: the same name is what a modified encoding has to
    produce, or the key would reach a binding that no longer exists. Where the
    legacy byte has no name — Ctrl-Space, Ctrl-/, which a terminal may or may not
    send at all — the name is spelled out, and being unbound it does nothing.
    """
    code = ord(character)
    if character == "@" or code == 0x20:
        legacy = 0x00
    elif character == "?":
        legacy = 0x7F
    elif 0x40 <= code <= 0x5F:
        legacy = code - 0x40
    elif 0x61 <= code <= 0x7A:
        legacy = code - 0x60
    else:
        return f"ctrl_{character}"
    return CONTROL_KEYS.get(legacy, f"ctrl_{character}")


#: Keys a terminal that sends Alt as a leading ESC can put Alt on: the cursor keys.
META_KEYS = frozenset({"up", "down", "left", "right", "home", "end", "page_up", "page_down", "delete"})


def meta_csi(data: bytes) -> tuple[str | None, int] | None:
    """Read ``ESC ESC [ …``: how a terminal in "Option sends Esc+" mode spells Alt on a cursor key.

    The same key without Alt is ``ESC [ A``, and with Alt the terminal puts one more ``ESC``
    in front of it. Read as two keys that is *Escape, then Up* — and Escape stops a running
    request, so an Alt-Up that was read that way would cancel the work it was pressed over.

    Returns:
        ``None`` when ``data`` is not this shape, ``(None, 0)`` while the sequence is still
        arriving, and ``(key, length)`` once it is complete.
    """
    if not data.startswith(b"\x1b\x1b["):
        return None
    csi = split_csi(data[1:])
    if csi is None:
        return (None, 0)
    parameters, final, length = csi
    named, _ = csi_event(parameters, final)
    if named not in META_KEYS:
        return None
    return (f"alt_{named}", length + 1)


def csi_event(parameters: bytes, final: bytes) -> tuple[str | None, str | None]:
    """Return ``(key, text)`` for one control sequence: a name, or text it spells.

    Args:
        parameters: Everything between ``ESC [`` and the final byte.
        final: The final byte.

    Returns:
        A key name, or the text a printable key spells, or ``(None, None)`` for a
        sequence this program has no name for.
    """
    fields = parameters.split(b";")
    if final == b"u":
        return _code_event(_number(fields[0]), modifiers_of(fields[1] if len(fields) > 1 else b""))
    if final == b"~":
        if len(fields) == 3 and _number(fields[0], default=-1) == 27:
            # xterm's modifyOtherKeys form: 27 ; modifiers ; code ~
            return _code_event(_number(fields[2]), modifiers_of(fields[1]))
        base = TILDE_KEYS.get(_number(fields[0], default=-1))
        if base is None:
            return (None, None)
        shift, alt, ctrl, super_ = modifiers_of(fields[1] if len(fields) > 1 else b"")
        return (modified(base, shift=shift, alt=alt, ctrl=ctrl, super_=super_), None)
    base = LETTER_KEYS.get(final)
    if base is None:
        return (None, None)
    shift, alt, ctrl, super_ = modifiers_of(fields[1] if len(fields) > 1 else b"")
    return (modified(base, shift=shift, alt=alt, ctrl=ctrl, super_=super_), None)


def _code_event(code: int, mods: tuple[bool, bool, bool, bool]) -> tuple[str | None, str | None]:
    """Return (key, text) for a code point and its modifiers, or (None, None) if unusable."""
    shift, alt, ctrl, super_ = mods
    if code < 0 or code > 0x10FFFF:
        return (None, None)
    character = chr(code)
    if ctrl or super_:
        if code in NAMED_CODES:
            return (modified(NAMED_CODES[code], shift=shift, alt=alt, ctrl=ctrl, super_=super_), None)
        # A control key means a letter or a punctuation mark: Ctrl with a character
        # outside ASCII is not something a terminal reports, and naming one after a
        # letter it is not would be worse than ignoring it.
        if character.isascii() and character.isprintable():
            return (control_name(character), None)
        return (None, None)
    if code in NAMED_CODES:
        base = NAMED_CODES[code]
        if base == "space":
            return (None, " ") if not alt else (modified(base, alt=alt, shift=shift), None)
        return (modified(base, shift=shift, alt=alt, super_=super_), None)
    if not character.isprintable():
        return (None, None)
    if alt:
        # Alt with a printable key is not text: without the encoding a terminal spells
        # it "ESC <key>", which this decoder reads as the key with Alt held, and a
        # binding is what acts on it.
        return (modified(character.lower(), alt=True, shift=shift, super_=super_), None)
    return (None, character.upper() if shift and character.isalpha() else character)


def _number(field: bytes, *, default: int = 0) -> int:
    """Return the number a control-sequence parameter holds, or ``default``."""
    if not field:
        return default
    try:
        return int(field)
    except ValueError:
        return default
