"""ANSI differential renderer that writes only changed cell ranges."""

from __future__ import annotations

from io import StringIO
from typing import TextIO

from .canvas import Canvas
from .color import ColorDepth, encode_style
from .style import Cell, Style

#: Synchronized output (DEC private mode 2026). A terminal that knows it holds back the screen from the first byte
#: after ``BEGIN_SYNC`` to the ``END_SYNC``, then shows the whole frame at once; one that does not know it ignores
#: the mode, as any terminal ignores a private mode it has no name for. Without it, a terminal may refresh while a
#: frame is half parsed, and a quick drag shows what the frame was in the middle of: the old place erased and the
#: new one not yet painted.
BEGIN_SYNC = "\x1b[?2026h"
END_SYNC = "\x1b[?2026l"
#: DECTCEM hide and show, the pair this renderer moves the cursor with.
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"

#: Stands for "no frame has been written yet", which no cursor position equals.
_UNKNOWN = object()


class DifferentialRenderer:
    """Write only changed cell ranges since the previous frame.

    The vocabulary is deliberately small: Erase in Display (``ED``), Cursor
    Position (``CUP``), Select Graphic Rendition (``SGR``), the cursor
    show/hide pair, and the begin/end of a synchronized update. Anything else
    would change a mode this renderer has no way to restore.

    A frame that paints something is one synchronized update, drawn with the
    cursor hidden and shown again where a widget wants it at the end, so a
    terminal that cannot hold the update back still does not show the cursor
    running across the cells as they are written.
    """

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
        #: Where the cursor was left by the last frame (``None`` is hidden), or ``_UNKNOWN`` before any frame: a
        #: frame that changes no cell and wants the cursor where it already is has nothing to say.
        self._cursor: tuple[int, int] | None | object = _UNKNOWN

    def reset(self) -> None:
        """Forget the previous frame so the next render repaints everything."""
        self.previous = None
        self._cursor = _UNKNOWN

    def render(self, canvas: Canvas, *, cursor: tuple[int, int] | None = None) -> None:
        """Emit only the cells that differ from the previous frame.

        Args:
            canvas: The frame to display.
            cursor: Cell to place the terminal cursor on, or ``None`` to hide it.
                A size change on canvas forces a full repaint regardless.
        """
        full = self.previous is None or (self.previous.width, self.previous.height) != (canvas.width, canvas.height)
        stream = StringIO()
        painted = False
        if full:
            # ED 2 erases the whole display. A resize renumbers every cell, so
            # diffing against the old frame would leave stale glyphs behind.
            stream.write("\x1b[2J")
            painted = True
        for y, row in enumerate(canvas.cells):
            previous_row = None if full or self.previous is None else self.previous.cells[y]
            if previous_row == row:
                continue  # An untouched row costs no bytes at all.
            painted = True
            start, end = _changed_bounds(row, previous_row)
            # CUP carries a 1-based row and column; the canvas is 0-based.
            stream.write(f"\x1b[{y + 1};{start + 1}H")
            active_style: Style | None = None
            for cell in row[start : end + 1]:
                if cell.continuation:
                    continue  # The wide glyph's leading cell painted this column.
                if cell.style != active_style:
                    # SGR is stateful, so it is emitted only where a run's style
                    # actually changes rather than once per cell.
                    stream.write(encode_style(cell.style, self.color_depth))
                    active_style = cell.style
                stream.write(cell.character or " ")
            # SGR 0 resets colour and attributes before the next CUP, so a run
            # cannot bleed past the row it belongs to.
            stream.write("\x1b[0m")
        if cursor is None:
            # DECTCEM hide: no widget asked for the cursor this frame. A frame that painted hid it before the first
            # cell, so only a frame that painted nothing has to say so.
            if not painted:
                stream.write(HIDE_CURSOR)
        else:
            x, y = cursor
            # Move first, then show: CUP on its own leaves the cursor hidden.
            stream.write(f"\x1b[{y + 1};{x + 1}H{SHOW_CURSOR}")
        frame = stream.getvalue()
        if painted:
            # The cursor goes first, so a terminal that ignores the update still never shows it mid-frame; the
            # tail puts it back where a widget wants it.
            frame = f"{BEGIN_SYNC}{HIDE_CURSOR}{frame}{END_SYNC}"
        elif cursor == self._cursor:
            # Nothing changed on the screen or at the cursor: there is nothing to send.
            self.previous = canvas
            return
        self._cursor = cursor
        self.output.write(frame)
        self.output.flush()
        self.previous = canvas


def _changed_bounds(row: list[Cell], previous: list[Cell] | None) -> tuple[int, int]:
    """Return an inclusive column range that safely repaints every changed cell.

    Args:
        row: The row being painted.
        previous: The same row one frame earlier, or ``None`` when the frame is
            painted from scratch, in which case the whole row counts as changed.

    Returns:
        ``(start, end)``, both inclusive. The range is widened outward to whole
        glyphs, so it may cover cells that did not change; ``end < start`` means
        the rows are identical and nothing has to be painted.
    """
    if previous is None:
        return 0, len(row) - 1

    changed = [index for index, cell in enumerate(row) if cell != previous[index]]
    if not changed:
        # An empty range keeps this a total function: a caller that forgot to
        # skip an identical row gets "nothing to paint" instead of an IndexError.
        return 0, -1
    start, end = changed[0], changed[-1]

    # A wide glyph occupies a leading cell plus one or more continuation cells.
    # Include its leader so replacing either half never leaves a stale terminal glyph.
    while start > 0 and (row[start].continuation or previous[start].continuation):
        start -= 1
    while end + 1 < len(row) and (row[end + 1].continuation or previous[end + 1].continuation):
        end += 1
    return start, end
