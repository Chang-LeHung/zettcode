"""A stored session replays into the same rows the live event flow builds."""

from __future__ import annotations

from pathlib import Path

from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

from zettcode.app.agent.projection import TranscriptProjector
from zettcode.app.agent.replay import replay
from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.transcript import Transcript


def _rows(transcript: Transcript) -> list[tuple[str, str]]:
    """Return each entry as ``(kind, text)``, the part a reader recognises."""
    return [(entry.kind, getattr(entry, "text", "")) for entry in transcript.entries]


async def test_replay_builds_the_rows_the_live_events_built(tmp_path: Path):
    """The two paths must agree, or a resumed session looks different from the run."""
    live = Transcript()
    projector = TranscriptProjector(live)
    projector.begin_turn("find the bug")
    await projector.dispatch(
        AgentEvent(
            AgentEventType.TOOL_STARTED,
            "s",
            tool_calls=(ToolCall("call-1", "read_file", {"path": "app.py"}),),
        )
    )
    await projector.dispatch(
        AgentEvent(
            AgentEventType.TOOL_COMPLETED,
            "s",
            message=ToolMessage(tool_call_id="call-1", name="read_file", content="one\ntwo"),
        )
    )
    await projector.dispatch(AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="Fixed it."))

    store = SessionStore(tmp_path)
    await store.append("s", "req", UserMessage(content="find the bug"))
    await store.append(
        "s",
        "req",
        AssistantMessage(tool_calls=(ToolCall("call-1", "read_file", {"path": "app.py"}),)),
    )
    await store.append("s", "req", ToolMessage(tool_call_id="call-1", name="read_file", content="one\ntwo"))
    await store.append("s", "req", AssistantMessage(content="Fixed it."))

    replayed = replay(store.read("s"))

    assert _rows(replayed.transcript) == _rows(live)
