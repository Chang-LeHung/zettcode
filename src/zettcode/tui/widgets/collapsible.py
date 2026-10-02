"""A header that expands to reveal one child."""

from __future__ import annotations

from collections.abc import Callable

from ..core.events import KeyEvent, MouseAction, MouseEvent
from ..core.geometry import Constraints, Rect, Size
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, Style, truncate


class Collapsible(Widget):
    """Show a title row and, when expanded, a body beneath it.

    Shape::

        > Thinking                        <- collapsed: U+25B8, one row only
        v Thinking                        <- expanded: U+25BE
          Checked the renderer.           <- body, directly beneath the header

    Expanding changes the widget's height, so toggling calls
    ``host.request_layout()``; the body is only a child while it is expanded,
    which keeps it out of layout and hit testing when collapsed.
    """

    MARKERS = ("\u25b8", "\u25be")

    def __init__(
        self,
        title: str = "",
        body: Widget | None = None,
        *,
        expanded: bool = False,
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        """Configure the title, the body, and the initial disclosure state.

        Args:
            title: Header text drawn after the disclosure marker.
            body: Child revealed below the header while expanded; ``None`` makes
                the widget a pure header.
            expanded: Whether the body starts visible.
            on_toggle: Called with the new state after every toggle.
        """
        super().__init__()
        self.title = title
        self.body = body
        self.expanded = expanded
        self.on_toggle = on_toggle

    @property
    def focusable(self) -> bool:
        """Take focus so Enter and Space can toggle the header."""
        return True

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the body only while it is expanded."""
        return (self.body,) if self.body is not None and self.expanded else ()

    def toggle(self) -> None:
        """Flip the disclosure state and tell the owner about it."""
        self.expanded = not self.expanded
        if self.on_toggle is not None:
            self.on_toggle(self.expanded)

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the header row, plus the body while it is expanded."""
        if self.body is None or not self.expanded:
            return constraints.constrain(Size(len(self.title) + 2, 1))
        inner = self.body.measure(constraints)
        return constraints.constrain(Size(max(len(self.title) + 2, inner.width), 1 + inner.height))

    def layout(self, rect: Rect) -> None:
        """Reserve the first row for the header and give the rest to the body."""
        super().layout(rect)
        if self.body is not None and self.expanded:
            self.body.layout(Rect(rect.x, rect.y + 1, rect.width, max(0, rect.height - 1)))

    def render(self, canvas: Canvas) -> None:
        """Paint the header marker and title, then the body when expanded."""
        if self.rect.empty:
            return
        theme = self.theme
        marker = self.MARKERS[1] if self.expanded else self.MARKERS[0]
        canvas.draw_text(
            self.rect.x,
            self.rect.y,
            truncate(f"{marker} {self.title}", self.rect.width),
            Style(foreground=theme.accent, bold=True),
            max_width=self.rect.width,
        )
        if self.body is not None and self.expanded:
            self.body.render(canvas)

    def handle(self, event, host: Host) -> bool:
        """Toggle on a click on the header row, or on Enter and Space."""
        if isinstance(event, MouseEvent):
            if self.rect.contains(event.x, event.y) and event.y == self.rect.y:
                if event.action is MouseAction.DOWN:
                    host.focus(self)
                    self.toggle()
                    host.request_layout()
                    return True
            return False
        if not isinstance(event, KeyEvent) or host.focused_widget() is not self:
            return False
        if event.key in ("enter", "space"):
            self.toggle()
            host.request_layout()
            return True
        return False
