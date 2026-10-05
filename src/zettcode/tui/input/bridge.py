"""Translate decoded terminal input into the widget-facing event model.

The legacy ``InputEvent`` structure predates the widget contract. This bridge
is the only place that knows both shapes, so removing it later is a local
change rather than a hunt through every widget.
"""

from __future__ import annotations

from ..core.events import (
    AnyEvent,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    ResizeEvent,
    TextEvent,
)
from .events import EventType, InputEvent


def translate(event: InputEvent) -> AnyEvent | None:
    """Return the widget-facing event, or None for internal signals."""
    match event.type:
        case EventType.KEY:
            return KeyEvent(key=event.key, shift=event.shift, alt=event.alt, control=event.control)
        case EventType.TEXT:
            return TextEvent(text=event.text, alt=event.alt, control=event.control)
        case EventType.PASTE:
            return PasteEvent(text=event.text)
        case EventType.MOUSE if event.action is not None:
            return MouseEvent(
                x=event.x,
                y=event.y,
                button=event.button,
                action=event.action,
                shift=event.shift,
                alt=event.alt,
                control=event.control,
            )
        case EventType.RESIZE:
            return ResizeEvent()
        case _:
            return None
