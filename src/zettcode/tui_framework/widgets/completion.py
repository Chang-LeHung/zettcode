"""Completion candidates shown next to an editor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import display_width


@dataclass(frozen=True, slots=True)
class CompletionItem:
    """One candidate: the text to insert plus how to present it.

    Attributes:
        value: Text inserted into the editor when the candidate is chosen.
        label: Row text; falls back to ``value`` when empty.
        description: Muted text shown after the label when space allows.
    """

    value: str
    label: str = ""
    description: str = ""

    @property
    def display(self) -> str:
        """Return the text to show, preferring the label over the inserted value."""
        return self.label or self.value


class Completer(Protocol):
    """Return candidates for the token under the cursor."""

    def __call__(self, text: str, position: int) -> Sequence[CompletionItem]:
        """Return the candidates for the token ending at ``position``."""


class CompletionPopup(Widget):
    """A borderless, scrolling list of completion candidates.

    Each row is a command column followed by a muted description, and the
    selected row is painted as a full-width band so the choice reads at a
    glance. The popup never takes focus: the editor keeps the cursor and drives
    the selection, so Tab and Enter still belong to the text being typed.
    """

    def __init__(
        self,
        items: Sequence[CompletionItem] = (),
        *,
        selected: int = 0,
        max_height: int = 8,
    ) -> None:
        """Build the popup with an optional initial selection.

        Args:
            items: Candidates to show; the popup hides itself while empty.
            selected: Index highlighted first, clamped into range.
            max_height: Most candidate rows to show; the popup is exactly that
                tall, with no frame around it.
        """
        super().__init__()
        self.max_height = max(1, max_height)
        self.items: tuple[CompletionItem, ...] = ()
        self.selected = 0
        self.top = 0
        self.set_items(items, selected=selected)

    def set_items(self, items: Sequence[CompletionItem], *, selected: int | None = None) -> None:
        """Replace the candidates, clamping the selection into range.

        Args:
            items: New candidate list.
            selected: Index to highlight; ``None`` keeps the current index, which
                is what makes cycling through a refreshed list stable.
        """
        self.items = tuple(items)
        if not self.items:
            self.selected = 0
            self.top = 0
            return
        self.selected = min(max(0, self.selected if selected is None else selected), len(self.items) - 1)

    def move(self, amount: int) -> None:
        """Move the highlight, wrapping at both ends."""
        if self.items:
            self.selected = (self.selected + amount) % len(self.items)

    @property
    def current(self) -> CompletionItem | None:
        """Return the highlighted candidate, or None when the list is empty."""
        return self.items[self.selected] if 0 <= self.selected < len(self.items) else None

    @property
    def visible_height(self) -> int:
        """Return how many candidate rows the popup shows at most."""
        return min(len(self.items), self.max_height)

    @property
    def visible(self) -> bool:
        """Return whether the popup has anything to show."""
        return bool(self.items)

    @property
    def name_width(self) -> int:
        """Return the columns reserved for the command column."""
        return max((display_width(item.display) for item in self.items), default=0)

    def preferred_size(self) -> Size:
        """Size the popup to its two columns, capped at ``max_height`` rows.

        The width is only a hint: a caller that hands the popup a wider slot,
        such as a full-width row above a composer, gets the whole span painted.
        """
        widest = max((display_width(item.description) for item in self.items), default=0)
        natural = 1 + self.name_width + 2 + widest + 1 if self.items else 0
        return Size(natural, self.visible_height)

    def measure(self, constraints: Constraints) -> Size:
        """Clamp the preferred size into the offered constraints."""
        return constraints.constrain(self.preferred_size())

    def _scroll_into_view(self) -> None:
        """Keep the highlighted candidate inside the visible window."""
        rows = min(self.rect.height, len(self.items))
        self.top = min(self.top, max(0, len(self.items) - rows))
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + rows:
            self.top = self.selected - rows + 1

    def render(self, canvas: Canvas) -> None:
        """Draw the visible candidates, banding the selected row full width."""
        if not self.items or self.rect.empty:
            return
        theme = self.theme
        width = self.rect.width
        # Every description starts at the same column, so the command column
        # stays aligned no matter which candidate is highlighted.
        description_column = 1 + self.name_width + 2
        self._scroll_into_view()
        for row in range(min(self.rect.height, len(self.items) - self.top)):
            item = self.items[self.top + row]
            selected = self.top + row == self.selected
            base = (
                Style(foreground=theme.text, background=theme.selection, bold=True)
                if selected
                else Style(foreground=theme.text)
            )
            if selected:
                # A band across the whole row, not just behind the text: that is
                # what makes the current choice readable at a glance.
                canvas.fill(self.rect.x, self.rect.y + row, width, 1, base, " ")
            canvas.draw_text(
                self.rect.x,
                self.rect.y + row,
                truncate(f" {item.display}", width),
                base,
                max_width=width,
            )
            room = width - description_column
            if item.description and room > 3:
                canvas.draw_text(
                    self.rect.x + description_column,
                    self.rect.y + row,
                    truncate(item.description, room),
                    Style(foreground=theme.muted, background=base.background),
                    max_width=room,
                )
