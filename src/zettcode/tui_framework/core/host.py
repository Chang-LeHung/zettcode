"""Services a running widget tree exposes to the widgets inside it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .widget import Widget


class Host(Protocol):
    """The application-side capabilities widgets may call.

    Widgets never reach for the terminal directly. Everything they need from
    the outside world, from moving focus to requesting a repaint, arrives
    through this interface so the same tree can run headless in tests.
    """

    def focus(self, widget: Widget | None) -> None:
        """Move keyboard focus to a widget, or clear it with ``None``."""

    def focused_widget(self) -> Widget | None:
        """Return the widget that currently receives keyboard input."""

    def invalidate(self) -> None:
        """Ask for a repaint on the next frame."""

    def request_layout(self) -> None:
        """Ask for a fresh measure before the next paint."""

    def copy(self, text: str) -> None:
        """Place text on the clipboard."""

    def refresh(self) -> None:
        """Repaint from scratch, discarding any retained frame."""

    def exit(self) -> None:
        """Stop the application loop."""
