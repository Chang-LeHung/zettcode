"""Clipped two-dimensional cell buffer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .style import DEFAULT_STYLE, Cell, Span, Style
from .text import cell_glyph


@dataclass(slots=True)
class Canvas:
    """Clipped two-dimensional cell buffer."""

    width: int
    height: int
    cells: list[list[Cell]] = field(init=False)

    def __post_init__(self) -> None:
        """Allocate the full grid of blank cells."""
        self.cells = [[Cell() for _ in range(self.width)] for _ in range(self.height)]

    def set_cell(self, x: int, y: int, character: str, style: Style = DEFAULT_STYLE) -> int:
        """Draw one printable glyph and return its display width.

        A style that names no background keeps the one already in the cell, so a
        foreground-only span cannot punch a hole through the page fill or the
        panel band it is drawn on top of. ``Canvas.fill`` writes cells verbatim
        and stays the way to clear a region on purpose.
        """
        glyph, width = cell_glyph(character)
        if not (0 <= y < self.height) or x >= self.width:
            return width
        if width == 0:
            if x > 0:
                previous = self.cells[y][x - 1]
                self.cells[y][x - 1] = Cell(previous.character + character, previous.style, previous.continuation)
            return 0
        if x < 0 or x + width > self.width:
            return width
        style = self._keep_background(x, y, style)
        self.cells[y][x] = Cell(glyph, style)
        for offset in range(1, width):
            self.cells[y][x + offset] = Cell("", style, continuation=True)
        return width

    def _keep_background(self, x: int, y: int, style: Style) -> Style:
        """Return ``style`` with the cell's existing background when it names none."""
        if style.background is not None:
            return style
        existing = self.cells[y][x].style.background
        return style if existing is None else replace(style, background=existing)

    def draw_text(
        self,
        x: int,
        y: int,
        text: str,
        style: Style = DEFAULT_STYLE,
        *,
        max_width: int | None = None,
        tab_size: int = 4,
    ) -> int:
        """Draw one unwrapped line and return consumed columns.

        Args:
            x: Left column; may be negative, in which case the text is clipped.
            y: Row; nothing is drawn when it falls outside the canvas.
            text: Single line; ``\\r``, ``\\n``, and anything past the budget stop
                the draw without raising.
            style: Style applied to every painted cell.
            max_width: Column budget counted from ``x``; the canvas edge always
                wins when it is nearer.
            tab_size: Cells between tab stops, used to expand ``\\t`` in place.

        Returns:
            Columns consumed, which is not the same as characters drawn.
        """
        used = 0
        limit = self.width - x if max_width is None else min(max_width, self.width - x)
        for character in text:
            if character in "\r\n":
                break
            if character == "\t":
                spaces = tab_size - ((x + used) % tab_size)
                spaces = min(spaces, max(0, limit - used))
                self.fill(x + used, y, spaces, 1, style)
                used += spaces
                continue
            width = cell_glyph(character)[1]
            if used + width > limit:
                break
            self.set_cell(x + used, y, character, style)
            used += width
        return used

    def draw_spans(self, x: int, y: int, spans: tuple[Span, ...], *, max_width: int | None = None) -> int:
        """Draw styled fragments without crossing the requested width.

        Args:
            x: Left column.
            y: Row.
            spans: Fragments drawn left to right with their own styles.
            max_width: Column budget counted from ``x``; ``None`` uses the
                distance to the canvas edge.

        Returns:
            Columns consumed.
        """
        used = 0
        limit = self.width - x if max_width is None else min(max_width, self.width - x)
        for span in spans:
            if used >= limit:
                break
            used += self.draw_text(x + used, y, span.text, span.style, max_width=limit - used)
        return used

    def fill(self, x: int, y: int, width: int, height: int, style: Style, character: str = " ") -> None:
        """Fill one clipped rectangle.

        Args:
            x: Left column; parts outside the canvas are dropped.
            y: Top row.
            width: Cells to fill horizontally.
            height: Rows to fill vertically.
            style: Style applied to every cell written.
            character: Glyph written into each cell; wide glyphs are not widened.
        """
        for row in range(max(0, y), min(self.height, y + height)):
            for column in range(max(0, x), min(self.width, x + width)):
                self.cells[row][column] = Cell(character, style)

    def restyle(self, x: int, y: int, width: int, transform: Callable[[Style], Style]) -> None:
        """Rewrite the style of one clipped column range, leaving glyphs alone.

        Selection is a repaint of cells that were already drawn, so it must be
        able to change a style without disturbing the character underneath.

        Args:
            x: Left column of the range.
            y: Row to rewrite; out-of-range rows are ignored.
            width: Cells to visit, clipped to the canvas.
            transform: Applied to the current style of each cell; wide glyph
                continuation cells are skipped so only the leader is rewritten.
        """
        if not 0 <= y < self.height:
            return
        for column in range(max(0, x), min(self.width, x + width)):
            cell = self.cells[y][column]
            if cell.continuation:
                continue
            self.cells[y][column] = Cell(cell.character, transform(cell.style), cell.continuation)
