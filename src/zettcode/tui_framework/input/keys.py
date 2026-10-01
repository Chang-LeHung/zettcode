"""Byte sequences terminals use to report keys and modifiers."""

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
    0x17: "ctrl_w",
    0x19: "ctrl_y",
    0x1A: "ctrl_z",
    0x1F: "ctrl_underscore",
    0x7F: "backspace",
    0x08: "backspace",
}
