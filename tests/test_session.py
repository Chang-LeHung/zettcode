"""The session store: JSONL format, the message tree, and the agent lifecycle."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.extensions.events import CompactionEvent, MessageAppendedEvent, MessageTiming, RunCancelledEvent
from zett_agent.extensions.persistence import BaseSessionPersistenceExtension
from zett_agent.messages import AssistantMessage, SystemMessage, ToolCall, ToolMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.app.agent.storage import SessionPersistenceMixin, SessionStore, now, workspace_key
from zettcode.app.agent.storage.metadata import (
    MAX_TITLE,
    SessionActivity,
    SessionStarted,
    SessionTitle,
    append_metadata,
    read_metadata,
)
from zettcode.app.agent.storage.records import CompactionLine, MessageLine, SessionLine


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
    assert raw["created_at"] >= datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()


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


async def test_a_message_holding_a_unicode_line_separator_is_read_back_whole(tmp_path: Path):
    """JSON writes U+2028, U+2029, and U+0085 into a string as they are, and a record is one line.

    ``str.splitlines`` breaks at all three, so a message that quoted one — a pasted
    log, a page of prose with a paragraph separator — was cut in half when its session
    was read and the file reported as corrupt. The file's own newline is the only
    thing that ends a record.
    """
    text = "before\u2028middle\u2029after\x85end — and a tab\tand a form feed\x0c"
    writer = SessionStore(tmp_path)
    await writer.append("s1", "r", UserMessage(content=text))
    await writer.append("s1", "r", AssistantMessage(content=text))

    session = SessionStore(tmp_path).read("s1")

    assert [line.message[0].content for line in session.messages] == [text, text]


def test_a_final_line_cut_in_the_middle_of_a_character_is_ignored(tmp_path: Path):
    """A crash can stop an append between the bytes of one character, not only between lines.

    Decoding the whole file first made that a ``UnicodeDecodeError`` for every record
    before it; read as bytes, the torn line is the one the parser rejects, and the
    rule that tolerates a half-written final line covers it.
    """
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    store._append_line("s1", _stored_message("s1", id="m1", parent=None))
    with store.session_path("s1").open("ab") as handle:
        handle.write('{"kind": "message", "id": "中'.encode()[:-1])  # two of the character's three bytes

    assert [line.id for line in SessionStore(tmp_path).read("s1").messages] == ["m1"]


async def test_asking_whether_a_session_exists_reads_one_line(tmp_path: Path, monkeypatch):
    """The header answers the question, so a long session is not parsed to be told it is there.

    A command line that resumes asked this with a fresh store, which cannot have kept
    the parse for the store that opens the session next: the same file was parsed
    twice, and on a long one the first of them cost more than any other stage.
    """
    from zettcode.app.agent.storage import store as store_module

    writer = SessionStore(tmp_path)
    for index in range(200):
        await writer.append("s1", f"r{index}", UserMessage(content=f"message {index}"))
    parsed: list[int] = []
    real = store_module.LINES

    class Counting:
        def validate_json(self, line):
            parsed.append(len(line))
            return real.validate_json(line)

    monkeypatch.setattr(store_module, "LINES", Counting())

    assert SessionStore(tmp_path).exists("s1") is True
    assert len(parsed) == 1, "one line, however long the session"

    assert SessionStore(tmp_path).exists("missing") is False
    assert len(parsed) == 1, "a session that is not there reads nothing"


def test_a_file_that_does_not_open_with_a_header_is_not_a_session(tmp_path: Path):
    store = SessionStore(tmp_path)
    path = store.session_path("s1")
    path.parent.mkdir(parents=True)

    path.write_bytes(b"")
    assert store.exists("s1") is False, "empty"

    path.write_bytes(b"not json at all\n")
    assert store.exists("s1") is False, "garbage"

    path.write_text(_stored_message("s1", id="m1", parent=None).model_dump_json() + "\n", encoding="utf-8")
    assert store.exists("s1") is False, "a message first"

    path.write_text("\n\n" + _header("s1").model_dump_json() + "\n", encoding="utf-8")
    assert store.exists("s1") is True, "blank lines before the header do not hide it"


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


def test_a_session_is_parsed_once_and_then_served_from_the_cache(tmp_path: Path, monkeypatch):
    """Reading twice must not re-parse the log; that is what keeps append O(1)."""
    store = SessionStore(tmp_path)
    store._append_line("s1", _header("s1"))
    store._append_line("s1", _stored_message("s1", id="m1", parent=None))
    path = store.session_path("s1")
    reads: list[Path] = []
    original = Path.read_bytes

    def spy(self: Path, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", spy)

    first = store.read("s1")
    second = store.read("s1")

    assert first is second
    assert reads.count(path) == 1


async def test_an_external_write_is_not_hidden_by_the_parse_cache(tmp_path: Path):
    """The cache is keyed on the file, so another writer's line must show up."""
    store = SessionStore(tmp_path)
    first = await store.append("s1", "req", UserMessage(content="hello"))
    assert [line.id for line in store.read("s1").messages] == [first]

    path = store.session_path("s1")
    extra = _stored_message("s1", id="m-extra", parent=first)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(extra.model_dump_json() + "\n")

    assert [line.id for line in store.read("s1").messages] == [first, "m-extra"]


