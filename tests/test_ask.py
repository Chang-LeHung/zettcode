"""The ask_user protocol: what the shell reads, and what it answers."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.ask_user import ASK_USER_EVENT_NAME

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.ask import AskUserQuestion, answer_payload, decline_payload, question_from
from zettcode.config import ModelConfig, ZettCodeConfig


def _event(payload: object, *, name: str = ASK_USER_EVENT_NAME) -> AgentEvent:
    return AgentEvent(AgentEventType.CUSTOM, "session-1", name=name, payload=payload)


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": "session-1",
        "tool_call_id": "call-7",
        "question": "Which format?",
        "options": ["Markdown", "Plain text"],
        "allow_multiple": False,
    }
    payload.update(changes)
    return payload


def test_a_question_is_read_out_of_the_event():
    question = question_from(_event(_payload()))

    assert question == AskUserQuestion(
        session_id="session-1",
        call_id="call-7",
        question="Which format?",
        options=("Markdown", "Plain text"),
        allow_multiple=False,
    )


def test_the_reader_keeps_only_what_it_can_use():
    """A question with junk around it is still a question."""
    question = question_from(_event(_payload(options=["Markdown", 7, "  ", "Plain text"], allow_multiple=True)))

    assert question is not None
    assert question.options == ("Markdown", "Plain text")
    assert question.allow_multiple is True

    # No options at all is the ordinary case: the model asked for free text.
    plain = question_from(_event(_payload(options=[])))
    assert plain is not None
    assert plain.options == ()


def test_the_shape_comes_from_the_runtime_and_is_read_as_it_is():
    """The payload keys are the runtime's; this fails when they are renamed."""
    from zett_agent.extensions.ask_user import AskUserEvent, AskUserRequest
    from zett_agent.messages import ToolCall

    call = ToolCall(id="call-3", name="ask_user", arguments={"question": "Which format?"})
    event = AskUserEvent(
        "session-9",
        call,
        AskUserRequest(question="Which format?", options=["Markdown", "Plain text"], allow_multiple=True),
    )

    assert question_from(event) == AskUserQuestion(
        session_id="session-9",
        call_id="call-3",
        question="Which format?",
        options=("Markdown", "Plain text"),
        allow_multiple=True,
    )


@pytest.mark.parametrize(
    "event",
    [
        _event({"tool_call_id": "call-7", "question": "Which format?"}, name="something_else"),
        _event("not-a-mapping"),
        _event(_payload(question="")),
        _event(_payload(question=7)),
        _event(_payload(tool_call_id="")),
        _event(_payload(tool_call_id=None)),
    ],
)
def test_anything_that_is_not_a_question_is_reported_as_none(event):
    assert question_from(event) is None


def test_the_answer_is_what_the_reader_typed():
    question = AskUserQuestion(session_id="s", call_id="call-7", question="Which format?")

    assert answer_payload(question, "Markdown, thanks") == {"tool_call_id": "call-7", "answer": "Markdown, thanks"}


def test_declining_says_so_because_the_tool_has_no_rejection_channel():
    question = AskUserQuestion(session_id="s", call_id="call-7", question="Which format?")

    payload = decline_payload(question)

    assert payload["tool_call_id"] == "call-7"
    assert payload["declined"] is True
    assert payload["answer"] is None
    assert "cancel" in str(payload["reason"])


def _config(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    return ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        **changes,
    )


def test_the_ask_tool_is_composed_by_default_and_can_be_turned_off(tmp_path):
    from zett_agent.extensions.ask_user import AskUserExtension

    composed = runtime_module.integration_extensions(_config(tmp_path))
    disabled = runtime_module.integration_extensions(_config(tmp_path, ask_user_enabled=False))

    assert any(isinstance(extension, AskUserExtension) for extension in composed)
    assert not any(isinstance(extension, AskUserExtension) for extension in disabled)
