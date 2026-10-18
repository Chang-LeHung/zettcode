"""Answering what the model asked for: a shell approval, or a question for the reader.

The agent is suspended inside a tool call while it waits, so the answer is an external
event routed to the session and the call the request came from.
"""

from __future__ import annotations

from zett_agent.agent import AgentRunConfig
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_RESPONSE_EVENT_NAME

from ..dialogue.ask import ASK_USER_RESPONSE_EVENT_NAME, AskUserQuestion, answer_payload, decline_payload
from .base import AgentBase


class InteractionMixin(AgentBase):
    """Send the reader's answer to an approval request or a question back to the running agent."""

    def respond_approval(self, session_id: str, call_id: str, decision: str, remember: bool) -> None:
        """Answer a pending shell approval for the originating session."""
        self.runtime.started.agent.emit_external_event(
            ExternalEvent(
                name=SHELL_APPROVAL_RESPONSE_EVENT_NAME,
                payload={"tool_call_id": call_id, "decision": decision, "remember": remember},
            ),
            config=AgentRunConfig(session_id=session_id),
        )

    def answer_ask(self, question: AskUserQuestion, answer: str) -> None:
        """Answer the model's question; the suspended tool call resumes with it.

        Args:
            question: The question being answered, which carries the session and
                the tool call the runtime routes the reply on.
            answer: What the reader typed, exactly as it should reach the model.
        """
        self._respond_to_ask(question, answer_payload(question, answer))

    def decline_ask(self, question: AskUserQuestion) -> None:
        """Tell the model the reader cancelled, rather than leaving it waiting.

        ``ask_user`` has no rejection channel in the runtime, so the tool result
        says the question was declined and why; the model carries on from that.
        """
        self._respond_to_ask(question, decline_payload(question))

    def _respond_to_ask(self, question: AskUserQuestion, payload: dict[str, object]) -> None:
        """Emit one ``ask_user_response`` for the session the question came from."""
        self.runtime.started.agent.emit_external_event(
            ExternalEvent(name=ASK_USER_RESPONSE_EVENT_NAME, payload=dict(payload)),
            config=AgentRunConfig(session_id=question.session_id),
        )
