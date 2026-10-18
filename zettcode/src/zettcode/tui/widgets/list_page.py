"""A full-screen page built around a scrollable list."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from zettcode.tui import SEPARATOR

from ..core.events import KeyEvent
from ..core.geometry import Rect
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, Style
from .list import ListItem, ListView, Parts, draw_parts


class ListPage(Widget):
    """An opaque page with a title, a scrolling list, and a footer hint.

    Shape::

        Title                                  <- one row below the top edge
        Subtitle                               <- when there is one, over the rows
          > row one                            <- ListView: marker, band, scroll
            row two
        enter select \u00b7 esc back                 <- footer, on the bottom row

    The page owns the frame so a caller only maps data to rows: it fills its
    rectangle with ``surface_alt`` so whatever is underneath cannot show
    through, bounds the list to ``visible_rows``, and turns Escape into
    ``on_cancel`` before the list can consume the key. Its rows wrap, as the
    slash menu's already do: a picker whose last row refuses Down reads as one
    that ignores the key, and with four models the reader presses Up once to reach
    the last instead of three times to reach nothing. Paging wraps with it, since
    one flag governs every move. It composes
    :class:`ListView` rather than inheriting it, which keeps that list
    general-purpose.

    It paints into whatever rectangle it is given: the caller decides whether
    that is the whole screen or a panel anchored to the bottom edge.

    Args:
        items: Rows to show; the list scrolls past ``visible_rows``.
        title: Drawn one row below the page's top edge.
        subtitle: Drawn under the title for a page with a second fact to name —
            the file a report came from, say. It costs one row of the page's
            height, and is left out of the layout entirely when absent.
        subtitle_parts: The subtitle in colours, which must read as ``subtitle`` when joined; ``None`` draws the
            subtitle in the muted colour.
        footer: Hint drawn on the bottom row.
        on_select: Receives the row committed with Enter.
        on_cancel: Called when the user presses Escape; ``None`` lets the key
            pass through untouched.
        selected: Index highlighted first, clamped into range.
        visible_rows: Most rows shown at once; the list scrolls when there are
            more. ``None`` fills the rectangle the page is given, which is what
            a panel wants: its height already bounds the list.
    """

    def __init__(
        self,
        items: Sequence[ListItem],
        *,
        title: str,
        subtitle: str | None = None,
        subtitle_parts: Parts | None = None,
        footer: str = f"enter select {SEPARATOR} esc back",
        on_select: Callable[[ListItem], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        selected: int = 0,
        visible_rows: int | None = None,
    ) -> None:
        """Build the page and its list, highlighting ``selected`` without notifying."""
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.subtitle_parts = subtitle_parts
        self.footer = footer
        self.on_cancel = on_cancel
        self.visible_rows = None if visible_rows is None else max(1, visible_rows)
        self.list = ListView(items, on_select=on_select, wrap=True, band=True)
        if items:
            self.list.select(selected, notify=False)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the list so it lays out, paints, and takes focus."""
        return (self.list,)

    def layout(self, rect: Rect) -> None:
        """Inset the list under the title, capped to the visible rows."""
        super().layout(rect)
        over = 1 if self.subtitle is not None else 0
        room = max(0, rect.height - 5 - over)
        height = room if self.visible_rows is None else min(self.visible_rows, room)
        self.list.layout(Rect(rect.x + 2, rect.y + 3 + over, max(0, rect.width - 4), height))

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
        if self.subtitle is not None:
            if self.subtitle_parts is None:
                canvas.draw_text(self.rect.x + 2, self.rect.y + 2, self.subtitle, hint, max_width=room)
            else:
                draw_parts(canvas, self.rect.x + 2, self.rect.y + 2, self.subtitle_parts(theme), hint, max_width=room)
        self.list.render(canvas)
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def capture_event(self, event, host: Host) -> bool:
        """Close on Escape before the focused list can see the key."""
        if isinstance(event, KeyEvent) and event.key == "escape" and self.on_cancel is not None:
            self.on_cancel()
            return True
        return False
