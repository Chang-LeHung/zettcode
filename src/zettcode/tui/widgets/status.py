"""One-line status bar with left and right segments."""

from __future__ import annotations

from collections.abc import Callable

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import display_width

Text = str | Callable[[], str]


class StatusBar(Widget):
    """Render a left-aligned and a right-aligned segment on one row.

    Shape::

        zettcode              openai/gpt-5 <- right segment, flush to the edge
        ^^^^^^^^^^^^^^^^^^^^^^                ^^^^^^^^^^^^^
        left segment                          never truncated

    The right segment wins when space runs out: it keeps its width and the left
    one is cut instead. A right segment wider than the whole row is drawn alone.
    Either segment may be a callable, read once per paint.
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
        wanted = display_width(self._value(self.left)) + display_width(self._value(self.right))
        return constraints.constrain(Size(wanted, 1))

    def render(self, canvas: Canvas) -> None:
        """Draw both segments, letting the right one win when space runs out."""
        if self.rect.empty:
            return
        theme = self.theme
        style = Style(foreground=theme.muted)
        left = self._value(self.left)
        right = self._value(self.right)
        right_width = display_width(right)
        if right_width >= self.rect.width:
            canvas.draw_text(
                self.rect.x,
                self.rect.y,
                truncate(right, self.rect.width),
                style,
                max_width=self.rect.width,
            )
            return
        room = self.rect.width - right_width
        canvas.draw_text(self.rect.x, self.rect.y, truncate(left, room), style, max_width=room)
        canvas.draw_text(
            self.rect.x + self.rect.width - right_width,
            self.rect.y,
            right,
            style,
            max_width=right_width,
        )

    @staticmethod
    def _value(text: Text) -> str:
        """Resolve a segment, calling it when it is a provider."""
        return text() if callable(text) else text
