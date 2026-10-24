"""A question nobody answered: one row, named Ask-User, in the caution colour rather than a tool's own.

A cancel is not a failure: the model is told the question was declined and carries on. The row has to say the same —
which is why the status is ``skipped`` and the colour is amber, in the live flow and after a session is reopened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

from zettcode.app.agent.conversation.entries import EntryStatus
from zettcode.app.agent.conversation.presenters import render_entry
from zettcode.app.agent.conversation.projection import TranscriptProjector
from zettcode.app.agent.conversation.replay import replay
from zettcode.app.agent.conversation.text import DECLINED_NOTE
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.engine.dialogue.ask import declined_answer
from zettcode.engine.storage import SessionStore
from zettcode.tui import DARK

#: What the tool returns when the reader cancels: the payload the shell sent, serialized.
DECLINED = json.dumps(
    {
        "name": "ask_user_response",
        "payload": {
            "tool_call_id": "call-1",
            "answer": None,
            "declined": True,
            "reason": "the user cancelled the question",
        },
    }
)

#: And what it returns when the reader answers.
ANSWERED = json.dumps({"name": "ask_user_response", "payload": {"tool_call_id": "call-1", "answer": "the second one"}})

CALL = ToolCall("call-1", "ask_user", {"question": "which file?"})


async def _live(result: str) -> Transcript:
    transcript = Transcript()
    projector = TranscriptProjector(transcript)
    projector.begin_turn("change the file")
    await projector.dispatch(AgentEvent(AgentEventType.TOOL_STARTED, "s", tool_calls=[CALL]))
    await projector.dispatch(
        AgentEvent(
            AgentEventType.TOOL_COMPLETED,
            "s",
            tool_calls=[CALL],
            message=ToolMessage(tool_call_id="call-1", name="ask_user", content=result),
        )
    )
    return transcript


async def _stored(tmp_path: Path, result: str) -> Transcript:
    store = SessionStore(tmp_path)
    await store.append("s", "req", UserMessage(content="change the file"))
    await store.append("s", "req", AssistantMessage(tool_calls=(CALL,)))
    await store.append("s", "req", ToolMessage(tool_call_id="call-1", name="ask_user", content=result, success=True))
    return replay(store.read("s")).transcript


def _row(transcript: Transcript):
    (entry,) = [entry for entry in transcript.entries if getattr(entry, "kind", None) == "tool"]
    return entry


def test_the_payload_a_cancel_leaves_behind_is_recognised():
    assert declined_answer(DECLINED)
    assert not declined_answer(ANSWERED)
    assert not declined_answer("not json")
    assert not declined_answer('{"payload": "declined"}')


async def test_a_cancelled_question_is_a_skipped_row_named_ask_user():
    entry = _row(await _live(DECLINED))

    assert entry.title == "Ask-User: which file?"
    assert entry.status is EntryStatus.SKIPPED, "not a failure: the model was told and carried on"
    assert entry.text == DECLINED_NOTE, "and the row says the question was declined, not the protocol's JSON"
    assert 'declined": true' not in entry.text and "tool_call_id" not in entry.text


async def test_an_answered_question_says_the_answer_rather_than_the_payload():
    entry = _row(await _live(ANSWERED))

    assert entry.status is EntryStatus.COMPLETED
    assert entry.text == "You answered: the second one"


async def test_the_note_is_drawn_under_the_title(tmp_path: Path):
    entry = _row(await _live(DECLINED))

    drawn = "\n".join(line.text for line in render_entry(entry, 60, DARK, 0))

    assert "Ask-User: which file?" in drawn and DECLINED_NOTE in drawn


async def test_the_skipped_row_is_amber_and_not_the_tool_colour():
    entry = _row(await _live(DECLINED))

    lines = render_entry(entry, 40, DARK, 0)
    colours = {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.warning in colours
    assert DARK.tools.ask_user not in colours and DARK.error not in colours


async def test_a_cancelled_question_after_reopening_is_the_same_row(tmp_path: Path):
    live = _row(await _live(DECLINED))
    again = _row(await _stored(tmp_path, DECLINED))

    assert (again.title, again.status, again.text) == (live.title, live.status, live.text)
    assert again.status is EntryStatus.SKIPPED and again.text == DECLINED_NOTE


async def test_an_answer_with_a_picture_is_a_short_note():
    with_image = json.dumps(
        {
            "name": "ask_user_response",
            "payload": {"tool_call_id": "call-1", "parts": [{"type": "image", "name": "a.png"}]},
        }
    )

    assert _row(await _live(with_image)).text == "You answered with a picture."


async def test_an_answered_question_after_reopening_is_completed(tmp_path: Path):
    assert _row(await _stored(tmp_path, ANSWERED)).status is EntryStatus.COMPLETED


@pytest.mark.parametrize("result", ["", "{}"])
async def test_a_result_that_is_not_the_protocol_is_left_completed(result: str):
    assert _row(await _live(result)).status is EntryStatus.COMPLETED
