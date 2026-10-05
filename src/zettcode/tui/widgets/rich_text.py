"""A retained widget for small styled text blocks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Span, Style, TextLine
from ..render.rich_text import Alignment, layout_rich_lines
from ..render.text import display_width

type RichContent = str | Span | TextLine | Sequence[Span] | Sequence[TextLine]
type RichValue = RichContent | Callable[[], RichContent]


class RichText(Widget):
    """Draw a small block of styled lines, with optional wrapping and alignment.

    A value may be a string, a Span, a TextLine, a sequence of spans or
    lines, or a callable evaluated at paint time. Long histories instead
    use a LineSource and the same ``layout_rich_lines`` function, without
    mounting a widget for each message.

    Args:
        value: Text or lines to show, optionally computed on each paint.
        wrap: Wrap within the given width; otherwise clip with an ellipsis.
        align: ``"left"``, ``"center"``, or ``"right"``.
    """

    def __init__(self, value: RichValue = "", *, wrap: bool = True, align: Alignment = "left") -> None:
        super().__init__()
        if align not in ("left", "center", "right"):
            raise ValueError(f"Unknown alignment: {align!r}")
        self.value = value
        self.wrap = wrap
        self.align = align

    def set_content(self, value: RichValue) -> None:
        """Replace the content and ask the parent to measure it again."""
        self.value = value
        self.request_layout()
        if self.app is not None:
            self.app.request_layout()

    def _lines(self) -> tuple[TextLine, ...]:
        """Resolve the current value into immutable styled lines."""
        value = self.value() if callable(self.value) else self.value
        if isinstance(value, str):
            style = Style(foreground=self.theme.text)
            return tuple(TextLine((Span(line, style),)) for line in value.split("\n"))
        if isinstance(value, Span):
            return (TextLine((value,)),)
        if isinstance(value, TextLine):
            return (value,)
        items: tuple[Span | TextLine, ...] = tuple(value)
        if not items:
            return ()
        if isinstance(items[0], TextLine):
            if not all(isinstance(item, TextLine) for item in items):
                raise TypeError("RichText content cannot mix TextLine and Span")
            return cast(tuple[TextLine, ...], items)
        if not all(isinstance(item, Span) for item in items):
            raise TypeError("RichText content must be Span or TextLine values")
        return (TextLine(cast(tuple[Span, ...], items)),)

    def measure(self, constraints: Constraints) -> Size:
        """Measure the text by visible columns and wrapped line count."""
        lines = self._lines()
        if not lines:
            return constraints.constrain(Size(0, 0))
        natural = max(display_width(line.text) for line in lines)
        width = min(natural, constraints.max_width) if constraints.max_width is not None else natural
        height = len(layout_rich_lines(lines, max(1, width), wrap=self.wrap, align=self.align))
        return constraints.constrain(Size(width, height))

    def render(self, canvas: Canvas) -> None:
        """Paint only rows inside the assigned rectangle."""
        if self.rect.empty:
            return
        rows = layout_rich_lines(self._lines(), self.rect.width, wrap=self.wrap, align=self.align)
        for offset, row in enumerate(rows[: self.rect.height]):
            canvas.draw_spans(self.rect.x, self.rect.y + offset, row.spans, max_width=self.rect.width)
