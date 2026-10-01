"""A framed modal body with a row of selectable actions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..core.events import KeyEvent
from ..core.geometry import Constraints, Rect, Size
from ..core.host import Host
from ..core.widget import Widget
from ..layout import Border, Slot, VBox
from ..render import Canvas, Style
from ..render.text import display_width


@dataclass(frozen=True, slots=True)
class DialogAction:
    """One button in a dialog.

    Attributes:
        label: Text drawn on the button.
        run: Called when the action is activated; ``None`` renders a button that
            cannot be committed.
    """

    label: str
    run: Callable[[], None] | None = None


class _ActionRow(Widget):
    """Internal row that paints the dialog buttons."""

    def __init__(self, dialog: Dialog) -> None:
        """Bind the row to the dialog that owns the actions."""
        super().__init__()
        self.dialog = dialog

    def measure(self, constraints: Constraints) -> Size:
        """Claim a minimal cell; the parent box supplies the real width."""
        return constraints.constrain(Size(1, 1))

    def render(self, canvas: Canvas) -> None:
        """Paint the actions along the last row of the assigned rectangle."""
        if self.rect.empty:
            return
        theme = self.theme
        y = self.rect.y + self.rect.height - 1
        x = self.rect.x
        for index, action in enumerate(self.dialog.actions):
            if x >= self.rect.x + self.rect.width:
                break
            label = f" {action.label} "
            selected = index == self.dialog.action_index
            style = (
                Style(foreground=theme.background, background=theme.accent, bold=True)
                if selected
                else Style(foreground=theme.muted)
            )
            canvas.draw_text(x, y, label, style, max_width=self.rect.x + self.rect.width - x)
            x += display_width(label) + 1


class Dialog(Widget):
    """A bordered body plus actions, meant to live on a modal screen."""

    def __init__(
        self,
        body: Widget | None = None,
        *,
        title: str = "",
        actions: Sequence[DialogAction] = (),
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Wrap the body and the action row in a border, with or without a body.

        Args:
            body: Content above the buttons; ``None`` leaves a dialog of pure
                actions, which is still laid out with the same frame.
            title: Drawn into the top border when the dialog is wide enough.
            actions: Buttons in focus order; the first one starts highlighted.
            on_cancel: Called on Escape when one is provided.
        """
        super().__init__()
        self.body = body
        self.actions = tuple(actions)
        self.action_index = 0
        self.on_cancel = on_cancel
        row = _ActionRow(self)
        inner = VBox([Slot(body, flex=1), Slot(row, size=1)]) if body is not None else VBox([Slot(row, flex=1)])
        self.frame = Border(inner, title=title)

    @property
    def focusable(self) -> bool:
        """Take focus so the arrow keys and Enter drive the actions."""
        return True

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the bordered frame."""
        return (self.frame,)

    @property
    def current_action(self) -> DialogAction | None:
        """Return the highlighted action, or None when there are no actions."""
        if 0 <= self.action_index < len(self.actions):
            return self.actions[self.action_index]
        return None

    def activate(self) -> bool:
        """Run the selected action, if it has a handler."""
        action = self.current_action
        if action is None or action.run is None:
            return False
        action.run()
        return True

    def measure(self, constraints: Constraints) -> Size:
        """Measure the frame, which measures the body in turn."""
        return self.frame.measure(constraints)

    def layout(self, rect: Rect) -> None:
        """Give the frame the whole assigned rectangle."""
        super().layout(rect)
        self.frame.layout(rect)

    def render(self, canvas: Canvas) -> None:
        """Paint the frame and everything inside it."""
        self.frame.render(canvas)

    def handle(self, event, host: Host) -> bool:
        """Move between actions, run one, or cancel the dialog."""
        if not isinstance(event, KeyEvent) or host.focused_widget() is not self:
            return False
        match event.key:
            case "left" | "backtab":
                self._move(-1)
            case "right" | "tab":
                self._move(1)
            case "enter":
                return self.activate()
            case "escape" if self.on_cancel is not None:
                self.on_cancel()
                return True
            case _:
                return False
        return True

    def _move(self, amount: int) -> None:
        """Move the highlight, wrapping at both ends."""
        if self.actions:
            self.action_index = (self.action_index + amount) % len(self.actions)
