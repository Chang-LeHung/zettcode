"""Session metadata: one small file per session, constant in size, and old sessions carried over."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.engine.storage import SessionStore
from zettcode.engine.storage import metadata as metadata_module
from zettcode.engine.storage import store as store_module
from zettcode.engine.storage.metadata import (
    SESSION_METADATA_FILE,
    SessionActivity,
    SessionMetadata,
    SessionStarted,
    SessionTitle,
    read_session_metadata,
    write_session_metadata,
)

LONG_AGO = datetime(2020, 1, 1, tzinfo=timezone.utc)
RECENTLY = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
#: Later than any session these tests create, so that a conversation file given this time is the
#: newest thing the store knows about it. (A session cannot have been active before it began.)
FUTURE = datetime(2040, 1, 1, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path, workspace="/work/project")


def _file(store: SessionStore, session_id: str) -> Path:
    return store.session_dir(session_id) / SESSION_METADATA_FILE


def _log_line(path: Path, record) -> None:
    """Write one line of the OLD workspace log, as versions before this one did."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")


async def _old_session(
    store: SessionStore,
    session_id: str,
    *,
    title: str | None = None,
    started: datetime = LONG_AGO,
    active: datetime = RECENTLY,
    messages: int = 2,
) -> None:
    """Make a session the way an older version left it: a conversation and a line in the log."""
    for index in range(messages):
        await store.append(session_id, f"r{index}", UserMessage(content=f"message {index}"))
    _file(store, session_id).unlink()
    log = store.legacy_metadata_path
    _log_line(log, SessionStarted(session_id=session_id, created_at=started))
    _log_line(log, SessionActivity(session_id=session_id, updated_at=active))
    if title is not None:
        _log_line(log, SessionTitle(session_id=session_id, title=title))


def _age(store: SessionStore, session_id: str, when: datetime) -> None:
    """Set the conversation file's modification time, which is when the session last changed."""
    stamp = when.timestamp()
    os.utime(store.session_path(session_id), (stamp, stamp))


# -- the file: written on creation and rename, and never on a message ------------------------------


async def test_a_new_session_gets_a_metadata_file_in_its_own_folder(tmp_path: Path):
    store = _store(tmp_path)

    await store.append("s1", "req", UserMessage(content="hello"))

    metadata = read_session_metadata(_file(store, "s1"), "s1")
    assert metadata is not None and metadata.title is None
    assert metadata.created_at == metadata.updated_at
    assert _file(store, "s1").parent == store.session_dir("s1")


async def test_a_message_writes_nothing_to_the_metadata_file(tmp_path: Path):
    """The old log took a line per message; this file is the same bytes after two hundred."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="first"))
    before = _file(store, "s1").read_bytes()
    stamp = _file(store, "s1").stat().st_mtime_ns

    for index in range(200):
        await store.append("s1", f"r{index}", UserMessage(content=f"message {index}"))

    assert _file(store, "s1").read_bytes() == before
    assert _file(store, "s1").stat().st_mtime_ns == stamp, "not even rewritten with the same text"


async def test_the_metadata_stays_small_whatever_the_conversation_does(tmp_path: Path):
    """What grew without bound was the log: a line for every message ever sent."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="first"))
    await store.set_title("s1", "A reasonably long title for a session about the parser")
    small = _file(store, "s1").stat().st_size

    for index in range(500):
        await store.append("s1", f"r{index}", UserMessage(content=f"message {index}"))

    assert _file(store, "s1").stat().st_size == small and small < 400
    assert not store.legacy_metadata_path.exists()


async def test_a_checkpoint_does_not_write_the_metadata_either(tmp_path: Path):
    from zett_agent.extensions.compaction import CompactedMessage

    store = _store(tmp_path)
    ids = [await store.append("s1", f"r{i}", UserMessage(content=f"message {i}")) for i in range(4)]
    before = _file(store, "s1").read_bytes()

    await store.checkpoint("s1", CompactedMessage(content="summary"), ids[1], 0)

    assert _file(store, "s1").read_bytes() == before


