"""The ``ask_user`` protocol: what the model asked, and what answers it.

``zett-agent`` owns the tool, the suspension and the routing; this module owns
the little the shell and the agent have to agree on — the question parsed out of
the event payload, and the payloads that answer it. Keeping both here means the
panel never reads a raw payload and the agent never invents one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zett_agent.events import AgentEvent
from zett_agent.extensions.ask_user import ASK_USER_EVENT_NAME, ASK_USER_RESPONSE_EVENT_NAME

__all__ = [
    "ASK_USER_RESPONSE_EVENT_NAME",
    "AskUserQuestion",
    "answer_payload",
    "decline_payload",
    "question_from",
]


@dataclass(frozen=True, slots=True)
class AskUserQuestion:
    """One question the model is waiting on.

    Attributes:
        session_id: Session the question belongs to, echoed back with the answer.
        call_id: Tool call the answer resolves; the agent routes on it.
        question: The question, trimmed.
        options: Choices the model offered, in display order; empty when it
            offered none.
        allow_multiple: Whether more than one option may be chosen.
    """

    session_id: str
    call_id: str
    question: str
    options: tuple[str, ...] = ()
    allow_multiple: bool = False


def _options(value: object) -> tuple[str, ...]:
    """Return the usable choices in a payload field, dropping anything else."""
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def question_from(event: AgentEvent) -> AskUserQuestion | None:
    """Return the question an event carries, or ``None`` when it is not one.

    The payload comes from the runtime, but a malformed one must not take the
    shell down: it is read defensively and reported as "not a question".
    """
    if event.name != ASK_USER_EVENT_NAME:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    question = payload.get("question")
    call_id = payload.get("tool_call_id")
    if not isinstance(question, str) or not question.strip():
        return None
    if not isinstance(call_id, str) or not call_id:
        return None
    session_id = payload.get("session_id") or event.session_id
    return AskUserQuestion(
        session_id=str(session_id or ""),
        call_id=call_id,
        question=question.strip(),
        options=_options(payload.get("options")),
        allow_multiple=bool(payload.get("allow_multiple")),
    )


def answer_payload(question: AskUserQuestion, answer: str) -> dict[str, Any]:
    """Return the response payload for a question the reader answered."""
    return {"tool_call_id": question.call_id, "answer": answer}


def decline_payload(question: AskUserQuestion) -> dict[str, Any]:
    """Return the response payload for a question the reader cancelled.

    ``ask_user`` has no rejection channel: the tool returns whatever payload the
    UI sends. A cancel therefore answers with a result that says the question was
    declined — the model reads that and carries on, instead of a suspended call
    waiting for a reply that is never coming.
    """
    return {
        "tool_call_id": question.call_id,
        "answer": None,
        "declined": True,
        "reason": "the user cancelled the question",
    }
