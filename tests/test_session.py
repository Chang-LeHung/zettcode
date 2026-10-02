"""The session store: JSONL format, the message tree, and the agent lifecycle."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from zett_agent import (
    AgentExtension,
    AgentRunConfig,
    AgentRunContext,
    AgentState,
    AssistantMessage,
    MessageTiming,
    ModelUsage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.extensions.events import CompactionEvent, MessageAppendedEvent, RunCancelledEvent
from zett_agent.extensions.persistence import BaseSessionPersistenceExtension

from zettcode.app.agent.session import (
    CompactionLine,
    MessageLine,
    SessionLine,
    SessionPersistenceMixin,
    SessionStore,
    now,
)


def _lines(store: SessionStore, session_id: str) -> list[dict]:
    """Return the parsed lines of one session file."""
    path = store.session_path(session_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _of_kind(store: SessionStore, session_id: str, kind: str) -> list[dict]:
    """Return the session's lines of one record kind, in file order."""
    return [line for line in _lines(store, session_id) if line["kind"] == kind]


def _summary(text: str) -> CompactedMessage:
    """Return a checkpoint body with the given summary text."""
    return CompactedMessage(content=text)


def _header(session_id: str) -> SessionLine:
    """Return a session line for a test session."""
    return SessionLine(version=1, session_id=session_id, created_at=now())


def _stored_message(session_id: str, *, id: str, parent: str | None) -> MessageLine:
    """Return a message line with an empty envelope, which the tree logic never reads."""
    return MessageLine(
        id=id,
        parent=parent,
        session_id=session_id,
        request_id="req",
        message=(),
        timing=MessageTiming.instant(),
        created_at=now(),
    )


def _active_messages(store: SessionStore, session_id: str) -> list:
    """Return the model context: the summary followed by the active tail."""
    checkpoint, tail = store.read(session_id).active()
    messages = [checkpoint.message[0]] if checkpoint is not None else []
    messages.extend(line.message[0] for line in tail)
    return messages


def context(
    *,
    session_id: str = "s1",
    request_id: str | None = None,
    parent: str | None = None,
    instructions: bool = True,
) -> AgentRunContext:
    """Return a run context with optional system instructions."""
    state = AgentState()
    state.parent_session_id = parent
    if instructions:
        state._messages.append(SystemMessage(content="current instructions"))
    return AgentRunContext(AgentRunConfig(session_id=session_id, request_id=request_id), state, {})


def appended(message, *, usage: ModelUsage | None = None) -> MessageAppendedEvent:
    """Return one append event for a message."""
    return MessageAppendedEvent(message=message, timing=MessageTiming.instant(), usage=usage)


# -- the file format and the tree -------------------------------------------