async def test_naming_a_session_rewrites_its_file_and_the_title_is_read_back(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    assert store.session_title("s1") is None

    await store.set_title("s1", "  Fix the parser  ")

    assert store.session_title("s1") == "Fix the parser"
    await store.set_title("s1", "Fix the lexer")
    assert store.session_title("s1") == "Fix the lexer", "the newest name replaces the older one"


async def test_a_title_does_not_move_the_age_the_list_shows(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    _age(store, "s1", FUTURE)
    before = (await store.list_sessions())[0].updated_at
    assert before == FUTURE

    await store.set_title("s1", "A name")

    assert (await store.list_sessions())[0].updated_at == before


async def test_a_session_named_before_its_first_message_is_created_by_the_name(tmp_path: Path):
    store = _store(tmp_path)

    await store.set_title("fresh", "Planned work")

    assert store.session_title("fresh") == "Planned work"
    assert [info.session_id for info in await store.list_sessions()] == ["fresh"]


async def test_each_session_has_a_file_of_its_own_and_they_do_not_share(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("a", "req", UserMessage(content="hello"))
    await store.append("b", "req", UserMessage(content="hello"))

    await store.set_title("a", "First")

    assert store.session_title("a") == "First" and store.session_title("b") is None
    assert _file(store, "a") != _file(store, "b")


# -- the age a list shows comes from the conversation file -----------------------------------------


async def test_the_age_is_when_the_conversation_file_last_changed(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("old", "req", UserMessage(content="hello"))
    await store.append("new", "req", UserMessage(content="hello"))
    _age(store, "old", FUTURE)
    _age(store, "new", FUTURE + timedelta(days=1))

    listed = await store.list_sessions()

    assert [(info.session_id, info.updated_at) for info in listed] == [
        ("new", FUTURE + timedelta(days=1)),
        ("old", FUTURE),
    ]


async def test_a_message_moves_the_session_to_the_top_of_the_list(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("a", "req", UserMessage(content="hello"))
    await store.append("b", "req", UserMessage(content="hello"))
    _age(store, "a", FUTURE)
    _age(store, "b", FUTURE + timedelta(days=1))
    assert [info.session_id for info in await store.list_sessions()] == ["b", "a"]

    # "again" is written now, which is before FUTURE: a real message is always newer than the
    # file it lands in, so the file is touched to the present and has to be moved back to show it.
    await store.append("a", "req", UserMessage(content="again"))
    stamp = store.session_path("a").stat().st_mtime
    _age(store, "b", datetime.fromtimestamp(stamp - 100, tz=timezone.utc))
    _age(store, "a", datetime.fromtimestamp(stamp, tz=timezone.utc))

    assert [info.session_id for info in await store.list_sessions()] == ["a", "b"]


async def test_the_list_pages_by_limit_and_offset(tmp_path: Path):
    store = _store(tmp_path)
    for index, name in enumerate("abc"):
        await store.append(name, "req", UserMessage(content="hello"))
        _age(store, name, FUTURE + timedelta(days=index))

    assert [i.session_id for i in await store.list_sessions(limit=2)] == ["c", "b"]
    assert [i.session_id for i in await store.list_sessions(limit=2, offset=1)] == ["b", "a"]
    with pytest.raises(ValueError):
        await store.list_sessions(limit=0)
    with pytest.raises(ValueError):
        await store.list_sessions(offset=-1)


async def test_a_listing_never_parses_a_conversation(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("indexed", "req", UserMessage(content="hi"))
    await store.set_title("indexed", "Fix the parser crash")
    store.session_path("indexed").write_text("torn", encoding="utf-8")

    listed = await store.list_sessions()

    assert [(info.session_id, info.title) for info in listed] == [("indexed", "Fix the parser crash")]


async def test_a_folder_deleted_by_hand_has_no_row(tmp_path: Path):
    import shutil

    store = _store(tmp_path)
    await store.append("gone", "req", UserMessage(content="hi"))
    await store.append("kept", "req", UserMessage(content="hi"))
    shutil.rmtree(store.session_dir("gone"))

    assert [info.session_id for info in await store.list_sessions()] == ["kept"]
    assert store.session_title("gone") is None


# -- writes replace the file whole -----------------------------------------------------------------


def test_a_write_that_fails_leaves_the_old_file_and_no_temporary_one_behind(tmp_path: Path, monkeypatch):
    path = tmp_path / "s1" / SESSION_METADATA_FILE
    first = SessionMetadata(session_id="s1", created_at=RECENTLY, updated_at=RECENTLY, title="old")
    assert write_session_metadata(path, first) is True

    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(metadata_module.os, "replace", fail)

    written = write_session_metadata(path, first.model_copy(update={"title": "new"}))

    assert written is False
    assert read_session_metadata(path, "s1") == first, "a reader still sees the old file whole"
    assert [p.name for p in path.parent.iterdir()] == [SESSION_METADATA_FILE], "and no temporary file is left"


def test_a_read_only_store_does_not_stop_a_conversation(tmp_path: Path):
    """Metadata is never worth failing a conversation for."""
    path = tmp_path / "no" / "such" / "dir" / SESSION_METADATA_FILE
    blocked = tmp_path / "no"
    blocked.write_text("a file where a folder would have to be")

    assert (
        write_session_metadata(path, SessionMetadata(session_id="s", created_at=RECENTLY, updated_at=RECENTLY)) is False
    )


# -- a file that is missing, damaged, or wrong is rebuilt, not trusted -----------------------------


@pytest.mark.parametrize(
    "damage",
    [
        lambda path: path.write_text('{"version": 1, "session_id": "s1", "created_at"', encoding="utf-8"),
        lambda path: path.write_text("not json at all", encoding="utf-8"),
        lambda path: path.write_text("", encoding="utf-8"),
        lambda path: path.write_text("[1, 2, 3]", encoding="utf-8"),
        lambda path: path.write_text('{"version": 99, "session_id": "s1"}', encoding="utf-8"),
        lambda path: path.write_bytes(b"\xff\xfe\x00 binary"),
    ],
    ids=["torn", "not-json", "empty", "wrong-shape", "unknown-version", "binary"],
)
async def test_a_damaged_metadata_file_is_rebuilt_and_the_session_stays_usable(tmp_path: Path, damage):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    damage(_file(store, "s1"))

    listed = await store.list_sessions()

    assert [info.session_id for info in listed] == ["s1"]
    assert read_session_metadata(_file(store, "s1"), "s1") is not None, "and it is whole again"


async def test_a_file_that_names_another_session_is_not_trusted(tmp_path: Path):
    """A folder copied under a new name still carries the old name's file."""
    import shutil

    store = _store(tmp_path)
    await store.append("original", "req", UserMessage(content="hello"))
    await store.set_title("original", "The original")
    shutil.copytree(store.session_dir("original"), store.session_dir("copy"))

    assert store.session_title("copy") is None, "the copy is not given the original's name"
    assert read_session_metadata(_file(store, "copy"), "copy") is not None
    assert store.session_title("original") == "The original"


async def test_a_session_with_a_conversation_and_no_metadata_anywhere_is_listed_from_its_header(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    header = store.read("s1").header
    assert header is not None
    _file(store, "s1").unlink()

    (info,) = await store.list_sessions()

    assert (info.session_id, info.title, info.created_at) == ("s1", None, header.created_at)


# -- old sessions: carried over once, then read from their own folder ------------------------------


async def test_an_old_session_is_carried_over_the_first_time_it_is_looked_at(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Fix the parser")
    assert not _file(store, "legacy").exists()

    title = store.session_title("legacy")

    assert title == "Fix the parser"
    assert read_session_metadata(_file(store, "legacy"), "legacy") is not None, "saved into the session"


async def test_after_the_carry_over_the_old_log_is_not_needed_again(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Fix the parser")
    store.session_title("legacy")
    store.legacy_metadata_path.unlink()
    fresh = _store(tmp_path)

    assert fresh.session_title("legacy") == "Fix the parser"
    assert [info.session_id for info in await fresh.list_sessions()] == ["legacy"]


async def test_after_the_carry_over_the_old_log_is_never_read_again(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Fix the parser")
    store.session_title("legacy")
    folded: list[Path] = []
    monkeypatch.setattr(store_module, "read_metadata", lambda path: folded.append(path) or [])

    fresh = _store(tmp_path)
    for _ in range(5):
        fresh.session_title("legacy")
    await fresh.list_sessions()

    assert folded == [], "a session with its own file never consults the old log"


async def test_listing_carries_over_every_old_session_and_folds_the_log_once(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    for index in range(5):
        await _old_session(store, f"old{index}", title=f"Session {index}", active=RECENTLY + timedelta(days=index))
    folded: list[Path] = []
    real = store_module.read_metadata
    monkeypatch.setattr(store_module, "read_metadata", lambda path: folded.append(path) or real(path))

    listed = await store.list_sessions()

    assert [info.session_id for info in listed] == [f"old{index}" for index in (4, 3, 2, 1, 0)]
    assert [info.title for info in listed] == [f"Session {index}" for index in (4, 3, 2, 1, 0)]
    assert len(folded) == 1, "five old sessions, one read of the log"
    assert all(_file(store, f"old{index}").is_file() for index in range(5)), "each saved into its own folder"


async def test_an_old_sessions_recorded_times_survive_the_carry_over(tmp_path: Path):
    """The conversation file may be newer than the log (a copy, a touch) or older (a restore);
    what the log recorded must not be lost, and the list's order must not change."""
    store = _store(tmp_path)
    await _old_session(store, "legacy", started=LONG_AGO, active=RECENTLY)
    _age(store, "legacy", LONG_AGO)

    (info,) = await store.list_sessions()

    assert info.created_at == LONG_AGO
    assert info.updated_at == RECENTLY, "the later of what the log said and what the file says"


async def test_an_old_session_that_was_never_named_stays_unnamed(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title=None)

    assert store.session_title("legacy") is None
    assert [info.title for info in await store.list_sessions()] == [None]


async def test_the_old_log_is_never_written_to_or_changed(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Old name")
    before = store.legacy_metadata_path.read_bytes()

    store.session_title("legacy")
    await store.list_sessions()
    await store.set_title("legacy", "New name")
    await store.append("legacy", "req", UserMessage(content="more"))
    await store.append("brand-new", "req", UserMessage(content="hello"))

    assert store.legacy_metadata_path.read_bytes() == before


async def test_renaming_an_old_session_keeps_the_times_the_log_recorded(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Old name", started=LONG_AGO, active=RECENTLY)
    _age(store, "legacy", LONG_AGO)

    await store.set_title("legacy", "New name")

    metadata = read_session_metadata(_file(store, "legacy"), "legacy")
    assert metadata is not None and metadata.title == "New name"
    assert (metadata.created_at, metadata.updated_at) == (LONG_AGO, RECENTLY)


async def test_a_log_row_with_no_conversation_does_not_invent_a_session(tmp_path: Path):
    store = _store(tmp_path)
    _log_line(store.legacy_metadata_path, SessionStarted(session_id="ghost", created_at=RECENTLY))
    _log_line(store.legacy_metadata_path, SessionTitle(session_id="ghost", title="Nothing here"))

    assert store.session_title("ghost") is None
    assert await store.list_sessions() == []
    assert not _file(store, "ghost").exists(), "and nothing is written for it"


async def test_a_damaged_old_log_is_reported_only_to_the_sessions_that_need_it(tmp_path: Path):
    """A session with its own file never needs the log, so a bad log cannot touch it; one that
    does need it hears about the damage instead of silently losing its title."""
    store = _store(tmp_path)
    await store.append("modern", "req", UserMessage(content="hello"))
    await store.set_title("modern", "Has its own file")
    await _old_session(store, "legacy", title="Needs the log")
    log = store.legacy_metadata_path
    log.write_text("this line is damaged\n" + log.read_text(encoding="utf-8"), encoding="utf-8")

    assert store.session_title("modern") == "Has its own file"
    with pytest.raises(ValueError, match="Corrupt metadata file"):
        store.session_title("legacy")


async def test_a_torn_last_line_of_the_old_log_is_still_ignored(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Intact")
    with store.legacy_metadata_path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "title", "session_id": "legacy"')

    assert store.session_title("legacy") == "Intact"


async def test_the_carry_over_survives_a_store_that_cannot_be_written(tmp_path: Path, monkeypatch):
    """Not saved is not lost: the row is still answered, and the next look tries again."""
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Fix the parser")

    def fail(source, target):
        raise OSError("read-only")

    monkeypatch.setattr(metadata_module.os, "replace", fail)

    assert store.session_title("legacy") == "Fix the parser"
    assert (await store.list_sessions())[0].title == "Fix the parser"
    assert not _file(store, "legacy").exists()


# -- forking, and the other things that read a title -----------------------------------------------


async def test_a_fork_of_an_old_session_carries_its_title_over_from_the_log(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Parser work")

    forked = store.fork("legacy")

    assert store.session_title(forked) == "Parser work (fork)"
    assert read_session_metadata(_file(store, forked), forked) is not None
    assert not store.legacy_metadata_path.read_text(encoding="utf-8").count(forked)


async def test_a_fork_writes_its_metadata_once_with_its_title(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    await store.set_title("s1", "Parser work")
    writes: list[str | None] = []
    real = store_module.write_session_metadata

    def spy(path, metadata):
        writes.append(metadata.title)
        return real(path, metadata)

    monkeypatch.setattr(store_module, "write_session_metadata", spy)

    store.fork("s1")

    assert writes == ["Parser work (fork)"]


async def test_looking_up_a_title_does_not_read_the_old_log_for_a_session_with_its_own_file(tmp_path: Path):
    """The cost this replaces: every `session_title` re-read and folded the whole log."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    await store.set_title("s1", "Named")
    store.legacy_metadata_path.write_text("garbage that would raise if it were read\n" * 3, encoding="utf-8")

    for _ in range(20):
        assert store.session_title("s1") == "Named"


async def test_a_session_that_has_no_conversation_yet_has_no_title_and_costs_no_log_read(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    folded: list[Path] = []
    monkeypatch.setattr(store_module, "read_metadata", lambda path: folded.append(path) or [])

    assert store.session_title("not-started-yet") is None
    assert folded == [], "the shell asks this for a fresh session on every frame"


async def test_a_complete_file_in_a_layout_this_version_does_not_know_is_rebuilt_not_half_read(tmp_path: Path):
    """Every field present and valid; only the version differs. A newer layout is not guessed at."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    await store.set_title("s1", "Named by this version")
    record = json.loads(_file(store, "s1").read_text(encoding="utf-8"))
    record["version"] = 99
    record["title"] = "Written by a future version"
    _file(store, "s1").write_text(json.dumps(record), encoding="utf-8")

    assert read_session_metadata(_file(store, "s1"), "s1") is None
    assert store.session_title("s1") is None, "rebuilt from what this store knows, not read as v1"
    assert read_session_metadata(_file(store, "s1"), "s1") is not None


async def test_the_listing_runs_off_the_event_loop(tmp_path: Path, monkeypatch):
    """It reads a file per session — a fifth of a second for five thousand — and is awaited from the
    interface, so it must not hold the loop while it does."""
    import threading

    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    seen: list[int] = []
    real = store._metadata
    monkeypatch.setattr(store, "_metadata", lambda session_id: seen.append(threading.get_ident()) or real(session_id))

    await store.list_sessions()

    assert seen and all(ident != threading.get_ident() for ident in seen)


# -- the model a session last used ------------------------------------------------------------------


async def test_the_model_a_session_used_is_recorded_and_read_back(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    assert store.session_model("s1") is None, "nothing is recorded until a turn says what it used"

    assert store.set_model("s1", "gpt-5-mini") is True

    assert store.session_model("s1") == "gpt-5-mini"
    assert read_session_metadata(_file(store, "s1"), "s1").model == "gpt-5-mini"  # type: ignore[union-attr]


async def test_recording_the_same_model_again_writes_nothing(tmp_path: Path):
    """It is asked about once per turn and changes once in a long while: the write is the exception."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "gpt-5-mini")
    stamp = _file(store, "s1").stat().st_mtime_ns
    before = _file(store, "s1").read_bytes()

    results = [store.set_model("s1", "gpt-5-mini") for _ in range(50)]

    assert results == [False] * 50
    assert _file(store, "s1").stat().st_mtime_ns == stamp and _file(store, "s1").read_bytes() == before


async def test_a_different_model_replaces_the_recorded_one(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "gpt-5-mini")

    assert store.set_model("s1", "GPT-4o") is True

    assert store.session_model("s1") == "GPT-4o"


async def test_nothing_is_written_for_a_session_with_no_conversation(tmp_path: Path):
    """There is no folder to put the file in; the first turn records it when it ends."""
    store = _store(tmp_path)

    assert store.set_model("not-started", "gpt-5-mini") is False

    assert store.session_model("not-started") is None
    assert not store.session_dir("not-started").exists()


@pytest.mark.parametrize("name", ["", "   ", "x" * 201], ids=["empty", "blank", "too-long"])
async def test_a_name_that_is_not_a_model_is_not_recorded(tmp_path: Path, name):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    assert store.set_model("s1", name) is False
    assert store.session_model("s1") is None


async def test_a_name_is_trimmed_before_it_is_recorded(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    store.set_model("s1", "  gpt-5-mini \n")

    assert store.session_model("s1") == "gpt-5-mini"


async def test_naming_a_session_keeps_its_model_and_choosing_a_model_keeps_its_name(tmp_path: Path):
    """Each write replaces the file whole, so each must carry the other's field across."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "gpt-5-mini")

    await store.set_title("s1", "Fix the parser")
    assert store.session_model("s1") == "gpt-5-mini" and store.session_title("s1") == "Fix the parser"

    store.set_model("s1", "GPT-4o")
    assert store.session_model("s1") == "GPT-4o" and store.session_title("s1") == "Fix the parser"


async def test_a_message_and_a_checkpoint_still_write_nothing_once_a_model_is_recorded(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "gpt-5-mini")
    before = _file(store, "s1").read_bytes()
    stamp = _file(store, "s1").stat().st_mtime_ns

    for index in range(100):
        await store.append("s1", f"r{index}", UserMessage(content=f"message {index}"))

    assert _file(store, "s1").read_bytes() == before and _file(store, "s1").stat().st_mtime_ns == stamp


async def test_a_file_written_before_models_were_recorded_reads_as_having_none(tmp_path: Path):
    """The field is additive: an old file simply lacks it, and the layout version is unchanged."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    record = json.loads(_file(store, "s1").read_text(encoding="utf-8"))
    record.pop("model", None)
    _file(store, "s1").write_text(json.dumps(record), encoding="utf-8")

    assert read_session_metadata(_file(store, "s1"), "s1") is not None, "still a valid v1 file"
    assert store.session_model("s1") is None
    assert store.set_model("s1", "gpt-5-mini") is True and store.session_model("s1") == "gpt-5-mini"


async def test_a_file_with_a_field_this_version_does_not_know_is_still_read(tmp_path: Path):
    """What lets a later version add to the file without making an earlier one rebuild it."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    await store.set_title("s1", "Kept")
    record = json.loads(_file(store, "s1").read_text(encoding="utf-8"))
    record["something_added_later"] = {"a": 1}
    _file(store, "s1").write_text(json.dumps(record), encoding="utf-8")

    assert store.session_title("s1") == "Kept"


async def test_a_session_from_an_older_version_has_no_model_and_can_be_given_one(tmp_path: Path):
    store = _store(tmp_path)
    await _old_session(store, "legacy", title="Old session")

    assert store.session_model("legacy") is None
    assert store.set_model("legacy", "gpt-5-mini") is True

    assert store.session_model("legacy") == "gpt-5-mini" and store.session_title("legacy") == "Old session"
    assert (store.session_dir("legacy") / "metadata.json").is_file()


async def test_a_fork_starts_on_the_model_the_session_it_came_from_was_using(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "GPT-4o")

    forked = store.fork("s1")

    assert store.session_model(forked) == "GPT-4o"
    assert store.session_model("s1") == "GPT-4o", "and the original is untouched"


async def test_a_fork_of_a_session_with_no_recorded_model_has_none_either(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    assert store.session_model(store.fork("s1")) is None


async def test_each_session_remembers_its_own_model(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("a", "req", UserMessage(content="hello"))
    await store.append("b", "req", UserMessage(content="hello"))

    store.set_model("a", "gpt-5-mini")
    store.set_model("b", "GPT-4o")

    assert (store.session_model("a"), store.session_model("b")) == ("gpt-5-mini", "GPT-4o")


async def test_recording_a_model_does_not_move_the_age_the_list_shows(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    _age(store, "s1", FUTURE)
    before = (await store.list_sessions())[0].updated_at

    store.set_model("s1", "gpt-5-mini")

    assert (await store.list_sessions())[0].updated_at == before == FUTURE


async def test_a_failed_write_while_recording_a_model_is_not_an_error(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    def fail(source, target):
        raise OSError("read-only")

    monkeypatch.setattr(metadata_module.os, "replace", fail)

    assert store.set_model("s1", "gpt-5-mini") is False
    assert store.session_model("s1") is None, "and nothing half-written is read back"
