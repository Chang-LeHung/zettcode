"""Services a running widget tree exposes to the widgets inside it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .widget import Widget


class Host(ABC):
    """The application-side capabilities widgets may call.

    Widgets never reach for the terminal directly. Everything they need from
    the outside world, from moving focus to requesting a repaint, arrives
    through this interface so the same tree can run headless in tests.

    This is an abstract base class rather than a protocol: an implementation is
    expected to subclass it and answer every method, which is what `TuiApp`
    does, and what keeps a missing implementation a loud error instead of a
    class that merely looks compatible.
    """

    @abstractmethod
    def focus(self, widget: Widget | None) -> None:
        """Move keyboard focus to a widget, or clear it with ``None``."""

    @abstractmethod
    def focused_widget(self) -> Widget | None:
        """Return the widget that currently receives keyboard input."""

    @abstractmethod
    def invalidate(self) -> None:
        """Ask for a repaint on the next frame."""

    @abstractmethod
    def request_layout(self) -> None:
        """Ask for a fresh measure before the next paint."""

    @abstractmethod
    def copy(self, text: str) -> None:
        """Place text on the clipboard."""

    @abstractmethod
    def refresh(self) -> None:
        """Repaint from scratch, discarding any retained frame."""

    @abstractmethod
    def exit(self) -> None:
        """Stop the application loop."""