def test_the_file_reads_back_a_tree_and_its_writer_bookkeeping(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    store._append_line("s1", _stored_message("s1", id="m1", parent=None))
    store._append_line("s1", _stored_message("s1", id="m2", parent="m1"))
    store._append_line(
        "s1",
        CompactionLine(id="c1", parent="m2", version=1, message=(), created_at=now()),
    )

    session = store.read("s1")

    assert session.header is not None and session.header.session_id == "s1"
    assert [line.id for line in session.messages] == ["m1", "m2"]
    assert [line.id for line in session.compactions] == ["c1"]
    # The head is the newest *message*; a checkpoint annotates it, never replaces it.
    assert session.head_id == "m2"
    assert [line.id for line in session.branch()] == ["m1", "m2"]
    assert session.checkpoint_for() is not None
    assert session.message("m1") is not None and session.message("missing") is None
    assert session.index("m2") == 1
    assert session.updated_at.tzinfo is not None


def test_the_active_context_keeps_only_the_branch_after_the_checkpoint(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    for node_id, parent in (("m1", None), ("m2", "m1"), ("m3", "m2")):
        store._append_line("s1", _stored_message("s1", id=node_id, parent=parent))
    store._append_line("s1", CompactionLine(id="c1", parent="m2", version=1, message=(), created_at=now()))
    # A fork: continue from m1 instead of the head m3, abandoning m2/m3.
    store._append_line("s1", _stored_message("s1", id="f1", parent="m1"))

    session = store.read("s1")
    checkpoint, tail = session.active()

    assert session.head_id == "f1"
    assert [line.id for line in session.branch()] == ["m1", "f1"]
    # The checkpoint covers m2, which is not on the forked branch, so it no longer applies.
    assert checkpoint is None
    assert [line.id for line in tail] == ["m1", "f1"]


def test_the_store_only_lists_folders_it_owns(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line("real", _header("real"))
    (tmp_path / "not-a-session").mkdir()
    (tmp_path / "not-a-session" / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "empty").mkdir()

    assert list(store.session_ids()) == ["real"]


def test_reading_and_writing_leave_other_files_alone(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    sidecar = store.session_dir("s1") / "notes.txt"
    sidecar.write_text("mine", encoding="utf-8")

    store._append_line("s1", _stored_message("s1", id="m1", parent=None))

    assert sidecar.read_text(encoding="utf-8") == "mine"
    (raw,) = _of_kind(store, "s1", "message")
    assert raw["parent"] is None
    assert raw["created_at"] >= datetime(2020, 1, 1, tzinfo=UTC).isoformat()


def test_an_absent_session_reads_as_empty(tmp_path: Path):
    session = SessionStore(tmp_path).read("missing")

    assert session.header is None
    assert session.messages == () and session.compactions == ()
    assert session.head_id is None and session.branch() == ()


def test_a_stored_envelope_decodes_into_a_concrete_runtime_message(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line(
        "s1",
        MessageLine(
            id="m1",
            session_id="s1",
            request_id="req",
            message=({"kind": 2, "data": {"content": "hello"}},),
            timing=MessageTiming.instant(),
            created_at=now(),
        ),
    )

    (line,) = store.read("s1").messages

    assert isinstance(line.message[0], UserMessage)
    assert line.message[0].content == "hello"


def test_an_unknown_message_kind_is_rejected(tmp_path: Path):
    store = SessionStore(tmp_path)

    with pytest.raises(ValidationError):
        store._append_line(
            "s1",
            MessageLine(
                id="m1",
                session_id="s1",
                request_id="req",
                message=({"kind": 99, "data": {}},),
                timing=MessageTiming.instant(),
                created_at=now(),
            ),
        )


def test_a_torn_final_line_is_ignored_and_a_corrupt_middle_line_is_not(tmp_path: Path):
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    store._append_line("s1", _stored_message("s1", id="m1", parent=None))
    path = store.session_path("s1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "message", "id": "half')  # a crash mid-append

    assert [line.id for line in store.read("s1").messages] == ["m1"]

    path.write_text("not json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt session file"):
        store.read("s1")


def test_session_ids_cannot_leave_the_store(tmp_path: Path):
    store = SessionStore(tmp_path)

    for unsafe in ("../escape", "a/b", "", "-leading-dash"):
        with pytest.raises(ValueError, match="Unsafe session id"):
            store.session_path(unsafe)


# -- the store API ----------------------------------------------------------


async def test_each_message_links_to_the_one_before_it(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = await store.append("s1", "req", UserMessage(content="hello"))
    second = await store.append("s1", "req", AssistantMessage(content="hi"))

    assert first != second

    header, first_line, second_line = _lines(store, "s1")
    assert header["kind"] == "session"
    assert first_line["id"] == first and first_line["parent"] is None
    assert second_line["id"] == second and second_line["parent"] == first

    session = store.read("s1")

    assert [line.id for line in session.messages] == [first, second]
    assert [line.parent for line in session.messages] == [None, first]
    assert [type(message).__name__ for message in _active_messages(store, "s1")] == [
        "UserMessage",
        "AssistantMessage",
    ]


async def test_the_context_cuts_at_the_latest_checkpoint(tmp_path: Path):
    store = SessionStore(tmp_path)
    ids = [await store.append("s1", "req", UserMessage(content=f"m{index + 1}")) for index in range(4)]

    checkpoint = await store.checkpoint("s1", _summary("first two"), ids[1], 0)
    stored, tail = store.read("s1").active()

    assert checkpoint.version == 1
    assert stored is not None and stored.parent == ids[1]
    assert [line.id for line in tail] == ids[2:]
    # The model context is the summary followed by the tail, while the raw log
    # keeps every original message.
    assert [message.text for message in _active_messages(store, "s1")] == ["first two", "m3", "m4"]
    assert len(store.read("s1").messages) == 4


async def test_a_prefix_checkpoint_still_yields_the_whole_tail(tmp_path: Path):
    """A summary taken mid-conversation is not on the tail's parent chain."""
    store = SessionStore(tmp_path)
    ids = [await store.append("s1", "req", UserMessage(content=f"m{index + 1}")) for index in range(5)]

    await store.checkpoint("s1", _summary("through m3"), ids[2], 0)

    # The checkpoint hangs off the message it summarized, so the file stays a tree.
    (compaction,) = _of_kind(store, "s1", "compaction")

    assert compaction["parent"] == ids[2]
    assert [message.text for message in _active_messages(store, "s1")] == ["through m3", "m4", "m5"]


async def test_checkpoints_must_advance_and_match_the_expected_version(tmp_path: Path):
    store = SessionStore(tmp_path)
    ids = [await store.append("s1", "req", UserMessage(content=f"m{index + 1}")) for index in range(4)]

    await store.checkpoint("s1", _summary("through 2"), ids[1], 0)

    with pytest.raises(ValueError, match="Checkpoint conflict"):
        await store.checkpoint("s1", _summary("stale"), ids[2], 0)
    with pytest.raises(ValueError, match="advance beyond"):
        await store.checkpoint("s1", _summary("older"), ids[1], 1)
    with pytest.raises(ValueError, match="existing message"):
        await store.checkpoint("s1", _summary("beyond"), "no-such-node", 1)


async def test_a_compaction_continues_from_its_boundary_message(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = await store.append("s1", "req", UserMessage(content="m1"))
    await store.checkpoint("s1", _summary("summary"), first, 0)

    await store.append("s1", "req", UserMessage(content="m2"))

    # A checkpoint is an annotation, not a tree node: the next message still
    # hangs off the head message.
    assert _of_kind(store, "s1", "message")[-1]["parent"] == first
    assert [message.text for message in _active_messages(store, "s1")] == ["summary", "m2"]


async def test_a_fork_leaves_the_abandoned_branch_out_of_context(tmp_path: Path):
    """Forking is a plain append: a child of an older node, not of the head."""
    store = SessionStore(tmp_path)
    root = await store.append("s1", "req", UserMessage(content="question"))
    abandoned = await store.append("s1", "req", AssistantMessage(content="first answer"))
    follow_up = await store.append("s1", "req", UserMessage(content="follow-up"))
    forked = await store.append("s1", "req", AssistantMessage(content="other answer"), parent=root)

    session = store.read("s1")

    # The active context walks root -> forked; the old branch is gone from it.
    assert [line.id for line in session.branch()] == [root, forked]
    assert [message.content for message in _active_messages(store, "s1")] == ["question", "other answer"]
    # ...but the raw log keeps the abandoned nodes for history and inspection.
    assert [line.id for line in session.messages] == [root, abandoned, follow_up, forked]
    # Later appends continue from the fork, not from the abandoned head.
    tip = await store.append("s1", "req", UserMessage(content="after the fork"))
    assert [line.id for line in store.read("s1").branch()] == [root, forked, tip]


async def test_a_fork_ignores_a_checkpoint_on_the_abandoned_branch(tmp_path: Path):
    store = SessionStore(tmp_path)
    root = await store.append("s1", "req", UserMessage(content="m1"))
    second = await store.append("s1", "req", UserMessage(content="m2"))
    await store.checkpoint("s1", _summary("covers m2"), second, 0)

    forked = await store.append("s1", "req", UserMessage(content="forked off m1"), parent=root)
    checkpoint, tail = store.read("s1").active()

    assert checkpoint is None
    assert [line.id for line in tail] == [root, forked]


async def test_an_unknown_parent_is_rejected_at_write_time(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("s1", "req", UserMessage(content="m1"))

    with pytest.raises(ValueError, match="Unknown parent"):
        await store.append("s1", "req", UserMessage(content="m2"), parent="no-such-node")


async def test_metadata_tags_timing_and_usage_round_trip(tmp_path: Path):
    store = SessionStore(tmp_path)
    usage = ModelUsage(input_tokens=10, output_tokens=4, cache_read_tokens=2, cache_write_tokens=0, reasoning_tokens=1)

    await store.append(
        "s1",
        "req-1",
        AssistantMessage(content="hi"),
        metadata={"model": "deepseek-chat"},
        tags={"kind": "answer"},
        usage=usage,
    )

    (line,) = store.read("s1").messages

    assert line.request_id == "req-1"
    assert line.metadata == {"model": "deepseek-chat"}
    assert line.tags == {"kind": "answer"}
    assert (line.usage.input_tokens, line.usage.output_tokens, line.usage.reasoning_tokens) == (10, 4, 1)
    assert line.timing.started_at.tzinfo is not None and line.timing.duration_ns >= 0


async def test_usage_is_rejected_for_user_messages(tmp_path: Path):
    store = SessionStore(tmp_path)

    with pytest.raises(ValueError, match="assistant messages"):
        await store.append("s1", "req", UserMessage(content="hi"), usage=ModelUsage(input_tokens=1, output_tokens=1))


async def test_each_session_owns_a_directory_with_its_data_file(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("s1", "req", UserMessage(content="hi"))

    assert store.session_dir("s1") == tmp_path / "s1"
    assert store.session_path("s1") == tmp_path / "s1" / "data.jsonl"
    assert (tmp_path / "s1" / "data.jsonl").is_file()


async def test_list_sessions_reports_activity_newest_first(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("older", "req", UserMessage(content="a"))
    await store.append("newer", "req", UserMessage(content="b"))
    await store.append("newer", "req", UserMessage(content="c"))

    listed = await store.list_sessions()

    assert [session.session_id for session in listed] == ["newer", "older"]
    assert [session.message_count for session in listed] == [2, 1]
    assert await store.list_sessions(limit=1, offset=1) == [listed[1]]


# -- the agent lifecycle ----------------------------------------------------


def test_storage_is_a_standalone_mixin_and_the_store_is_the_plugin():
    assert issubclass(SessionStore, AgentExtension)
    assert not issubclass(SessionStore, BaseSessionPersistenceExtension)
    # The mixin inherits nothing: it is combined with AgentExtension, not built
    # on top of it, and its storage comes first in the MRO.
    assert not issubclass(SessionPersistenceMixin, AgentExtension)
    assert SessionStore.__mro__[:3] == (SessionStore, SessionPersistenceMixin, AgentExtension)
    # Saving lives in the mixin; the framework hooks live on the plugin.
    assert {"read", "append", "checkpoint", "list_sessions"} <= set(SessionPersistenceMixin.__dict__)
    assert {"on_state", "on_event", "on_success", "on_error"} <= set(SessionStore.__dict__)
    assert not {"on_state", "on_event"} & set(SessionPersistenceMixin.__dict__)


async def test_persisting_a_turn_and_restoring_it(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = context(request_id="req-1")
    await store.on_state(first)
    await store.on_event(first, appended(UserMessage(content="hello")))
    await store.on_event(first, appended(AssistantMessage(content="hi")))
    await store.on_success(first, AssistantMessage(content="done"))

    assert (tmp_path / "s1" / "data.jsonl").is_file()
    assert [session.message_count for session in await store.list_sessions()] == [2]

    second = context(request_id="req-2")
    await store.on_state(second)

    assert [getattr(message, "text", None) or message.content for message in second.state.messages] == [
        "current instructions",
        "hello",
        "hi",
    ]


async def test_restoring_keeps_instructions_and_drops_interrupted_tool_batches(tmp_path: Path):
    store = SessionStore(tmp_path)
    complete = ToolCall(id="call-1", name="read", arguments={})
    incomplete = ToolCall(id="call-2", name="write", arguments={})
    first = context(request_id="req-1")
    await store.on_state(first)
    for message in (
        UserMessage(content="start"),
        AssistantMessage(content="", tool_calls=[complete]),
        ToolMessage(tool_call_id="call-1", name="read", content="ok"),
        AssistantMessage(content="", tool_calls=[incomplete]),
        AssistantMessage(content="done"),
        ToolMessage(tool_call_id="orphan", name="read", content="stray"),
    ):
        await store.on_event(first, appended(message))
    await store.on_success(first, AssistantMessage(content="done"))

    second = context(request_id="req-2", instructions=False)
    await store.on_state(second)

    assert [type(message).__name__ for message in second.state.messages] == [
        "UserMessage",
        "AssistantMessage",
        "ToolMessage",
        "AssistantMessage",
    ]
    assert second.state.messages[-1].content == "done"


async def test_cancelling_drops_the_bookkeeping_so_late_events_are_ignored(tmp_path: Path):
    store = SessionStore(tmp_path)
    ctx = context()
    await store.on_state(ctx)

    await store.on_event(
        ctx,
        RunCancelledEvent(previous_phase=ctx.state.phase, occurred_at=datetime.now(UTC), monotonic_ns=0),
    )
    await store.on_event(ctx, appended(UserMessage(content="too late")))

    assert not (tmp_path / "s1").exists()


async def test_a_compaction_event_maps_the_prefix_onto_the_stored_boundary(tmp_path: Path):
    store = SessionStore(tmp_path)
    ctx = context()
    await store.on_state(ctx)

    for message in (UserMessage(content="a"), AssistantMessage(content="b"), UserMessage(content="c")):
        await store.on_event(ctx, appended(message))

    await store.on_event(
        ctx,
        CompactionEvent(compressed_from=1, compressed_to=2, kept_from=3, kept_to=3, summary="first two"),
    )

    messages = _of_kind(store, "s1", "message")
    (first,) = _of_kind(store, "s1", "compaction")

    assert first["parent"] == messages[1]["id"] and first["version"] == 1

    # The next compaction covers the checkpoint plus one message, so its
    # boundary advances past the first one.
    await store.on_event(
        ctx,
        CompactionEvent(compressed_from=1, compressed_to=2, kept_from=3, kept_to=4, summary="again"),
    )

    second = _of_kind(store, "s1", "compaction")[-1]

    assert second["parent"] == messages[2]["id"] and second["version"] == 2


async def test_a_stale_compaction_range_is_rejected(tmp_path: Path):
    store = SessionStore(tmp_path)
    ctx = context()
    await store.on_state(ctx)
    await store.on_event(ctx, appended(UserMessage(content="only message")))

    with pytest.raises(ValueError, match="Compaction range does not match"):
        await store.on_event(
            ctx,
            CompactionEvent(compressed_from=1, compressed_to=9, kept_from=1, kept_to=1, summary="too far"),
        )
