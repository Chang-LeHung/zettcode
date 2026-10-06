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
from .shell import APPROVAL_ROWS, PAGE_SCREEN, ShellState
from .widgets import ApprovalChoice, ApprovalPage, bottom_panel

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.events import AgentEvent


class NoticesMixin(ShellState):
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

    def _notify(self, message: str, *, level: str = "info") -> None:
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
