"""Incremental terminal byte-stream decoder."""

from __future__ import annotations

import re

from ..core.events import MouseAction
from .events import EventType, InputEvent
from .keys import CONTROL_KEYS, KEY_SEQUENCES

# SGR mouse report: CSI < Cb ; Cx ; Cy M (press or motion) or m (release).
# Coordinates arrive 1-based, so the decoder subtracts one from each.
_MOUSE = re.compile(rb"^\x1b\[<(\d+);(\d+);(\d+)([Mm])")

#: An operating-system command, which is how a terminal answers a query.
_OSC = b"\x1b]"

#: Control characters a paste may keep: tab indents code and newline separates
#: it. Everything else — the carriage return a clipboard adds per line, a stray
#: escape, a bell — would be drawn as a broken line or walked over silently.
_PASTE_KEEP = {"\t", "\n"}


def _paste_text(payload: bytes) -> str:
    """Decode one bracketed-paste payload into text an editor can hold.

    Clipboard line endings are normalised to ``\\n`` and control characters
    other than tab and newline are dropped, so pasted code cannot depend on the
    terminal it came from.
    """
    text = payload.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(character for character in text if character in _PASTE_KEEP or character.isprintable())


class InputDecoder:
    """Decode fragmented UTF-8, keyboard, paste, and SGR mouse input."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[InputEvent]:
        """Decode everything buffered, holding back a sequence that is still incomplete.

        Args:
            data: One raw read from the terminal; it may split a key sequence or
                a UTF-8 character anywhere, so the leftover stays in ``buffer``
                until the next call or ``flush_escape``.
        """
        self.buffer.extend(data)
        events: list[InputEvent] = []
        while self.buffer:
            event, consumed, incomplete = self._next()
            if incomplete:
                break
            if consumed == 0:
                consumed = 1
            del self.buffer[:consumed]
            if event is not None:
                events.append(event)
        return events

    def flush_escape(self) -> InputEvent | None:
        """Resolve a pending escape once the terminal's sequence timeout lapsed."""
        if not self.buffer:
            return None
        data = bytes(self.buffer)
        self.buffer.clear()
        # A reply cut off mid-sequence is a terminal that stopped talking, not
        # the Escape key followed by Alt-]: dropping it is the only reading that
        # cannot type the answer into the reader's draft.
        if data.startswith(_OSC):
            return None
        # "ESC <printable>" is how a terminal spells Alt-<key>; anything else
        # left over is the Escape key on its own.
        if len(data) >= 2 and 0x20 <= data[1] < 0x7F:
            return InputEvent(EventType.KEY, key=chr(data[1]), alt=True)
        return InputEvent(EventType.KEY, key="escape")

    def _next(self) -> tuple[InputEvent | None, int, bool]:
        """Decode one event, reporting bytes consumed and whether more are needed."""
        data = bytes(self.buffer)
        # Bracketed paste: 200~ opens the payload, 201~ closes it. Until the
        # closing guard arrives the payload is held back, so a paste containing
        # newlines or escape bytes is delivered whole rather than replayed.
        if data.startswith(b"\x1b[200~"):
            end = data.find(b"\x1b[201~", 6)
            if end < 0:
                return None, 0, True
            return (
                InputEvent(EventType.PASTE, text=_paste_text(data[6:end])),
                end + 6,
                False,
            )

        # Operating-system reply: ``ESC ]`` body, ended by BEL or by ST (ESC \).
        # The body belongs to whoever asked the question — it is stripped of its
        # framing and delivered as a REPLY, never decoded as keystrokes.
        if data.startswith(_OSC):
            bell = data.find(b"\x07", 2)
            terminator = data.find(b"\x1b\\", 2)
            if bell < 0 and terminator < 0:
                return None, 0, True
            if 0 <= bell and (terminator < 0 or bell < terminator):
                end, length = bell, 1
            else:
                end, length = terminator, 2
            return InputEvent(EventType.REPLY, text=data[2:end].decode("utf-8", "replace")), end + length, False

        mouse = _MOUSE.match(data)
        if mouse:
            code, x, y = (int(mouse.group(index)) for index in (1, 2, 3))
            suffix = mouse.group(4)
            action = _mouse_action(code, suffix)
            return (
                InputEvent(
                    EventType.MOUSE,
                    x=max(0, x - 1),
                    y=max(0, y - 1),
                    button=code & 3,  # low two bits: which button
                    action=action,
                    shift=bool(code & 4),  # bit 2
                    alt=bool(code & 8),  # bit 3, reported as "meta" by some terminals
                    control=bool(code & 16),  # bit 4
                ),
                mouse.end(),
                False,
            )

        for sequence, key in sorted(KEY_SEQUENCES.items(), key=lambda item: len(item[0]), reverse=True):
            if data.startswith(sequence):
                return InputEvent(EventType.KEY, key=key), len(sequence), False
            if sequence.startswith(data):
                return None, 0, True

        first = data[0]
        if first in CONTROL_KEYS:
            return InputEvent(EventType.KEY, key=CONTROL_KEYS[first]), 1, False
        if first == 0x1B:
            if len(data) == 1:
                return None, 0, True
            if data[1] in (0x0A, 0x0D):
                return InputEvent(EventType.KEY, key="alt_enter"), 2, False
            if data[1] in (0x08, 0x7F):
                return InputEvent(EventType.KEY, key="alt_backspace"), 2, False
            if data[1] in (ord("["), ord("O")):
                # ``ESC [`` and ``ESC O`` may still grow into a control sequence
                # the tables do not list, so wait for the timeout rather than
                # guessing that the user pressed Alt with a bracket.
                return None, 0, True
            if 0x20 <= data[1] < 0x7F:
                return InputEvent(EventType.KEY, key=chr(data[1]), alt=True), 2, False
            return InputEvent(EventType.KEY, key="escape"), 1, False
        if first < 0x20:
            return None, 1, False

        length = _utf8_length(first)
        if len(data) < length:
            return None, 0, True
        try:
            text = data[:length].decode("utf-8")
        except UnicodeDecodeError:
            text = "�"
            length = 1
        return InputEvent(EventType.TEXT, text=text), length, False


def _utf8_length(first: int) -> int:
    """Return the byte length of a UTF-8 sequence from its lead byte."""
    if first < 0x80:
        return 1
    if first & 0xE0 == 0xC0:
        return 2
    if first & 0xF0 == 0xE0:
        return 3
    if first & 0xF8 == 0xF0:
        return 4
    return 1


def _mouse_action(code: int, suffix: bytes) -> MouseAction:
    """Map an SGR mouse code and its suffix onto one action."""
    if code & 64:  # bit 6: wheel; bit 0 then picks up versus down
        return MouseAction.SCROLL_DOWN if code & 1 else MouseAction.SCROLL_UP
    if code & 32:  # bit 5: motion with a button held
        return MouseAction.MOVE
    return MouseAction.UP if suffix == b"m" else MouseAction.DOWN  # M presses, m releases
