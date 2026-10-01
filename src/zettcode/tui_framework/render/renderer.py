"""ANSI differential renderer that writes only changed cell ranges."""

from __future__ import annotations

from io import StringIO
from typing import TextIO

from .canvas import Canvas
from .color import ColorDepth, encode_style
from .style import Cell, Style


class DifferentialRenderer:
    """Write only changed cell ranges since the previous frame."""

    def __init__(self, output: TextIO, *, color_depth: ColorDepth = ColorDepth.TRUECOLOR) -> None:
        """Write frames to ``output`` at the given colour depth.

        Args:
            output: Text stream to write ANSI to; a real terminal or a StringIO
                in tests.
            color_depth: How precisely colours may be encoded.
        """
        self.output = output
        self.color_depth = color_depth
        self.previous: Canvas | None = None

    def reset(self) -> None:
        """Forget the previous frame so the next render repaints everything."""
        self.previous = None

    def render(self, canvas: Canvas, *, cursor: tuple[int, int] | None = None) -> None:
        """Emit only the cells that differ from the previous frame.

        Args:
            canvas: The frame to display.
            cursor: Cell to place the terminal cursor on, or ``None`` to hide it.
                A size change on canvas forces a full repaint regardless.
        """
        full = self.previous is None or (self.previous.width, self.previous.height) != (canvas.width, canvas.height)
        stream = StringIO()
        if full:
            stream.write("\x1b[2J")
        for y, row in enumerate(canvas.cells):
            previous_row = None if full or self.previous is None else self.previous.cells[y]
            if previous_row == row:
                continue
            start, end = _changed_bounds(row, previous_row)
            stream.write(f"\x1b[{y + 1};{start + 1}H")
            active_style: Style | None = None
            for cell in row[start : end + 1]:
                if cell.continuation:
                    continue
                if cell.style != active_style:
                    stream.write(encode_style(cell.style, self.color_depth))
                    active_style = cell.style
                stream.write(cell.character or " ")
            stream.write("\x1b[0m")
        if cursor is None:
            stream.write("\x1b[?25l")
        else:
            x, y = cursor
            stream.write(f"\x1b[{y + 1};{x + 1}H\x1b[?25h")
        self.output.write(stream.getvalue())
        self.output.flush()
        self.previous = canvas


def _changed_bounds(row: list[Cell], previous: list[Cell] | None) -> tuple[int, int]:
    """Return a glyph-safe inclusive range containing every changed cell."""
    if previous is None:
        return 0, len(row) - 1

    changed = [index for index, cell in enumerate(row) if cell != previous[index]]
    start, end = changed[0], changed[-1]

    # A wide glyph occupies a leading cell plus one or more continuation cells.
    # Include its leader so replacing either half never leaves a stale terminal glyph.
    while start > 0 and (row[start].continuation or previous[start].continuation):
        start -= 1
    while end + 1 < len(row) and (row[end + 1].continuation or previous[end + 1].continuation):
        end += 1
    return start, end
