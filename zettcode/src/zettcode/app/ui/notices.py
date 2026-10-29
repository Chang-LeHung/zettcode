"""The shell's notices: approvals, toasts, and the usage mirror.

These are the small things shown beside the conversation — a suspended shell
command waiting for a decision, a one-line confirmation, the token counters the
status line reads. They live together because they write to the same places: a
screen, the status line, and the transcript.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from zettcode.sdk.types import Usage
from zettcode.tui import Anchor, Overlay, OverlaySlot, Screen, Toast

from ..commands import CommandUi
from .shell import APPROVAL_ROWS, ASK_SCREEN, PAGE_SCREEN, ShellState
from .widgets import ApprovalChoice, ApprovalPage, AskUserPage, bottom_panel

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.sdk.events import ApprovalRequested, QuestionAsked


class NoticesMixin(CommandUi, ShellState):
    """Show approvals, toasts, and the usage counters."""

    def _usage_updated(self, snapshot: Usage, session_id: str) -> None:
        """Mirror the usage extension's cumulative counters into the status line.

        Only this session's: a subagent works in a session of its own, and its
        totals describe a conversation this shell never sent. Painting them here
        would show another context's size as this one's.
        """
        if session_id != self.client.session.id:
            return
        if snapshot.context_tokens >= self.client.model.context_window:
            # A request cannot carry more than the window it is measured against,
            # so a figure that does is not this request's size: it belongs to
            # another call or to a provider counting to a rule of its own, and
            # painting it would pin the share at a hundred while the context has
            # room to spare. The counters still move — they are cumulative and
            # honest — but the size waits for a measurement to replace it, which
            # is what the reader's next answer brings. The previous reading stands
            # in the meantime rather than a number that cannot be true.
            snapshot = replace(snapshot, context_tokens=self._usage.context_tokens)
            self._remeasure_context_later()
        self._usage = snapshot
        self.app.invalidate()

    def _approval_requested(self, event: ApprovalRequested) -> None:
        """Show the approval panel for one pending shell command.

        The panel is an :class:`ApprovalPage` in a bottom strip: the question,
        the command with its shell highlighting, and the numbered choices, so
        the transcript above stays readable while the command is reviewed.
        """
        page = ApprovalPage(
            event.command,
            on_choice=lambda choice: self._respond(event, choice),
            remember_supported=event.remember_supported,
            permission=self.client.permission,
            work_dir=event.work_dir,
        )
        panel = bottom_panel(page, rows=APPROVAL_ROWS)
        self.app.push_screen(Screen(panel, name=PAGE_SCREEN, modal=True))

    def _respond(self, event: ApprovalRequested, choice: ApprovalChoice) -> None:
        """Dismiss the panel and answer the suspended agent run.

        Args:
            event: The request the decision answers.
            choice: What the user picked; ``safe`` and ``auto`` also move the
                permission level up a rung, which is the same change ``/permission``
                makes — including that the session remembers it.
        """
        self.close_page()
        try:
            if choice is ApprovalChoice.ABORT:
                event.deny()
            else:
                event.approve(remember=choice is ApprovalChoice.ALWAYS)
        except Exception as error:
            self.transcript.error(f"approval failed: {error}")
        else:
            if choice is ApprovalChoice.RUN_SAFE:
                self.change_permission("safe")
            elif choice is ApprovalChoice.RUN_AUTO:
                self.change_permission("full")
        self.app.invalidate()

    # -- questions from the model -------------------------------------------
    def _ask_requested(self, question: QuestionAsked) -> None:
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

    def _answer_ask(self, question: QuestionAsked, answer: str) -> None:
        """Send the reader's answer to the suspended tool call, then ask the next."""
        self._forget_ask(question)
        self.close_page()
        try:
            question.answer(answer)
        except Exception as error:
            self.transcript.error(f"answer failed: {error}")
        self._next_ask()

    def _cancel_ask(self, question: QuestionAsked) -> None:
        """Decline the question, closing the panel that asked it."""
        self._forget_ask(question)
        self.close_page()
        try:
            question.decline()
        except Exception as error:
            self.transcript.error(f"cancel failed: {error}")
        else:
            self.transcript.notice("question declined; the model was told")
        self._next_ask()

    def _forget_ask(self, question: QuestionAsked) -> None:
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
