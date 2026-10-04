"""Framework runtime: contracts, focus, screens, keymaps, and the app loop."""

from .app import TuiApp
from .events import (
    AnyEvent,
    Event,
    EventKind,
    FocusEvent,
    KeyEvent,
    MouseAction,
    MouseEvent,
    PasteEvent,
    ResizeEvent,
    TextEvent,
)
from .focus import FocusManager, walk
from .geometry import Constraints, EdgeInsets, Point, Rect, Size
from .host import Host
from .keymap import Binding, Command, CommandRegistry, Keymap, event_key, key_id, normalize_key
from .scheduler import Scheduler
from .screen import Screen, ScreenStack
from .theme import DARK, LIGHT, Theme, ToolTheme, theme_named, theme_names
from .widget import Widget

__all__ = [
    "AnyEvent",
    "TuiApp",
    "Binding",
    "Command",
    "CommandRegistry",
    "Constraints",
    "DARK",
    "EdgeInsets",
    "Event",
    "EventKind",
    "FocusEvent",
    "FocusManager",
    "Host",
    "KeyEvent",
    "Keymap",
    "LIGHT",
    "MouseAction",
    "MouseEvent",
    "PasteEvent",
    "Point",
    "Rect",
    "ResizeEvent",
    "Scheduler",
    "Screen",
    "ScreenStack",
    "Size",
    "Theme",
    "TextEvent",
    "Widget",
    "event_key",
    "key_id",
    "normalize_key",
    "theme_named",
    "ToolTheme",
    "theme_names",
    "walk",
]
