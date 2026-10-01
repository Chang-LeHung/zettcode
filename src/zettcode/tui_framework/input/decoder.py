"""Incremental terminal byte-stream decoder."""

from __future__ import annotations

import re

from ..core.events import MouseAction
from .events import EventType, InputEvent
from .keys import CONTROL_KEYS, KEY_SEQUENCES

_MOUSE = re.compile(rb"^\x1b\[<(\d+);(\d+);(\d+)([Mm])")


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
        if len(data) >= 2 and 0x20 <= data[1] < 0x7F:
            return InputEvent(EventType.KEY, key=chr(data[1]), alt=True)
        return InputEvent(EventType.KEY, key="escape")

    def _next(self) -> tuple[InputEvent | None, int, bool]:
        """Decode one event, reporting bytes consumed and whether more are needed."""
        data = bytes(self.buffer)
        if data.startswith(b"\x1b[200~"):
            end = data.find(b"\x1b[201~", 6)
            if end < 0:
                return None, 0, True
            return InputEvent(EventType.PASTE, text=data[6:end].decode("utf-8", "replace")), end + 6, False

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
                    button=code & 3,
                    action=action,
                    shift=bool(code & 4),
                    alt=bool(code & 8),
                    control=bool(code & 16),
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
    if code & 64:
        return MouseAction.SCROLL_DOWN if code & 1 else MouseAction.SCROLL_UP
    if code & 32:
        return MouseAction.MOVE
    return MouseAction.UP if suffix == b"m" else MouseAction.DOWN
