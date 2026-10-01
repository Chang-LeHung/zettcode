"""Input events consumed by widgets, independent from the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class EventKind(StrEnum):
    """The finite set of input a widget can receive."""

    KEY = "key"
    TEXT = "text"
    PASTE = "paste"
    MOUSE = "mouse"
    RESIZE = "resize"
    FOCUS = "focus"


class MouseAction(StrEnum):
    """The gesture a mouse event describes."""

    DOWN = "down"
    UP = "up"
    MOVE = "move"
    SCROLL_UP = "scroll_up"
    SCROLL_DOWN = "scroll_down"


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Base class carrying the modifiers shared by every input event.

    Attributes:
        shift: Shift was held, where the terminal reports it.
        alt: Alt was held; a terminal may instead fold this into ``key``.
        control: Ctrl was held; a terminal may instead fold this into ``key``.
        meta: Meta was held.
    """

    shift: bool = False
    alt: bool = False
    control: bool = False
    meta: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyEvent(Event):
    """A named key press, such as ``enter``, ``ctrl_c``, or ``escape``.

    Attributes:
        key: Canonical key name, already lower-cased; a modifier may be folded
            into it (``"ctrl_c"``) or reported through the flags above.
        repeat: The terminal repeated the key while it was held down.
    """

    kind: ClassVar[EventKind] = EventKind.KEY
    key: str = ""
    repeat: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class TextEvent(Event):
    """One printable character or grapheme cluster.

    Attributes:
        text: The printable text, with no newline.
    """

    kind: ClassVar[EventKind] = EventKind.TEXT
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PasteEvent(Event):
    """A whole bracketed-paste payload delivered as one event.

    Attributes:
        text: The pasted payload, newlines included.
    """

    kind: ClassVar[EventKind] = EventKind.PASTE
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class MouseEvent(Event):
    """A pointer gesture at an absolute cell coordinate.

    Attributes:
        x: Column, zero-based from the left edge of the terminal.
        y: Row, zero-based from the top edge of the terminal.
        button: Button index reported by the terminal; 0 is the primary button.
            Wheel events keep the index they arrived with, so read ``action``
            rather than ``button`` to tell scrolling apart from clicking.
        action: Gesture this event describes.
    """

    kind: ClassVar[EventKind] = EventKind.MOUSE
    x: int = 0
    y: int = 0
    button: int = 0
    action: MouseAction = MouseAction.MOVE


@dataclass(frozen=True, slots=True, kw_only=True)
class ResizeEvent(Event):
    """The terminal changed size to the given cell dimensions.

    Attributes:
        width: New width in cells.
        height: New height in cells.
    """

    kind: ClassVar[EventKind] = EventKind.RESIZE
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class FocusEvent(Event):
    """The terminal gained or lost focus.

    Attributes:
        focused: ``True`` when the terminal gained focus.
    """

    kind: ClassVar[EventKind] = EventKind.FOCUS
    focused: bool = True


AnyEvent = KeyEvent | TextEvent | PasteEvent | MouseEvent | ResizeEvent | FocusEvent
