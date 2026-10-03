"""A compact panel of ordered tasks with one of them in progress."""

from __future__ import annotations

from collections.abc import Sequence

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import display_width

MARKERS = {
    "completed": "\u2713",
    "processing": "\u25b8",
    "pending": "\u00b7",
}


class TaskPanel(Widget):
    """Show ordered tasks; a panel with no tasks occupies no space.

    The widget only knows about a state name and a label, which keeps the
    framework free of any particular task vocabulary.

    Shape::

          Plan                             <- title, muted
          x read the renderer              <- completed: muted, U+2713
          > preview widgets                <- processing: accent, bold, U+25B8
          . run make check                 <- pending: body text, U+00B7

    An unknown state falls back to the pending dot, and ``preferred_height()``
    is the slot size an owner passes to keep the panel exactly as tall as its
    contents (zero rows when there is nothing to show).
    """

    def __init__(self, title: str = "Plan") -> None:
        """Start empty; the panel occupies no space until tasks arrive.

        Args:
            title: Heading drawn above the rows, indented by two spaces.
        """
        super().__init__()
        self.title = title
        self.tasks: tuple[tuple[str, str], ...] = ()

    @property
    def visible(self) -> bool:
        """Return whether the panel has anything to show."""
        return bool(self.tasks)

    def set_tasks(self, tasks: Sequence[tuple[str, str]]) -> bool:
        """Replace the list and report whether anything actually changed.

        Args:
            tasks: ``(state, label)`` pairs in display order. ``state`` is looked
                up in ``MARKERS`` for the glyph and for the colour; an unknown
                state falls back to a neutral dot.
        """
        updated = tuple((state, label) for state, label in tasks)
        if updated == self.tasks:
            return False
        self.tasks = updated
        self.invalidate()
        return True

    def preferred_height(self) -> int:
        """Return the rows needed for the title and one row per task."""
        return len(self.tasks) + 1 if self.tasks else 0

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest task label plus the marker indentation."""
        width = max((display_width(label) for _, label in self.tasks), default=0) + 4
        return constraints.constrain(Size(width, self.preferred_height()))

    def render(self, canvas: Canvas) -> None:
        """Paint the title and one row per task, coloured by state."""
        if not self.tasks or self.rect.empty:
            return
        theme = self.theme
        canvas.draw_text(
            self.rect.x,
            self.rect.y,
            truncate(f"  {self.title}", self.rect.width),
            Style(foreground=theme.muted, bold=True),
            max_width=self.rect.width,
        )
        for offset, (state, label) in enumerate(self.tasks):
            row = self.rect.y + offset + 1
            if row >= self.rect.y + self.rect.height:
                return
            marker = MARKERS.get(state, "\u00b7")
            if state == "completed":
                style = Style(foreground=theme.muted)
            elif state == "processing":
                style = Style(foreground=theme.accent, bold=True)
            else:
                style = Style(foreground=theme.text)
            canvas.draw_text(
                self.rect.x,
                row,
                truncate(f"  {marker} {label}", self.rect.width),
                style,
                max_width=self.rect.width,
            )
