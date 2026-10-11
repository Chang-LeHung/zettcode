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


async def test_a_replayed_edit_row_keeps_the_counts_it_was_phrased_with(tmp_path: Path):
    """The row is phrased from the call's arguments in both paths.

    A live call and a stored one carry the same arguments, so a resumed session
    must show the same `(1 edit, +1 -3)`. A row that counted the lines only while
    the call was live would be exactly the difference the parity rule exists to
    prevent.
    """
    edits = [{"old_text": "a\nb\nc", "new_text": "one"}]
    store = SessionStore(tmp_path)
    await store.append("s", "req", UserMessage(content="tighten the parser"))
    await store.append(
        "s",
        "req",
        AssistantMessage(tool_calls=(ToolCall("call-1", "replace_in_file", {"path": "app.py", "edits": edits}),)),
    )
    await store.append(
        "s",
        "req",
        ToolMessage(tool_call_id="call-1", name="replace_in_file", content="Replaced 1 occurrence in app.py"),
    )

    replayed = replay(store.read("s"))

    tool_rows = [entry for entry in replayed.transcript.entries if getattr(entry, "kind", None) == "tool"]

    assert [(entry.title, entry.added, entry.removed) for entry in tool_rows] == [("Edited app.py (1 edit)", 1, 3)]


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

    # The live transcript still holds its pinned wait row — a request is open
    # there — while a replayed one has no request in flight, so the turn's own
    # rows are what the two paths must agree on.
    assert _rows(live)[:-1] == _rows(replayed.transcript)
    assert live.entries[-1].kind == "wait"
