"""Layout styled lines without requiring a mounted widget.

RichText widgets and virtualized LineSources use the same column-aware
wrapping and indentation. The resulting TextLines are plain render data;
scrolling and focus stay with the widget that presents them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeAlias

from .style import Span, TextLine
from .text import truncate_spans, wrap_spans

Alignment: TypeAlias = Literal["left", "center", "right"]


def inset_line(line: TextLine, columns: int) -> TextLine:
    """Shift a nonblank line right, retaining the style of its first run."""
    if columns <= 0 or not line.spans:
        return line
    first, *rest = line.spans
    return TextLine((Span(" " * columns + first.text, first.style), *rest), metadata=line.metadata)


def layout_rich_lines(
    lines: Sequence[TextLine],
    width: int,
    *,
    wrap: bool = True,
    align: Alignment = "left",
) -> tuple[TextLine, ...]:
    """Wrap or truncate styled lines within a display-column budget.

    ``TextLine.metadata`` may contain an integer hanging indent. That indent
    is applied to continuation rows, so a list wraps beneath its own text.
    Alignment adds space only to rows narrower than the available width.
    """
    if width <= 0:
        return ()
    if align not in ("left", "center", "right"):
        raise ValueError(f"Unknown alignment: {align!r}")
    laid_out: list[TextLine] = []
    for line in lines:
        indent = line.metadata if isinstance(line.metadata, int) and line.metadata > 0 else 0
        if wrap:
            rows = wrap_spans(line.spans, width)
            if len(rows) > 1 and indent:
                remainder = tuple(span for row in rows[1:] for span in row)
                rows = [rows[0], *wrap_spans(remainder, max(1, width - min(indent, width - 1)))]
        else:
            rows = [truncate_spans(line.spans, width)]
        for position, spans in enumerate(rows):
            row = TextLine(tuple(spans))
            if wrap and position and indent:
                row = inset_line(row, min(indent, width - 1))
            used = row.width
            if used > width:
                row = TextLine(truncate_spans(row.spans, width))
                used = row.width
            if align != "left" and used < width and row.spans:
                gap = (width - used) // 2 if align == "center" else width - used
                row = inset_line(row, gap)
            laid_out.append(row)
    return tuple(laid_out)
