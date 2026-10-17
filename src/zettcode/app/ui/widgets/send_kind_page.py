"""The bottom-panel question a message typed during a request has to answer: steer, or follow up?"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zettcode._compat import StrEnum
from zettcode.tui import MARKER, PROMPT, SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import Style, truncate

from .follow_up import one_line
from .panel import pressed


class SendKind(StrEnum):
    """What a message typed while the agent is working should do.

    Attributes:
        FOLLOW_UP: Hold it, and send it as a turn of its own when this request ends.
        STEER: Hand it to the agent now; it is adopted at the next model or tool
            boundary and replaces the rest of the current task.
    """

    FOLLOW_UP = "follow_up"
    STEER = "steer"


@dataclass(frozen=True, slots=True)
class SendOption:
    """One numbered row of the question.

    Attributes:
        kind: The answer this row gives.
        key: Key that picks the row outright.
        label: The name of the kind.
        detail: What it does, in a sentence.
    """

    kind: SendKind
    key: str
    label: str
    detail: str


#: Rows in the order shown. Follow-up comes first and is highlighted first: it is the one
#: that cannot interrupt anything, so an Enter pressed without reading is the safe answer.
OPTIONS = (
    SendOption(SendKind.FOLLOW_UP, "f", "Follow up", "send it after this request finishes"),
    SendOption(SendKind.STEER, "s", "Steer", "hand it to the agent now; it replaces the rest of the current task"),
)

#: Rows the panel takes: a blank, the question, a blank, the message, a blank, the two
#: options, a blank, and the keys line.
SEND_KIND_ROWS = 9


class SendKindPage(Widget):
    """Ask which kind of message a draft typed during a request is.

    Shape::

        You sent a message while ZettCode is working. What should it do?

        \u203a stop editing and explain the diff             <- the draft, one line

        \u25b8 1. Follow up   send it after this request finishes (f)
          2. Steer        hand it to the agent now; it replaces the rest of the current task (s)

        enter choose \u00b7 esc keep editing the draft

    The draft is still in the composer while this is up: Escape closes the panel and
    leaves it there, which is what makes asking safe — a reader who pressed Enter too early
    has lost nothing. The two kinds are named with what each does to the running task,
    because "steer" is a word the program uses and the reader may never have met.

    Args:
        message: The draft, shown so the question is about something visible.
        on_choice: Receives the picked :class:`SendKind`.
        on_cancel: Called when the reader backs out.
    """

    QUESTION = "You sent a message while ZettCode is working. What should it do?"
    HINT = f"enter choose {SEPARATOR} f follow up {SEPARATOR} s steer {SEPARATOR} esc keep editing the draft"

    def __init__(
        self,
        message: str,
        *,
        on_choice: Callable[[SendKind], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with the first row highlighted."""
        super().__init__()
        self.message = message
        self.on_choice = on_choice
        self.on_cancel = on_cancel
        self.options = OPTIONS
        self.selected = 0

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def choice(self) -> SendKind:
        """Return the kind the highlighted row would commit."""
        return self.options[self.selected].kind

    def move(self, amount: int) -> None:
        """Move the highlight, wrapping around the ends."""
        self.selected = (self.selected + amount) % len(self.options)

    def activate(self) -> None:
        """Hand the highlighted row to the shell."""
        self.on_choice(self.choice)

    def capture_event(self, event, host: Host) -> bool:
        """Take Escape and a row's own key before anything else sees them."""
        key = pressed(event)
        if key == "escape":
            self.on_cancel()
            return True
        option = next((item for item in self.options if item.key == key), None)
        if option is None:
            return False
        self.on_choice(option.kind)
        return True

    def handle(self, event, host: Host) -> bool:
        """Move with the arrows, and commit with Enter, a row number, or a click."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        key = pressed(event)
        match key:
            case "up":
                self.move(-1)
            case "down":
                self.move(1)
            case "enter":
                self.activate()
            case digit if (
                digit is not None and digit.isascii() and digit.isdigit() and 1 <= int(digit) <= len(self.options)
            ):
                self.selected = int(digit) - 1
                self.activate()
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Commit a clicked row, the way Enter commits the highlighted one."""
        if event.action is not MouseAction.DOWN or not self.rect.contains(event.x, event.y):
            return False
        index = event.y - (self.rect.y + 5)
        if not 0 <= index < len(self.options):
            return False
        self.selected = index
        self.activate()
        return True

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the question, the draft, the options, and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface_alt))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        canvas.draw_text(
            x, self.rect.y + 1, truncate(self.QUESTION, room), Style(foreground=theme.text, bold=True), max_width=room
        )
        draft = f"{PROMPT} {one_line(self.message)}"
        canvas.draw_text(x, self.rect.y + 3, truncate(draft, room), Style(foreground=theme.accent), max_width=room)
        for index, option in enumerate(self.options):
            self._render_option(canvas, self.rect.y + 5 + index, index, option)
        hint_y = self.rect.y + 5 + len(self.options) + 1
        if hint_y < self.rect.bottom:
            canvas.draw_text(x, hint_y, truncate(self.HINT, room), Style(foreground=theme.muted), max_width=room)

    def _render_option(self, canvas: Canvas, y: int, index: int, option: SendOption) -> None:
        """Draw one numbered row, banding the highlighted one."""
        theme = self.theme
        selected = index == self.selected
        if selected:
            style = Style(foreground=theme.text, background=theme.selection, bold=True)
            canvas.fill(self.rect.x + 1, y, max(0, self.rect.width - 2), 1, style)
        else:
            style = Style(foreground=theme.text)
        marker = f"{MARKER} " if selected else "  "
        text = f"{index + 1}. {option.label:<10}{option.detail} ({option.key})"
        canvas.draw_text(self.rect.x + 2, y, marker + text, style, max_width=max(0, self.rect.width - 4))
