"""A full-screen page built around a scrollable list."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...tui import SEPARATOR
from ..core.events import KeyEvent
from ..core.geometry import Rect
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, Style
from .list import ListItem, ListView


class ListPage(Widget):
    """An opaque page with a title, a scrolling list, and a footer hint.

    Shape::

        Title                                  <- one row below the top edge
          > row one                            <- ListView: marker, band, scroll
            row two
        enter select \u00b7 esc back                 <- footer, on the bottom row

    The page owns the frame so a caller only maps data to rows: it fills its
    rectangle with ``surface_alt`` so whatever is underneath cannot show
    through, bounds the list to ``visible_rows``, and turns Escape into
    ``on_cancel`` before the list can consume the key. It composes
    :class:`ListView` rather than inheriting it, which keeps that list
    general-purpose.

    It paints into whatever rectangle it is given: the caller decides whether
    that is the whole screen or a panel anchored to the bottom edge.

    Args:
        items: Rows to show; the list scrolls past ``visible_rows``.
        title: Drawn one row below the page's top edge.
        footer: Hint drawn on the bottom row.
        on_select: Receives the row committed with Enter.
        on_cancel: Called when the user presses Escape; ``None`` lets the key
            pass through untouched.
        selected: Index highlighted first, clamped into range.
        visible_rows: Most rows shown at once; the list scrolls when there are
            more.
    """

    def __init__(
        self,
        items: Sequence[ListItem],
        *,
        title: str,
        footer: str = f"enter select {SEPARATOR} esc back",
        on_select: Callable[[ListItem], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        selected: int = 0,
        visible_rows: int = 6,
    ) -> None:
        """Build the page and its list, highlighting ``selected`` without notifying."""
        super().__init__()
        self.title = title
        self.footer = footer
        self.on_cancel = on_cancel
        self.visible_rows = max(1, visible_rows)
        self.list = ListView(items, on_select=on_select, wrap=False, band=True)
        if items:
            self.list.select(selected, notify=False)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the list so it lays out, paints, and takes focus."""
        return (self.list,)

    def layout(self, rect: Rect) -> None:
        """Inset the list under the title, capped to the visible rows."""
        super().layout(rect)
        height = min(self.visible_rows, max(0, rect.height - 5))
        self.list.layout(Rect(rect.x + 2, rect.y + 3, max(0, rect.width - 4), height))

    def render(self, canvas: Canvas) -> None:
        """Fill the page, then draw the title, the list, and the footer."""
        if self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface_alt))
        heading = Style(foreground=theme.text, background=theme.surface_alt, bold=True)
        hint = Style(foreground=theme.muted, background=theme.surface_alt)
        room = max(0, self.rect.width - 4)
        canvas.draw_text(self.rect.x + 2, self.rect.y + 1, self.title, heading, max_width=room)
        self.list.render(canvas)
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def capture_event(self, event, host: Host) -> bool:
        """Close on Escape before the focused list can see the key."""
        if isinstance(event, KeyEvent) and event.key == "escape" and self.on_cancel is not None:
            self.on_cancel()
            return True
        return False
