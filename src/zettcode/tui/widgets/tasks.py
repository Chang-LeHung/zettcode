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

                                           <- blank row, so the box is not glued
        \u250c Plan \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510      to the transcript above
        \u2502 \u2713 read the renderer      \u2502   <- completed: muted, struck out
        \u2502 \u25b8 preview widgets        \u2502   <- processing: accent, bold, U+25B8
        \u2502 \u00b7 run make check         \u2502   <- pending: body text, U+00B7
        \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518

    An unknown state falls back to the pending dot, and ``preferred_height()``
    is the slot size an owner passes to keep the panel exactly as tall as its
    contents (zero rows when there is nothing to show). A panel too narrow for a
    frame drops it and keeps the rows.
    """

    #: Frame glyphs; the title rides in the top edge to save a row.
    TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT = "\u250c", "\u2510", "\u2514", "\u2518"
    HORIZONTAL, VERTICAL = "\u2500", "\u2502"
    #: Cells of frame around the rows, and the blank row above the frame.
    FRAME_COLUMNS = 4
    SEPARATOR_ROWS = 1

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
        """Return the rows needed for the separator, the frame, and the tasks."""
        return len(self.tasks) + 3 if self.tasks else 0

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest task label plus the marker and the frame."""
        width = max((display_width(label) for _, label in self.tasks), default=0) + self.FRAME_COLUMNS
        return constraints.constrain(Size(width, self.preferred_height()))

    def render(self, canvas: Canvas) -> None:
        """Paint the frame, one row per task, and the heading in the top edge."""
        if not self.tasks or self.rect.empty:
            return
        theme = self.theme
        frame = Style(foreground=theme.border)
        heading = Style(foreground=theme.muted, bold=True)
        # The separator row is outside the frame, so the box never sits flush
        # against the transcript it follows.
        top = self.rect.y + self.SEPARATOR_ROWS
        width = self.rect.width
        label = f" {self.title} "
        framed = width >= 4 + display_width(label) and self.rect.height > self.SEPARATOR_ROWS + 2
        if framed:
            rule = self.HORIZONTAL * max(0, width - 2 - display_width(label))
            canvas.draw_text(self.rect.x, top, self.TOP_LEFT, frame)
            canvas.draw_text(self.rect.x + 1, top, label, heading, max_width=display_width(label))
            canvas.draw_text(self.rect.x + 1 + display_width(label), top, f"{rule}{self.TOP_RIGHT}", frame)
        for offset, (state, text) in enumerate(self.tasks):
            row = top + offset + (1 if framed else 0)
            if row >= self.rect.y + self.rect.height:
                return
            marker = MARKERS.get(state, "\u00b7")
            if state == "completed":
                # A finished task is struck out as well as dimmed, so a long
                # plan shows what is left at a glance.
                style = Style(foreground=theme.muted, strike=True)
            elif state == "processing":
                style = Style(foreground=theme.accent, bold=True)
            else:
                style = Style(foreground=theme.text)
            if not framed:
                canvas.draw_text(self.rect.x, row, truncate(f"  {marker} {text}", width), style, max_width=width)
                continue
            canvas.draw_text(self.rect.x, row, self.VERTICAL, frame)
            room = max(0, width - self.FRAME_COLUMNS)
            canvas.draw_text(self.rect.x + 2, row, truncate(f"{marker} {text}", room), style, max_width=room)
            canvas.draw_text(self.rect.x + width - 1, row, self.VERTICAL, frame)
        if framed:
            row = top + len(self.tasks) + 1
            if row < self.rect.y + self.rect.height:
                floor = f"{self.BOTTOM_LEFT}{self.HORIZONTAL * max(0, width - 2)}{self.BOTTOM_RIGHT}"
                canvas.draw_text(self.rect.x, row, floor, frame, max_width=width)
