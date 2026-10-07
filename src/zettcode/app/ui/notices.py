"""The shell's notices: approvals, toasts, and the usage mirror.

These are the small things shown beside the conversation — a suspended shell
command waiting for a decision, a one-line confirmation, the token counters the
status line reads. They live together because they write to the same places: a
screen, the status line, and the transcript.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...tui import Anchor, Overlay, OverlaySlot, Screen, Toast
from ..agent.usage import UsageSnapshot
from ..commands import CommandUi
from .shell import APPROVAL_ROWS, ASK_SCREEN, PAGE_SCREEN, ShellState
from .widgets import ApprovalChoice, ApprovalPage, AskUserPage, bottom_panel

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.events import AgentEvent

    from ..agent.ask import AskUserQuestion


class NoticesMixin(CommandUi, ShellState):
    """Show approvals, toasts, and the usage counters."""

    def _usage_updated(self, event: AgentEvent) -> None:
        """Mirror the usage extension's cumulative counters into the status line."""
        self._usage = UsageSnapshot.from_payload(event.payload or {})
        self.app.invalidate()

    def _approval_requested(self, event: AgentEvent) -> None:
        """Show the approval panel for one pending shell command.

        The panel is an :class:`ApprovalPage` in a bottom strip: the question,
        the command with its shell highlighting, and the numbered choices, so
        the transcript above stays readable while the command is reviewed.
        """
        payload = event.payload if isinstance(event.payload, dict) else {}
        call_id = str(payload.get("tool_call_id", ""))
        session_id = str(payload.get("session_id") or self.agent.session_id)
        command = str(payload.get("command", ""))
        page = ApprovalPage(
            command,
            on_choice=lambda choice: self._respond(session_id, call_id, choice),
            remember_supported=bool(payload.get("remember_supported")),
        )
        panel = bottom_panel(page, rows=APPROVAL_ROWS)
        self.app.push_screen(Screen(panel, name=PAGE_SCREEN, modal=True))

    def _respond(self, session_id: str, call_id: str, choice: ApprovalChoice) -> None:
        """Dismiss the panel and answer the suspended agent run.

        Args:
            session_id: Session the approval belongs to, echoed back to the agent.
            call_id: Tool call the decision applies to.
            choice: What the user picked; ``auto`` also silences every later
                request this run.
        """
        decision = "abort" if choice is ApprovalChoice.ABORT else "execute"
        remember = choice is ApprovalChoice.ALWAYS
        self.close_page()
        try:
            self.agent.respond_approval(session_id, call_id, decision, remember)
        except Exception as error:
            self.transcript.error(f"approval failed: {error}")
        else:
            if choice is ApprovalChoice.RUN_AUTO:
                self.agent.approve_all_shell_commands()
                self._auto_shell = True
                self.transcript.notice("auto mode on: approving every shell command this run")
        self.app.invalidate()

    # -- questions from the model -------------------------------------------
    def _ask_requested(self, question: AskUserQuestion) -> None:
        """Show the panel for one question the model is waiting on.

        The run is suspended until the panel answers, so this is a modal layer
        like the approval prompt: the question, its options, and the answer line
        stay on screen while the conversation above them is read. One response
        may carry several questions; they queue behind the one on screen and are
        asked in turn, because each suspends the same run.
        """
        if not self._asks:
            self._ask_total = 0
        self._asks.append(question)
        self._ask_total += 1
        if len(self._asks) == 1:
            self._show_ask()
        else:
            self.transcript.notice(f"the model asked another question; {len(self._asks) - 1} waiting behind this one")

    def _show_ask(self) -> None:
        """Put the question at the head of the queue on screen."""
        question = self._asks[0]
        page = AskUserPage(
            question,
            on_answer=lambda answer: self._answer_ask(question, answer),
            on_cancel=lambda: self._cancel_ask(question),
            position=lambda: (self._ask_total - len(self._asks) + 1, self._ask_total),
        )
        panel = bottom_panel(page, rows=min(page.preferred_height(self.app.width), max(5, self.app.height - 6)))
        self.app.push_screen(Screen(panel, name=ASK_SCREEN, modal=True))
        self.app.invalidate()

    def _answer_ask(self, question: AskUserQuestion, answer: str) -> None:
        """Send the reader's answer to the suspended tool call, then ask the next."""
        self._forget_ask(question)
        self.close_page()
        try:
            self.agent.answer_ask(question, answer)
        except Exception as error:
            self.transcript.error(f"answer failed: {error}")
        self._next_ask()

    def _cancel_ask(self, question: AskUserQuestion) -> None:
        """Decline the question, closing the panel that asked it."""
        self._forget_ask(question)
        self.close_page()
        try:
            self.agent.decline_ask(question)
        except Exception as error:
            self.transcript.error(f"cancel failed: {error}")
        else:
            self.transcript.notice("question declined; the model was told")
        self._next_ask()

    def _forget_ask(self, question: AskUserQuestion) -> None:
        """Drop one question from the pending list, if it is still in it."""
        if question in self._asks:
            self._asks.remove(question)

    def _next_ask(self) -> None:
        """Show the question that was waiting behind the one just answered."""
        if self._asks:
            self._show_ask()
        else:
            self._ask_total = 0

    def _drop_ask(self) -> None:
        """Close the question panels a finished run left behind, with no answer.

        Nothing is emitted: the request that asked is already over, and the
        runtime has dropped its pending route, so an answer would go nowhere.
        """
        self._asks.clear()
        self._ask_total = 0
        while self.app.screens.top.name == ASK_SCREEN:
            self.app.pop_screen()

    def notify(self, message: str, *, level: str = "info") -> None:
        """Show a toast, replacing any toast that is still on screen.

        Args:
            message: Text shown in the toast.
            level: Colour key understood by ``Toast``.
        """
        while len(self.app.screens) > 1 and self.app.screens.top.name == "toast":
            self.app.pop_screen()
        toast = Toast(message, level=level, duration=2)
        overlay = Overlay([OverlaySlot(toast, Anchor(horizontal="end", vertical="end", offset_x=-1, offset_y=-1))])
        # A paint-only layer: the toast shows over the shell but must not take
        # input, or scrolling the transcript under it would stop working.
        self.app.push_screen(Screen(overlay, name="toast", interactive=False))

    def markdown(self, text: str) -> None:
        """Append Markdown to the transcript, parsed like an answer."""
        self.transcript.markdown(text)

    def notice(self, text: str) -> None:
        """Append a muted one-line remark."""
        self.transcript.notice(text)

    def error(self, text: str) -> None:
        """Append a one-line failure, painted as an error."""
        self.transcript.error(text)
