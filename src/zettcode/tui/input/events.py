"""Decoded terminal input shared by the decoder and the legacy component API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..core.events import MouseAction


class EventType(StrEnum):
    """The kinds of input the decoder can produce."""

    KEY = "key"
    TEXT = "text"
    PASTE = "paste"
    MOUSE = "mouse"
    RESIZE = "resize"
    RENDER = "render"


@dataclass(frozen=True, slots=True)
class InputEvent:
    """One decoded terminal input, before it becomes a framework event.

    Which fields matter depends on ``type``: keys fill ``key``, text and paste
    payloads fill ``text``, mouse events fill ``x``/``y``/``button``/``action``,
    and a resize carries no payload at all.

    Attributes:
        type: Which decoder branch produced this event.
        key: Canonical key name for ``KEY`` events.
        text: Payload for ``TEXT`` and ``PASTE`` events.
        x: Column for ``MOUSE`` events, zero-based.
        y: Row for ``MOUSE`` events, zero-based.
        button: Button index reported by the terminal.
        action: Gesture for ``MOUSE`` events.
        shift: Shift modifier, where the terminal reports it.
        alt: Alt modifier, where the terminal reports it.
        control: Ctrl modifier, where the terminal reports it.
    """

    type: EventType
    key: str = ""
    text: str = ""
    x: int = 0
    y: int = 0
    button: int = 0
    action: MouseAction | None = None
    shift: bool = False
    alt: bool = False
    control: bool = False


__all__ = ["EventType", "InputEvent", "MouseAction"]
