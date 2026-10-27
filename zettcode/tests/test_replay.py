"""A stored session replays into the same rows the live event flow builds."""

from __future__ import annotations

from pathlib import Path

from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

from zettcode.app.agent.conversation.projection import TranscriptProjector
from zettcode.app.agent.conversation.replay import replay
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.engine.storage import SessionStore


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


async def test_a_replayed_read_row_keeps_the_count_it_was_given(tmp_path: Path):
    """The count comes from the stored result, through the same hook the live path runs."""
    store = SessionStore(tmp_path)
    await store.append("s", "req", UserMessage(content="read the parser"))
    await store.append(
        "s",
        "req",
        AssistantMessage(tool_calls=(ToolCall("call-1", "read", {"path": "app.py"}),)),
    )
    await store.append(
        "s",
        "req",
        ToolMessage(tool_call_id="call-1", name="read", content="one\ntwo\nthree"),
    )

    replayed = replay(store.read("s"))

    rows = [entry for entry in replayed.transcript.entries if getattr(entry, "kind", None) == "tool"]
    assert [(entry.title, entry.lines) for entry in rows] == [("Read app.py", 3)]


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
            tool_calls=(ToolCall("call-1", "read_file", {"path": "app.py"}),),
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


# -- replaying only the window the transcript keeps ------------------------------


async def _long_session(tmp_path: Path, turns: int) -> SessionStore:
    """Return a store holding a session of ``turns`` turns, each with a tool round and an answer."""
    from zett_agent.model import ModelUsage

    store = SessionStore(tmp_path)
    for turn in range(turns):
        request = f"req-{turn}"
        await store.append("s", request, UserMessage(content=f"question {turn}"))
        call = ToolCall(f"call-{turn}", "read_file", {"path": f"module_{turn}.py"})
        await store.append(
            "s",
            request,
            AssistantMessage(reasoning=f"thinking about {turn}", tool_calls=(call,)),
            usage=ModelUsage(input_tokens=100 + turn, output_tokens=10),
        )
        await store.append("s", request, ToolMessage(tool_call_id=call.id, name="read_file", content=f"body {turn}"))
        await store.append(
            "s",
            request,
            AssistantMessage(content=f"answer {turn}"),
            usage=ModelUsage(input_tokens=200, output_tokens=20),
        )
    return store


def _shape(transcript: Transcript) -> list[tuple]:
    """Return what each entry looks like, without the ids that depend on how many came before."""
    from zettcode.app.agent.conversation.presenters import _look_fields

    return [
        (
            str(entry.kind),
            *(
                getattr(entry, name)
                for name in _look_fields(type(entry))
                # The clock readings a restored row is stamped with differ run to run.
                if name not in {"markdown", "started_at", "duration"}
            ),
        )
        for entry in transcript.entries
    ]


async def test_a_long_branch_is_replayed_from_the_window_and_the_window_matches_a_full_replay(tmp_path: Path):
    """The entries a long session shows are the newest ones, and they are the same ones a full walk makes.

    The transcript drops its oldest entries past its cap, so walking the whole branch
    builds rows nobody will see. Starting where the kept entries begin must not change
    what the reader sees: the newest rows are identical to the ones a full replay ends
    with, and the usage the status line shows still counts every reply on the branch.
    """
    store = await _long_session(tmp_path, turns=120)
    session = store.read("s")

    windowed = replay(session, max_entries=40)
    full = replay(SessionStore(tmp_path).read("s"), max_entries=10_000)

    kept = windowed.transcript.entries
    assert len(kept) >= 40, "at least the entries the cap keeps"
    assert len(kept) < len(full.transcript.entries), "and not the whole branch"
    assert _shape(windowed.transcript)[-40:] == _shape(full.transcript)[-40:]
    assert windowed.usage == full.usage, "usage counts the replies before the window as well"
    assert windowed.usage.input_tokens > 0


async def test_the_lines_before_the_window_are_never_decoded(tmp_path: Path):
    """Skipping the old rows only pays if their messages are left as stored."""
    await _long_session(tmp_path, turns=120)
    session = SessionStore(tmp_path).read("s")
    assert not any(line.message.decoded for line in session.messages), "a read decodes nothing"

    replay(session, max_entries=40)

    lines = session.branch()
    decoded = [line.message.decoded for line in lines]
    assert decoded[-1] and decoded[-100], "the window's lines were decoded"
    assert not decoded[0] and not decoded[len(lines) // 4], "the old ones were not"
    assert decoded.count(True) < len(lines) // 2


async def test_a_branch_shorter_than_the_window_is_replayed_whole(tmp_path: Path):
    store = await _long_session(tmp_path, turns=5)

    windowed = replay(store.read("s"), max_entries=1024)
    full = replay(SessionStore(tmp_path).read("s"), max_entries=10_000)

    assert _shape(windowed.transcript) == _shape(full.transcript)
    assert len(windowed.transcript.entries) == 5 * 4


async def test_the_history_a_request_would_carry_is_still_the_whole_branch(tmp_path: Path):
    """The window is about what is shown; the messages the model gets are another matter."""
    store = await _long_session(tmp_path, turns=30)

    windowed = replay(store.read("s"), max_entries=10)
    full = replay(SessionStore(tmp_path).read("s"), max_entries=10_000)

    assert windowed.history == full.history
    assert len(windowed.history) == 30 * 4


async def test_the_window_follows_the_cap_the_transcript_was_given(tmp_path: Path):
    """A cap of five thousand restores more than the default cap of a thousand, not the same."""
    store = await _long_session(tmp_path, turns=400)  # 1600 entries

    small = replay(store.read("s"), max_entries=100)
    large = replay(SessionStore(tmp_path).read("s"), max_entries=3000)

    assert len(small.transcript.entries) < 300
    assert len(large.transcript.entries) == 1600


async def test_a_tool_result_whose_call_is_before_the_window_adds_no_row(tmp_path: Path):
    """The window may start between a call and its result; the orphan is dropped, not drawn."""
    store = await _long_session(tmp_path, turns=60)
    lines = store.read("s").branch()
    # Find a start that lands on a tool result, so its call sits just before the window.
    tool_result = next(
        index for index in range(len(lines) // 2, len(lines)) if isinstance(lines[index].message[0], ToolMessage)
    )

    from zettcode.app.agent.conversation import replay as replay_module

    original = replay_module.window_start
    replay_module.window_start = lambda lines, entries: tool_result
    try:
        replayed = replay(store.read("s"), max_entries=40)
    finally:
        replay_module.window_start = original

    tools = [entry for entry in replayed.transcript.entries if entry.kind == "tool"]
    assert all(entry.text.startswith("body ") for entry in tools), "no tool row is left without its result"
