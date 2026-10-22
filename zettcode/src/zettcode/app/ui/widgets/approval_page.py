"""The bottom-panel prompt that asks whether to run one shell command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zettcode._compat import StrEnum
from zettcode.tui import MARKER, SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import ELLIPSIS, SHELL, Span, Style, highlight, wrap_spans

from .panel import pressed


class ApprovalChoice(StrEnum):
    """What the user wants done with one pending shell command.

    The rows are the same ladder ``/permission`` offers, seen from one command: a
    choice either leaves the level alone (``RUN``, ``ALWAYS``, ``ABORT``) or moves
    it up a rung for the rest of the run (``RUN_SAFE`` to ``safe``, ``RUN_AUTO`` to
    ``full``). Neither ``deny`` nor ``full`` ever shows the prompt, so there is no
    row that goes down.

    Attributes:
        RUN: Execute this command once; the next one asks again.
        RUN_SAFE: Execute it and stop asking: later commands run in the sandbox.
        RUN_AUTO: Execute it and stop asking for any later command this run, with full access.
        ALWAYS: Execute it and remember this exact command for the session.
        ABORT: Do not execute it; the agent sees a normal tool failure.
    """

    RUN = "run"
    RUN_SAFE = "run_safe"
    RUN_AUTO = "run_auto"
    ALWAYS = "always"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class ApprovalOption:
    """One numbered line of the prompt.

    Attributes:
        choice: Decision handed to the page's ``on_choice`` callback.
        key: Key that triggers this row without moving the selection first.
        label: Sentence drawn after the number and before the key hint.
    """

    choice: ApprovalChoice
    key: str
    label: str


#: How a key name is spelled in a hint; Escape is the one that shortens.
_KEY_HINTS = {"escape": "esc"}


class ApprovalPage(Widget):
    """Review one shell command before it runs.

    Shape::

        Would you like to run the following command?

        Environment: local

        $ rm -rf build && make dist   <- the command, shell-highlighted

        \u25b8 1. Yes, proceed (y)          <- selected row is banded
          2. Yes, and don't ask again for this command (p)
          3. Yes, and stop asking; run commands sandboxed (s)
          4. Yes, and stop asking; full access, no sandbox (a)
          5. No, and say what to do differently (esc)

    The ``s`` row is offered only while the level is ``ask``: at ``safe`` it would
    change nothing, and a row that does nothing is a row that teaches the wrong
    thing about the ladder.

    The panel answers the question the agent is blocked on, so it names every
    option and its key instead of relying on the list conventions alone; the
    arrows and Enter still work, and the digits pick a row outright. Escape
    takes the ``Abort`` row.

    It owns no fill colour: the page clears its rectangle and paints text
    straight onto the terminal's own background, with the surrounding border as
    the only frame. Only the highlighted option bands a row, so the prompt
    never reads as a second surface stacked on the conversation.

    It paints into whatever rectangle it is given; the shell puts it in a
    bottom panel so the conversation stays visible above the command.

    Args:
        command: Shell command under review, shown verbatim and highlighted.
        on_choice: Receives the picked :class:`ApprovalChoice`.
        environment: Where the command will run; ZettCode has no sandbox, so
            the default is ``"local"``.
        remember_supported: Whether to offer ``Always allow``; the runtime can
            only honour it when it has approval storage.
        permission: The shell permission level in force, shown beside the
            environment so the prompt says which rung it is on, and used to leave
            out the rung it is already standing on.
    """

    QUESTION = "Would you like to run the following command?"
    #: Rows spent on everything but the command and the options: a leading
    #: blank, the question, the blank, the environment line, the blank after
    #: the command, the blank before the options, and one spare bottom row.
    FIXED_ROWS = 7

    def __init__(
        self,
        command: str,
        *,
        on_choice: Callable[[ApprovalChoice], None],
        environment: str = "local",
        remember_supported: bool = True,
        permission: str = "ask",
    ) -> None:
        """Build the numbered options and start the highlight on the first."""
        super().__init__()
        self.command = command
        self.on_choice = on_choice
        self.environment = environment
        self.permission = permission
        self.options = self._options(remember_supported, permission)
        self.selected = 0

    @staticmethod
    def _options(remember_supported: bool, permission: str = "ask") -> tuple[ApprovalOption, ...]:
        """Return the rows to show, dropping the ones that would do nothing.

        A row the runtime cannot honour (``Always`` without storage) or that would
        move the level to where it already is (``safe`` at ``safe``) is left out.
        """
        options = [ApprovalOption(ApprovalChoice.RUN, "y", "Yes, proceed")]
        if remember_supported:
            options.append(ApprovalOption(ApprovalChoice.ALWAYS, "p", "Yes, and don't ask again for this command"))
        if permission == "ask":
            options.append(ApprovalOption(ApprovalChoice.RUN_SAFE, "s", "Yes, and stop asking; run commands sandboxed"))
        options.append(ApprovalOption(ApprovalChoice.RUN_AUTO, "a", "Yes, and stop asking; full access, no sandbox"))
        options.append(ApprovalOption(ApprovalChoice.ABORT, "escape", "No, and say what to do differently"))
        return tuple(options)

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def choice(self) -> ApprovalChoice:
        """Return the decision the highlighted row would commit."""
        return self.options[self.selected].choice

    def move(self, amount: int) -> None:
        """Move the highlight, wrapping around the ends."""
        self.selected = (self.selected + amount) % len(self.options)

    def activate(self) -> None:
        """Hand the highlighted row to the shell."""
        self.on_choice(self.choice)

    def capture_event(self, event, host: Host) -> bool:
        """Commit a keyed row, or abort on Escape, before anything else sees it."""
        key = pressed(event)
        if key is None:
            return False
        if key == "escape":
            self.on_choice(ApprovalChoice.ABORT)
            return True
        option = next((item for item in self.options if item.key == key), None)
        if option is None:
            return False
        self.on_choice(option.choice)
        return True

    def handle(self, event, host: Host) -> bool:
        """Move with the arrows, and commit with Enter, a row number, or a click."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        key = pressed(event)
        if key is None:
            return False
        match key:
            case "up":
                self.move(-1)
            case "down":
                self.move(1)
            case "enter":
                self.activate()
            case digit if digit.isascii() and digit.isdigit() and 1 <= int(digit) <= len(self.options):
                self.selected = int(digit) - 1
                self.activate()
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Commit a clicked option row, the way Enter commits the highlighted one."""
        if event.action is not MouseAction.DOWN or not self.rect.contains(event.x, event.y):
            return False
        top = self.rect.y + 6 + len(self._command_rows(max(0, self.rect.width - 4)))
        index = event.y - top
        if not 0 <= index < len(self.options):
            return False
        self.selected = index
        self.activate()
        return True

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the question, the command, and the options."""
        if self.rect.empty:
            return
        theme = self.theme
        # Fill the panel like every other page: it is a screen of its own over
        # the conversation, so leaving the cells unstyled would let the
        # terminal's background through instead of the palette's.
        canvas.fill(
            self.rect.x,
            self.rect.y,
            self.rect.width,
            self.rect.height,
            Style(background=theme.surface_alt),
        )
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        heading = Style(foreground=theme.text, bold=True)
        hint = Style(foreground=theme.muted)
        canvas.draw_text(x, self.rect.y + 1, self.QUESTION, heading, max_width=room)
        canvas.draw_text(
            x,
            self.rect.y + 3,
            f"Environment: {self.environment} {SEPARATOR} Permission: {self.permission}",
            hint,
            max_width=room,
        )
        rows = self._command_rows(room)
        for offset, spans in enumerate(rows):
            canvas.draw_spans(x, self.rect.y + 5 + offset, spans, max_width=room)
        top = self.rect.y + 6 + len(rows)
        for index, option in enumerate(self.options):
            self._render_option(canvas, top + index, index, option)

    def _command_rows(self, width: int) -> list[tuple[Span, ...]]:
        """Return the highlighted command, wrapped and cut to the rows that fit.

        The first row carries a ``$`` prompt and continuation rows are indented,
        the way a shell transcript reads. A command longer than the panel leaves
        a lone ellipsis row rather than looking complete.
        """
        code = self.theme.code
        prompt = Span("$ ", Style(foreground=self.theme.accent, bold=True))
        indent = Span("  ", Style(foreground=code.text))
        rows: list[tuple[Span, ...]] = []
        for line in self.command.splitlines() or [""]:
            for chunk in wrap_spans(highlight(line, SHELL, code), max(1, width - 2)):
                rows.append((prompt if not rows else indent, *chunk))
        budget = max(0, self.rect.height - len(self.options) - self.FIXED_ROWS)
        if len(rows) <= budget:
            return rows
        return [*rows[: max(0, budget - 1)], (indent, Span(ELLIPSIS, Style(foreground=self.theme.muted)))]

    def _render_option(self, canvas: Canvas, y: int, index: int, option: ApprovalOption) -> None:
        """Draw one numbered row, banding the highlighted one."""
        if y >= self.rect.bottom - 1:
            return
        theme = self.theme
        selected = index == self.selected
        if selected:
            style = Style(foreground=theme.text, background=theme.selection, bold=True)
            canvas.fill(self.rect.x + 1, y, max(0, self.rect.width - 2), 1, style)
        else:
            style = Style(foreground=theme.text)
        marker = f"{MARKER} " if selected else "  "
        hint = f" ({_KEY_HINTS.get(option.key, option.key)})"
        text = f"{index + 1}. {option.label}{hint}"
        canvas.draw_text(self.rect.x + 2, y, marker + text, style, max_width=max(0, self.rect.width - 4))
