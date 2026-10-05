"""One-line status bar with left and right segments."""

from __future__ import annotations

from collections.abc import Callable

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import DEFAULT_STYLE, Canvas, Span, Style, TextLine, truncate_spans

type Text = str | TextLine | Callable[[], str | TextLine]


class StatusBar(Widget):
    """Render a left-aligned and a right-aligned segment on one row.

    Shape::

        zettcode              openai/gpt-5 <- right segment, flush to the edge
        ^^^^^^^^^^^^^^^^^^^^^^                ^^^^^^^^^^^^^
        left segment                          never truncated

    The right segment wins when space runs out: it keeps its width and the left
    one is cut instead. A right segment wider than the whole row is drawn alone.
    Either segment may be a callable, read once per paint.

    A segment can be a styled :class:`~zettcode.tui.render.TextLine`; its spans
    keep their own colours and attributes. A span that sets no style of its own
    is painted with the bar's muted style, so a plain ``str``, an unstyled line,
    and the golden default all look the same.
    """

    def __init__(self, left: Text = "", right: Text = "") -> None:
        """Store both segments; either may be a callback evaluated at paint time.

        Args:
            left: Drawn at the left edge, truncated when the right segment wins.
            right: Drawn flush to the right edge; it is never truncated, so it
                keeps the width it asks for even at the left segment's expense.
        """
        super().__init__()
        self.left = left
        self.right = right

    def measure(self, constraints: Constraints) -> Size:
        """Ask for one row and the combined width of both segments."""
        wanted = self._line(self.left).width + self._line(self.right).width
        return constraints.constrain(Size(wanted, 1))

    def render(self, canvas: Canvas) -> None:
        """Draw both segments, letting the right one win when space runs out."""
        if self.rect.empty:
            return
        left = self._line(self.left)
        right = self._line(self.right)
        right_width = right.width
        if right_width >= self.rect.width:
            canvas.draw_spans(
                self.rect.x,
                self.rect.y,
                truncate_spans(right.spans, self.rect.width),
                max_width=self.rect.width,
            )
            return
        room = self.rect.width - right_width
        canvas.draw_spans(self.rect.x, self.rect.y, truncate_spans(left.spans, room), max_width=room)
        canvas.draw_spans(
            self.rect.x + self.rect.width - right_width,
            self.rect.y,
            right.spans,
            max_width=right_width,
        )

    def _line(self, text: Text) -> TextLine:
        """Resolve a segment to a styled line, applying the bar style to bare spans."""
        value = text() if callable(text) else text
        fallback = Style(foreground=self.theme.muted)
        if isinstance(value, TextLine):
            return TextLine(tuple(self._tint(span, fallback) for span in value.spans), metadata=value.metadata)
        return TextLine((Span(value, fallback),))

    @staticmethod
    def _tint(span: Span, fallback: Style) -> Span:
        """Give an unstyled span the bar's style, leaving designed spans alone."""
        return span if span.style != DEFAULT_STYLE else Span(span.text, fallback)
