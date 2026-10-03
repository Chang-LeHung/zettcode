"""Selectable list with keyboard navigation and a scrolling window."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..core.events import KeyEvent, MouseAction, MouseEvent
from ..core.geometry import Constraints, Size
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import display_width


@dataclass(frozen=True, slots=True)
class ListItem:
    """One row of a ListView.

    Attributes:
        value: Opaque payload handed back to the callbacks.
        label: Left-hand text of the row.
        description: Secondary text drawn after the label when space allows.
        disabled: Skipped by navigation and refused by ``activate``.
    """

    value: object = None
    label: str = ""
    description: str = ""
    disabled: bool = False


class ListView(Widget):
    """Show rows and let one of them be selected.

    The window is an absolute row index so the list never rebuilds itself, and
    the selection is always kept inside the visible window.

    Shape::

        > alpha  first                    <- selected: marker, bold, selection band
          beta   second                   <- description starts at a fixed column
          gamma                           <- disabled: dim, no marker, refuses Enter
          delta  fourth

    Only ``rect.height`` rows are drawn, starting at ``top``; the marker is part
    of the label (U+25B8 selected, two spaces otherwise) and the muted
    description keeps the row's background so the selection band stays
    continuous.
    """

    MARKERS = ("\u25b8 ", "  ")

    def __init__(
        self,
        items: Sequence[ListItem] = (),
        *,
        on_select: Callable[[ListItem], None] | None = None,
        on_highlight: Callable[[ListItem], None] | None = None,
        wrap: bool = True,
        band: bool = False,
    ) -> None:
        """Configure the rows, the callbacks, and whether the selection wraps.

        Args:
            items: Initial rows; ``set_items`` replaces them wholesale.
            on_select: Called with the row when Enter or ``activate`` commits it.
            on_highlight: Called only when the selection actually moves, which
                makes it safe to use for previewing the highlighted row.
            wrap: Wrap from the last row to the first and back.
            band: Fill the entire highlighted row, not just the label.
        """
        super().__init__()
        self._items = tuple(items)
        self.on_select = on_select
        self.on_highlight = on_highlight
        self.wrap = wrap
        self.band = band
        self.selected = 0 if self._items else -1
        self.top = 0

    @property
    def focusable(self) -> bool:
        """Let Tab land on the list so the arrow keys work without a click."""
        return True

    @property
    def items(self) -> tuple[ListItem, ...]:
        """Return the rows currently shown."""
        return self._items

    def set_items(self, items: Sequence[ListItem]) -> None:
        """Replace the rows and reset the selection to the top."""
        self._items = tuple(items)
        self.selected = 0 if self._items else -1
        self.top = 0

    @property
    def current(self) -> ListItem | None:
        """Return the selected row, or None when the list is empty."""
        if 0 <= self.selected < len(self._items):
            return self._items[self.selected]
        return None

    def select(self, index: int, *, notify: bool = True) -> None:
        """Move the selection to a row, skipping disabled entries.

        Args:
            index: Target row, clamped to the list; a disabled row is refused.
            notify: Call ``on_highlight`` when the row actually changes. Pass
                False for programmatic resets that should stay silent.
        """
        if not self._items:
            self.selected = -1
            return
        index = min(max(0, index), len(self._items) - 1)
        if self._items[index].disabled:
            return
        changed = index != self.selected
        self.selected = index
        if changed and notify and self.on_highlight is not None:
            self.on_highlight(self._items[index])

    def move(self, amount: int) -> None:
        """Move the selection, wrapping when configured to."""
        if not self._items:
            return
        count = len(self._items)
        index = self.selected + amount
        if self.wrap:
            index %= count
        else:
            index = min(max(0, index), count - 1)
        step = 1 if amount >= 0 else -1
        for offset in range(count):
            candidate = (index + offset * step) % count
            if not self._items[candidate].disabled:
                self.select(candidate)
                return

    def activate(self) -> bool:
        """Fire the select callback for the current row."""
        item = self.current
        if item is None or item.disabled or self.on_select is None:
            return False
        self.on_select(item)
        return True

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest row plus marker, and one cell per row."""
        widest = max(
            (display_width(item.label) + display_width(item.description) + 2 for item in self._items),
            default=0,
        )
        return constraints.constrain(Size(widest + 2, len(self._items)))

    def render(self, canvas: Canvas) -> None:
        """Scroll the selection into view, then paint the visible rows."""
        if not self._items or self.rect.height <= 0:
            return
        self._ensure_visible()
        theme = self.theme
        for row in range(self.rect.height):
            index = self.top + row
            if index >= len(self._items):
                break
            item = self._items[index]
            selected = index == self.selected
            marker = self.MARKERS[0] if selected else self.MARKERS[1]
            if item.disabled:
                style = Style(foreground=theme.muted, dim=True)
            elif selected:
                style = Style(foreground=theme.text, background=theme.selection, bold=True)
            else:
                style = Style(foreground=theme.text, background=theme.surface_alt if self.band else None)
            if selected and self.band:
                canvas.fill(self.rect.x, self.rect.y + row, self.rect.width, 1, style)
            label = truncate(marker + item.label, max(0, self.rect.width))
            canvas.draw_text(self.rect.x, self.rect.y + row, label, style, max_width=self.rect.width)
            if item.description:
                used = len(marker) + len(item.label) + 1
                room = self.rect.width - used
                if room > 3:
                    text = truncate(item.description, room)
                    canvas.draw_text(
                        self.rect.x + used,
                        self.rect.y + row,
                        text,
                        Style(foreground=theme.muted, background=style.background),
                        max_width=room,
                    )

    def handle(self, event, host: Host) -> bool:
        """Select the clicked row, or move with the arrow and page keys."""
        if isinstance(event, MouseEvent) and self.rect.contains(event.x, event.y):
            if event.action is MouseAction.DOWN:
                self.select(self.top + event.y - self.rect.y)
                host.focus(self)
                return True
            return False
        if not isinstance(event, KeyEvent) or host.focused_widget() is not self:
            return False
        page = max(1, self.rect.height - 1)
        match event.key:
            case "up":
                self.move(-1)
            case "down":
                self.move(1)
            case "page_up":
                self.move(-page)
            case "page_down":
                self.move(page)
            case "home":
                self.select(0)
            case "end":
                self.select(len(self._items) - 1)
            case "enter":
                return self.activate()
            case _:
                return False
        return True

    def _ensure_visible(self) -> None:
        """Scroll the window so the selected row stays on screen."""
        height = max(1, self.rect.height)
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + height:
            self.top = self.selected - height + 1
        self.top = min(max(0, self.top), max(0, len(self._items) - height))
