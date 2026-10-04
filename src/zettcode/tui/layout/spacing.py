"""Containers that reserve space around a single child."""

from __future__ import annotations

from ...tui import RULE
from ..core.geometry import Constraints, EdgeInsets, Point, Rect, Size
from ..core.widget import Widget
from ..render import DEFAULT_STYLE, Canvas, Style


class Padding(Widget):
    """Place one child inside an inset rectangle.

    Shape::

        +---------------------+  <- the widget's own rectangle (draws nothing)
        |  +---------------+  |
        |  | child         |  |  <- child gets rect.inset(edges)
        |  +---------------+  |
        +---------------------+

    It contributes no glyphs of its own; it only deflates the constraints on
    the way down and adds the edges back on the way up, so the parent's budget
    stays exact.
    """

    def __init__(self, child: Widget, edges: EdgeInsets | int = 1) -> None:
        """Accept a full EdgeInsets or one value applied to all four sides.

        Args:
            child: The single widget placed inside the inset rectangle.
            edges: Spacing reserved on each side, in cells.
        """
        super().__init__()
        self.child = child
        self.edges = edges if isinstance(edges, EdgeInsets) else EdgeInsets.all(edges)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the single child that receives the inset rectangle."""
        return (self.child,)

    def measure(self, constraints: Constraints) -> Size:
        """Measure the child inside the deflated constraints, then add the edges back."""
        inner = self.child.measure(constraints.deflate(self.edges))
        wanted = Size(inner.width + self.edges.horizontal, inner.height + self.edges.vertical)
        return constraints.constrain(wanted)

    def layout(self, rect: Rect) -> None:
        """Give the child the assigned rectangle minus the padding."""
        super().layout(rect)
        self.child.layout(rect.inset(self.edges))

    def render(self, canvas: Canvas) -> None:
        """Paint the child; padding itself draws nothing."""
        self.child.render(canvas)

    def cursor(self) -> Point | None:
        """Forward the cursor request to the child."""
        return self.child.cursor()


class Border(Widget):
    """Draw a box around one child and inset it by the drawn frame.

    Shape::

        +-- title ---------+  <- title only when the frame is wider than 4 cells
        |child             |  <- child gets rect.inset(1), one cell on every side
        |                  |
        +------------------+

    The frame is box-drawing (U+250C, U+2500, U+2502, U+2514). It clears its own
    rectangle before drawing, which is what lets a panel sit over another screen
    without letting it show through; a border with no child still draws.
    """

    HORIZONTAL = RULE
    VERTICAL = "\u2502"

    def __init__(self, child: Widget | None = None, *, style: Style = DEFAULT_STYLE, title: str = "") -> None:
        """Draw a frame around ``child``; a border without a child is still valid.

        Args:
            child: Content inset by one cell on each side; ``None`` draws the
                frame alone.
            style: Style of the frame glyphs, not of the child.
            title: Text embedded in the top border; only drawn when the frame is
                wider than four cells, otherwise it is dropped.
        """
        super().__init__()
        self.child = child
        self.style = style
        self.title = title

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the child, if this border has one."""
        return (self.child,) if self.child is not None else ()

    def measure(self, constraints: Constraints) -> Size:
        """Measure the child inside the frame and reserve two cells per axis."""
        inner = self.child.measure(constraints.deflate(EdgeInsets.all(1))) if self.child else Size(0, 0)
        wanted = Size(inner.width + 2, inner.height + 2)
        return constraints.constrain(wanted)

    def layout(self, rect: Rect) -> None:
        """Reserve one cell on every side for the frame."""
        super().layout(rect)
        if self.child is not None:
            self.child.layout(rect.inset(1))

    def render(self, canvas: Canvas) -> None:
        """Clear the panel, then draw the frame, the title, and the child."""
        if self.rect.empty:
            return
        # A framed panel is a surface, not a frame drawn over someone else's
        # text: clear its own rectangle so no earlier screen shows through.
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, DEFAULT_STYLE, " ")
        width = self.rect.width
        rule = self.HORIZONTAL * max(0, width - 2)
        canvas.draw_text(self.rect.x, self.rect.y, f"\u250c{rule}\u2510", self.style)
        for row in range(1, max(1, self.rect.height - 1)):
            y = self.rect.y + row
            canvas.draw_text(self.rect.x, y, self.VERTICAL, self.style)
            canvas.draw_text(self.rect.x + width - 1, y, self.VERTICAL, self.style)
        if self.rect.height > 1:
            canvas.draw_text(self.rect.x, self.rect.y + self.rect.height - 1, f"\u2514{rule}\u2518", self.style)
        if self.title and width > 4:
            canvas.draw_text(self.rect.x + 2, self.rect.y, f" {self.title} ", self.style, max_width=width - 4)
        if self.child is not None:
            self.child.render(canvas)

    def cursor(self) -> Point | None:
        """Forward the cursor request to the child, if there is one."""
        return self.child.cursor() if self.child is not None else None
