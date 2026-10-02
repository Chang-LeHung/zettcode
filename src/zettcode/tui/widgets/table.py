"""A table widget that paints the same shape as a Markdown table."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas
from ..render.text import display_width
from .markdown import render_table

ALIGNMENTS = ("left", "center", "right")


@dataclass(frozen=True, slots=True)
class Column:
    """One table column and how its cells line up.

    Attributes:
        title: Header text; an empty title on every column hides the header row.
        align: One of ``ALIGNMENTS``; anything else is rejected.
        width: Pins the column to a fixed cell count. It is still raised to the
            renderer's minimum and shrunk when the width budget is tight;
            ``None`` lets the column take its natural width.
    """

    title: str = ""
    align: str = "left"
    width: int | None = None

    def __post_init__(self) -> None:
        """Reject alignments the table renderer does not know."""
        if self.align not in ALIGNMENTS:
            raise ValueError(f"Unknown alignment: {self.align!r}")


class Table(Widget):
    """Lay rows out in columns that always fit the widget rectangle.

    Rendering is delegated to the Markdown table renderer so a table looks the
    same wherever it comes from: a header, one rule per column, and cells that
    wrap instead of being cut. ``Column.width`` pins a column when needed.
    """

    def __init__(
        self,
        columns: Sequence[Column],
        rows: Sequence[Sequence[str]] = (),
        *,
        header: bool = True,
    ) -> None:
        """Store the columns and rows; a header hides itself when no title is set.

        Args:
            columns: Column definitions, left to right.
            rows: Cell text, padded and truncated to the column count.
            header: Draw the title row; ignored when every title is empty.
        """
        super().__init__()
        self.columns = tuple(columns)
        self.rows = tuple(tuple(row) for row in rows)
        self.header = header and any(column.title for column in self.columns)

    @property
    def body_height(self) -> int:
        """Return how many body rows the table holds."""
        return len(self.rows)

    def measure(self, constraints: Constraints) -> Size:
        """Estimate the natural width from the titles and one row per entry."""
        widest = sum(display_width(column.title) + 3 for column in self.columns)
        return constraints.constrain(Size(widest, len(self.rows) + int(self.header)))

    def render(self, canvas: Canvas) -> None:
        """Delegate to the Markdown renderer, dropping the header when it is hidden."""
        if not self.columns or self.rect.empty:
            return
        lines = render_table(
            [column.title for column in self.columns],
            [column.align for column in self.columns],
            [list(row) for row in self.rows],
            self.rect.width,
            self.theme,
            fixed=[column.width for column in self.columns],
        )
        if not self.header:
            lines = lines[2:]
        for index, line in enumerate(lines[: self.rect.height]):
            canvas.draw_spans(self.rect.x, self.rect.y + index, line.spans, max_width=self.rect.width)
