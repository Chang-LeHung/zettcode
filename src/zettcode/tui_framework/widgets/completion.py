"""Completion candidates shown next to an editor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import DEFAULT_STYLE, Canvas, Style, truncate
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
    """A framed, scrolling list of completion candidates.

    The popup never takes focus: the editor keeps the cursor and drives the
    selection, so Tab and Enter still belong to the text being typed.
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
            max_height: Most candidate rows to show; the frame adds two more.
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
        """Return how many candidate rows the popup will show at most."""
        return min(len(self.items), self.max_height)

    def preferred_size(self) -> Size:
        """Size the popup to its widest candidate and the visible rows."""
        widest = max(
            (display_width(item.display) + display_width(item.description) + 2 for item in self.items), default=0
        )
        return Size(widest + 2, self.visible_height + 2)

    def measure(self, constraints: Constraints) -> Size:
        """Clamp the preferred size into the offered constraints."""
        return constraints.constrain(self.preferred_size())

    def render(self, canvas: Canvas) -> None:
        """Draw the frame and visible candidates, keeping the selection on screen."""
        if not self.items or self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, DEFAULT_STYLE, " ")
        width = self.rect.width
        if self.rect.height >= 2:
            canvas.draw_text(
                self.rect.x,
                self.rect.y,
                truncate("\u250c" + "\u2500" * max(0, width - 2) + "\u2510", width),
                Style(foreground=theme.border),
                max_width=width,
            )
            canvas.draw_text(
                self.rect.x,
                self.rect.y + self.rect.height - 1,
                truncate("\u2514" + "\u2500" * max(0, width - 2) + "\u2518", width),
                Style(foreground=theme.border),
                max_width=width,
            )
        rows = max(1, self.rect.height - 2)
        self.top = min(self.top, max(0, len(self.items) - rows))
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + rows:
            self.top = self.selected - rows + 1
        for row in range(rows):
            index = self.top + row
            if index >= len(self.items):
                break
            item = self.items[index]
            selected = index == self.selected
            style = (
                Style(foreground=theme.text, background=theme.selection, bold=True)
                if selected
                else Style(foreground=theme.text)
            )
            canvas.draw_text(self.rect.x, self.rect.y + row + 1, "\u2502", Style(foreground=theme.border))
            canvas.draw_text(
                self.rect.x + 1,
                self.rect.y + row + 1,
                truncate(f" {item.display}", max(0, width - 2)),
                style,
                max_width=max(0, width - 2),
            )
            if item.description:
                used = display_width(item.display) + 3
                room = width - used - 1
                if room > 3:
                    canvas.draw_text(
                        self.rect.x + used,
                        self.rect.y + row + 1,
                        truncate(item.description, room),
                        Style(foreground=theme.muted, background=style.background),
                        max_width=room,
                    )
            canvas.draw_text(self.rect.x + width - 1, self.rect.y + row + 1, "\u2502", Style(foreground=theme.border))