async def test_per_message_attributes_survive_the_round_trip(tmp_path: Path):
    """The ``@`` original prompt rides on the message and must come back."""
    store = SessionStore(tmp_path)
    await store.append(
        "s1",
        "req",
        UserMessage(content="expanded @skill", attributes={"prompt": "typed @skill"}),
    )

    (line,) = store.read("s1").messages
    stored = line.message[0]

    assert isinstance(stored, UserMessage)
    assert stored.content == "expanded @skill"
    assert stored.attributes == {"prompt": "typed @skill"}


async def test_appending_does_not_reparse_the_whole_file(tmp_path: Path, monkeypatch):
    """A new message folds into the parsed cache instead of re-reading it."""
    store = SessionStore(tmp_path)
    first = await store.append("s1", "req", UserMessage(content="hello"))
    store.read("s1")
    path = store.session_path("s1")
    reads: list[Path] = []
    original = Path.read_bytes

    def spy(self: Path, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", spy)

    second = await store.append("s1", "req", AssistantMessage(content="hi"))
    session = store.read("s1")

    assert [line.id for line in session.messages] == [first, second]
    assert session.head_id == second
    assert path not in reads


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


async def test_each_session_owns_a_directory_under_its_workspace(tmp_path: Path):
    store = SessionStore(tmp_path, workspace="/work/project")
    await store.append("s1", "req", UserMessage(content="hi"))

    # The key is the resolved path's, so the expectation has to resolve too.
    key = workspace_key(store.workspace)
    assert store.workspace_dir == tmp_path / key
    assert store.session_dir("s1") == tmp_path / key / "s1"
    assert store.session_path("s1") == tmp_path / key / "s1" / "data.jsonl"
    assert (tmp_path / key / "s1" / "data.jsonl").is_file()


def test_the_workspace_folder_keeps_each_project_apart(tmp_path: Path):
    first = SessionStore(tmp_path, workspace="/work/one")
    second = SessionStore(tmp_path, workspace="/work/two")

    assert first.workspace_dir != second.workspace_dir
    # The key is the URL-safe base64 of the resolved path, without padding.
    assert first.workspace_dir.name == workspace_key(first.workspace)
    assert "/" not in first.workspace_dir.name


def test_a_very_long_workspace_path_still_names_one_folder(tmp_path: Path):
    store = SessionStore(tmp_path, workspace="/" + "deep/" * 200)

    assert len(store.workspace_dir.name) <= 120
    assert store.workspace_dir.is_dir()


async def test_list_sessions_reports_activity_newest_first(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("older", "req", UserMessage(content="a"))
    await store.append("newer", "req", UserMessage(content="b"))
    await store.append("newer", "req", UserMessage(content="c"))

    listed = await store.list_sessions()

    assert [session.session_id for session in listed] == ["newer", "older"]
    assert store.read("newer").message_count == 2
    assert await store.list_sessions(limit=1, offset=1) == [listed[1]]


async def test_the_metadata_log_records_the_session_lifecycle(tmp_path: Path):
    store = SessionStore(tmp_path, workspace="/work/project")
    await store.append("s1", "req", UserMessage(content="one"))
    await store.append("s1", "req", UserMessage(content="two"))
    await store.set_title("s1", "Fix the parser crash")

    records = [json.loads(line) for line in store.metadata_path.read_text(encoding="utf-8").splitlines()]

    assert [record["kind"] for record in records] == ["session", "activity", "activity", "title"]
    assert records[0]["session_id"] == "s1"
    assert records[-1]["title"] == "Fix the parser crash"


def test_the_metadata_log_folds_to_the_newest_record_of_each_kind(tmp_path: Path):
    path = tmp_path / "metadata.jsonl"
    start = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    append_metadata(path, SessionStarted(session_id="s1", created_at=start))
    append_metadata(path, SessionTitle(session_id="s1", title="First name"))
    append_metadata(path, SessionActivity(session_id="s1", updated_at=start))
    append_metadata(path, SessionTitle(session_id="s1", title="Second name"))
    append_metadata(path, SessionActivity(session_id="s2", updated_at=start))

    (info,) = read_metadata(path)

    assert (info.session_id, info.title) == ("s1", "Second name")
    assert info.created_at == start
    # An activity line for an unknown session cannot invent one.
    assert [row.session_id for row in read_metadata(path)] == ["s1"]


def test_a_torn_final_metadata_line_is_ignored(tmp_path: Path):
    path = tmp_path / "metadata.jsonl"
    start = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    append_metadata(path, SessionStarted(session_id="s1", created_at=start))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "title", "session_id": "s1"')

    (info,) = read_metadata(path)

    assert (info.session_id, info.title) == ("s1", None)


async def test_the_listing_answers_from_the_metadata_log_alone(tmp_path: Path):
    store = SessionStore(tmp_path, workspace="/work/project")
    await store.append("indexed", "req", UserMessage(content="hi"))
    await store.set_title("indexed", "Fix the parser crash")
    # Damage the conversation file: the listing must not need to parse it, so
    # the row still answers with its title and activity times.
    store.session_path("indexed").write_text("torn", encoding="utf-8")

    listed = await store.list_sessions()

    assert [(info.session_id, info.title) for info in listed] == [("indexed", "Fix the parser crash")]
    assert listed[0].created_at <= listed[0].updated_at


async def test_an_index_row_without_a_session_folder_is_hidden(tmp_path: Path):
    store = SessionStore(tmp_path, workspace="/work/project")
    await store.append("gone", "req", UserMessage(content="hi"))
    shutil.rmtree(store.session_dir("gone"))

    assert await store.list_sessions() == []


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

    assert store.session_path("s1").is_file()
    assert store.read("s1").message_count == 2

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


async def test_restoring_skips_persisted_instructions_so_the_prefix_stays_stable(tmp_path: Path):
    """A turn's instructions are rebuilt, never replayed from the log.

    Replaying them duplicated the system prompt and the extension notes at the
    head of every request, which moved the dialogue down and broke the
    provider's prefix cache from the first duplicated message on.
    """
    store = SessionStore(tmp_path)
    first = context(request_id="req-1")
    await store.on_state(first)
    for message in (
        SystemMessage(content="stale system prompt"),
        UserMessage(content="hello"),
        AssistantMessage(content="hi"),
    ):
        await store.on_event(first, appended(message))
    await store.on_success(first, AssistantMessage(content="hi"))

    second = context(request_id="req-2")
    await store.on_state(second)

    assert [getattr(message, "text", None) or message.content for message in second.state.messages] == [
        "current instructions",
        "hello",
        "hi",
    ]


async def test_cancelling_drops_the_bookkeeping_so_late_events_are_ignored(tmp_path: Path):
    store = SessionStore(tmp_path)
    ctx = context()
    await store.on_state(ctx)

    await store.on_event(
        ctx,
        RunCancelledEvent(previous_phase=ctx.state.phase, occurred_at=datetime.now(timezone.utc), monotonic_ns=0),
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


# -- messages that are decoded when someone looks inside ---------------------------


async def test_a_line_read_from_the_file_is_not_decoded_until_it_is_looked_into(tmp_path: Path):
    """Decoding a message into its runtime type is the one step that costs Python time per message.

    A reader that wants the whole branch pays it; one that wants the newest part and the
    usage beside the message must not.
    """
    writer = SessionStore(tmp_path)
    for index in range(20):
        await writer.append("s1", f"r{index}", UserMessage(content=f"message {index}"))

    session = SessionStore(tmp_path).read("s1")
    lines = session.messages

    assert not any(line.message.decoded for line in lines), "reading decodes nothing"
    assert [len(line.message) for line in lines] == [1] * 20, "the length is known without decoding"
    assert not any(line.message.decoded for line in lines), "and so is asking how many"

    assert lines[7].message[0].content == "message 7"
    assert [line.message.decoded for line in lines].count(True) == 1, "only the one that was looked into"


async def test_an_undecoded_line_is_written_back_exactly_as_it_was_read(tmp_path: Path):
    """The stored form is the envelope, so a line nobody opened must not change on its way out."""
    writer = SessionStore(tmp_path)
    await writer.append("s1", "r", UserMessage(content="hello \u2028 world"))
    await writer.append(
        "s1", "r", AssistantMessage(content="hi", tool_calls=(ToolCall("c1", "read_file", {"path": "a.py"}),))
    )
    stored = [json.loads(line) for line in writer.session_path("s1").read_bytes().splitlines()]

    session = SessionStore(tmp_path).read("s1")

    for line, raw in zip(session.messages, stored[1:], strict=True):
        assert json.loads(line.model_dump_json())["message"] == raw["message"]
        assert not line.message.decoded, "writing it out did not open it"


async def test_a_message_sequence_behaves_as_the_tuple_it_replaces(tmp_path: Path):
    writer = SessionStore(tmp_path)
    await writer.append("s1", "r", UserMessage(content="first"))

    (lazy,) = SessionStore(tmp_path).read("s1").messages
    messages = lazy.message

    assert len(messages) == 1
    assert [message.content for message in messages] == ["first"]
    assert messages[0] is messages[-1]
    assert messages[0:1] == (messages[0],)
    assert messages == (messages[0],) and messages == messages
    assert messages != ()
    assert "decoded" in repr(messages)
    with pytest.raises(TypeError):
        hash(messages)
    with pytest.raises(IndexError):
        messages[1]


def test_messages_built_in_python_are_validated_when_they_are_built():
    """A writer that hands over a malformed envelope is told at once, before anything is written."""
    with pytest.raises(ValidationError):
        MessageLine(
            id="m",
            session_id="s",
            request_id="r",
            message=({"kind": 99, "data": {}},),
            timing=MessageTiming.instant(),
            created_at=now(),
        )

    line = MessageLine(
        id="m",
        session_id="s",
        request_id="r",
        message=({"kind": 2, "data": {"content": "hi"}},),
        timing=MessageTiming.instant(),
        created_at=now(),
    )
    assert line.message.decoded and line.message[0].content == "hi"


async def test_a_corrupt_envelope_in_a_line_nobody_opens_is_found_when_somebody_does(tmp_path: Path):
    """The cost of deferring: the line parses, and an envelope the runtime cannot decode shows later.

    The structure of a record is still checked when the file is read, so a torn or
    reordered file is refused as before; only a well-formed line holding an envelope of a
    kind the runtime does not know waits for the first look.
    """
    writer = SessionStore(tmp_path)
    await writer.append("s1", "r", UserMessage(content="fine"))
    path = writer.session_path("s1")
    record = json.loads(path.read_bytes().splitlines()[-1])
    record["id"] = "bad"
    record["parent"] = json.loads(path.read_bytes().splitlines()[-1])["id"]
    record["message"] = [{"kind": 99, "data": {}}]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")

    session = SessionStore(tmp_path).read("s1")

    assert [line.id for line in session.messages][-1] == "bad", "the file reads"
    with pytest.raises(ValueError):
        session.messages[-1].message[0]


# -- forking a session -------------------------------------------------------------


async def test_a_fork_carries_the_context_and_leaves_the_rest_behind(tmp_path: Path):
    """What is copied is what a request would send, not everything the file holds.

    The messages a checkpoint replaced are not part of the conversation any more: a
    fork that copied them would carry context the model never sees, and the fork
    exists to start from what the model is working with.
    """
    from zett_agent.messages import AssistantMessage

    store = SessionStore(tmp_path)
    ids = [await store.append("s1", f"r{index}", UserMessage(content=f"message {index}")) for index in range(4)]
    await store.checkpoint("s1", _summary("the first two, summarized"), ids[1], 0)
    await store.append("s1", "r2", AssistantMessage(content="after the checkpoint"))

    fork_id = store.fork("s1")
    fork = SessionStore(tmp_path).read(fork_id)
    source = SessionStore(tmp_path).read("s1")

    assert fork_id != "s1"
    assert [line.message[0].content for line in fork.messages] == [
        "the first two, summarized",
        "message 2",
        "message 3",
        "after the checkpoint",
    ]
    assert fork.compactions == (), "the summary is a message now: there is no boundary to sit on"
    assert _active_messages(SessionStore(tmp_path), fork_id) == _active_messages(SessionStore(tmp_path), "s1"), (
        "the same context, message for message"
    )
    assert [line.message[0].content for line in source.messages] == [
        "message 0",
        "message 1",
        "message 2",
        "message 3",
        "after the checkpoint",
    ], "the session forked from is untouched"


async def test_a_fork_without_a_checkpoint_is_the_whole_branch(tmp_path: Path):
    store = SessionStore(tmp_path)
    for index in range(3):
        await store.append("s1", "r", UserMessage(content=f"message {index}"))

    fork = SessionStore(tmp_path).read(store.fork("s1"))

    assert [line.message[0].content for line in fork.messages] == ["message 0", "message 1", "message 2"]


async def test_a_fork_keeps_the_usage_tags_and_timing_it_was_taken_from(tmp_path: Path):
    """A forked conversation reads, and counts, the way the one it came from did."""
    from zett_agent.messages import AssistantMessage

    from zettcode.app.agent.side import SIDE

    store = SessionStore(tmp_path)
    timing = MessageTiming(started_at=now(), completed_at=now(), duration_ns=2_500_000_000)
    await store.append("s1", "r1", UserMessage(content="ask"), tags={SIDE: True}, metadata={"note": "kept"})
    await store.append(
        "s1",
        "r1",
        AssistantMessage(content="answer"),
        timing=timing,
        usage=ModelUsage(input_tokens=1_000, output_tokens=20, cache_read_tokens=900),
    )

    fork = SessionStore(tmp_path).read(store.fork("s1"))

    asked, answered = fork.messages
    assert asked.tags == {SIDE: True} and asked.metadata == {"note": "kept"}
    assert asked.request_id == "r1"
    assert answered.usage is not None and answered.usage.input_tokens == 1_000
    assert answered.usage.cache_read_tokens == 900
    assert answered.timing.duration_ns == 2_500_000_000


async def test_a_fork_names_where_it_came_from_and_carries_the_title(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("s1", "r", UserMessage(content="hello"))
    await store.set_title("s1", "Fix the parser")

    fork_id = store.fork("s1")

    assert store.read(fork_id).header is not None
    assert store.read(fork_id).parent_session_id == "s1"
    assert store.session_title(fork_id) == "Fix the parser (fork)"
    assert store.session_title("s1") == "Fix the parser", "the original keeps its own name"


async def test_a_fork_of_a_fork_and_a_nameless_one_are_both_fine(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append("s1", "r", UserMessage(content="hello"))

    nameless = store.fork("s1")
    assert store.session_title(nameless) is None

    await store.set_title(nameless, "a name long enough to matter here")
    again = store.fork(nameless)
    assert store.session_title(again) == "a name long enough to matter here (fork)"


async def test_a_fork_that_is_too_long_to_name_stays_unnamed(tmp_path: Path):
    """The suffix is a nicety; a name at the limit keeps the fork rather than breaking it."""
    store = SessionStore(tmp_path)
    await store.append("s1", "r", UserMessage(content="hello"))
    await store.set_title("s1", "x" * MAX_TITLE)

    fork_id = store.fork("s1")

    assert store.session_title(fork_id) is None
    assert [line.message[0].content for line in store.read(fork_id).messages] == ["hello"]


async def test_forking_something_with_nothing_in_it_is_refused(tmp_path: Path):
    store = SessionStore(tmp_path)

    with pytest.raises(ValueError, match="Nothing to fork yet"):
        store.fork("no-such-session")

    await store.set_title("empty", "a session with a name and no messages")
    with pytest.raises(ValueError, match="Nothing to fork yet"):
        store.fork("empty")


async def test_a_fork_can_be_continued_and_only_shows_the_forked_branch(tmp_path: Path):
    store = SessionStore(tmp_path)
    for index in range(3):
        await store.append("s1", "r", UserMessage(content=f"message {index}"))

    fork_id = store.fork("s1")
    await store.append(fork_id, "r", UserMessage(content="a new direction"))

    fork = SessionStore(tmp_path).read(fork_id)
    assert [line.message[0].content for line in fork.branch()] == [
        "message 0",
        "message 1",
        "message 2",
        "a new direction",
    ]
    assert len(SessionStore(tmp_path).read("s1").messages) == 3, "the source did not grow"


async def test_a_forked_session_keeps_its_parent_when_a_later_append_names_none(tmp_path: Path):
    """The runtime hands the stored parent back on every append; a caller that names
    none is leaving the header as it is, not asking for it to be changed."""
    store = SessionStore(tmp_path)
    await store.append("s1", "r", UserMessage(content="hello"))
    fork_id = store.fork("s1")

    await store.append(fork_id, "r", UserMessage(content="onwards"))
    await store.append(fork_id, "r", UserMessage(content="and onwards"), parent_session_id=fork_id and "s1")

    assert store.read(fork_id).parent_session_id == "s1"
    with pytest.raises(ValueError, match="cannot change after creation"):
        await store.append(fork_id, "r", UserMessage(content="elsewhere"), parent_session_id="some-other-session")
