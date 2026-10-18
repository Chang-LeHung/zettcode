"""The per-session self-compaction flag: one field of the session's own metadata file.

It is metadata and not conversation, so turning it on or off is one small atomic rewrite of
``metadata.json`` — never a line in ``data.jsonl`` — and every other field of the file has to
survive it. A choice made before the first message is a choice about a session that does not
exist yet, so the store creates it, as naming one does; a write that fails raises rather than
letting a panel say the setting was saved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.storage import metadata as metadata_module
from zettcode.app.agent.storage import store as store_module
from zettcode.app.agent.storage.metadata import SESSION_METADATA_FILE, read_session_metadata


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path, workspace="/work/project")


def _file(store: SessionStore, session_id: str) -> Path:
    return store.session_dir(session_id) / SESSION_METADATA_FILE


def _record(store: SessionStore, session_id: str) -> dict:
    return json.loads(_file(store, session_id).read_text(encoding="utf-8"))


async def test_a_session_starts_with_no_choice_of_its_own(tmp_path: Path):
    store = _store(tmp_path)

    await store.append("s1", "req", UserMessage(content="hello"))

    assert store.session_self_compact("s1") is None, "it follows the configuration's default"
    assert _record(store, "s1")["self_compact"] is None


def test_a_session_that_was_never_used_has_no_choice_and_is_not_created_by_asking(tmp_path: Path):
    """The shell asks about the session on screen; asking must not write anything."""
    store = _store(tmp_path)

    assert store.session_self_compact("not-started") is None
    assert not store.session_dir("not-started").exists()


async def test_a_file_written_before_the_flag_existed_has_no_choice(tmp_path: Path):
    """The field is additive: an old file simply lacks it, and the layout version is unchanged."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    record = _record(store, "s1")
    record.pop("self_compact", None)
    _file(store, "s1").write_text(json.dumps(record), encoding="utf-8")

    metadata = read_session_metadata(_file(store, "s1"), "s1")

    assert metadata is not None, "still a valid v1 file"
    assert store.session_self_compact("s1") is None


async def test_turning_it_on_and_off_again_round_trips(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    store.set_self_compact("s1", True)

    assert store.session_self_compact("s1") is True
    assert _record(store, "s1")["self_compact"] is True

    store.set_self_compact("s1", False)

    assert store.session_self_compact("s1") is False
    assert _record(store, "s1")["self_compact"] is False


async def test_an_explicit_off_is_kept_and_is_not_the_same_as_no_choice(tmp_path: Path):
    """With the default on, off has to be remembered, or the session would turn itself back on."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    store.set_self_compact("s1", False, default=True)

    assert store.session_self_compact("s1") is False
    assert _store(tmp_path).session_self_compact("s1") is False


async def test_taking_the_choice_back_makes_the_session_follow_the_default_again(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_self_compact("s1", True)

    store.set_self_compact("s1", None)

    assert store.session_self_compact("s1") is None
    assert _record(store, "s1")["self_compact"] is None


async def test_setting_the_value_the_file_already_holds_writes_nothing(tmp_path: Path):
    """A panel may set the flag every frame; the write is the exception."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_self_compact("s1", True)
    before = _file(store, "s1").read_bytes()
    stamp = _file(store, "s1").stat().st_mtime_ns

    for _ in range(20):
        store.set_self_compact("s1", True)

    assert _file(store, "s1").read_bytes() == before
    assert _file(store, "s1").stat().st_mtime_ns == stamp, "not even rewritten with the same text"


async def test_a_rename_and_a_model_change_leave_the_flag_alone(tmp_path: Path):
    """Each write replaces the file whole, so each must carry the other fields across."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_self_compact("s1", True)

    await store.set_title("s1", "Fix the parser")
    store.set_model("s1", "gpt-5-mini")

    assert store.session_self_compact("s1") is True
    assert store.session_title("s1") == "Fix the parser" and store.session_model("s1") == "gpt-5-mini"


async def test_turning_it_off_keeps_the_title_and_the_model(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    await store.set_title("s1", "Fix the parser")
    store.set_model("s1", "gpt-5-mini")
    store.set_self_compact("s1", True)

    store.set_self_compact("s1", False)

    assert store.session_self_compact("s1") is False
    assert store.session_title("s1") == "Fix the parser" and store.session_model("s1") == "gpt-5-mini"


async def test_turning_it_on_before_the_first_message_is_kept(tmp_path: Path):
    """A choice made before anything was said is a choice about the session, not a stray."""
    store = _store(tmp_path)

    store.set_self_compact("fresh", True)

    assert store.session_self_compact("fresh") is True
    # It is a real session now: a header and a row, with no conversation in it yet.
    assert store.read("fresh").header is not None
    assert store.read("fresh").message_count == 0
    assert [info.session_id for info in await store.list_sessions()] == ["fresh"]
    # And it is on disk, not just in this process.
    assert _store(tmp_path).session_self_compact("fresh") is True


async def test_the_first_message_keeps_the_setting_made_before_it(tmp_path: Path):
    store = _store(tmp_path)
    store.set_self_compact("fresh", True)

    await store.append("fresh", "req", UserMessage(content="now I say something"))

    assert store.session_self_compact("fresh") is True


def test_a_choice_that_matches_the_default_for_a_session_that_does_not_exist_writes_nothing(tmp_path: Path):
    """A session with no choice already does what the default says, so there is nothing to save."""
    store = _store(tmp_path)

    store.set_self_compact("not-started", False)
    store.set_self_compact("also-not-started", True, default=True)
    store.set_self_compact("cleared", None)

    assert store.session_self_compact("not-started") is None
    assert not store.session_dir("not-started").exists()
    assert not store.session_dir("also-not-started").exists()
    assert not store.session_dir("cleared").exists()


def test_a_choice_that_differs_from_the_default_creates_the_session(tmp_path: Path):
    store = _store(tmp_path)

    store.set_self_compact("fresh", False, default=True)

    assert store.session_self_compact("fresh") is False
    assert _store(tmp_path).session_self_compact("fresh") is False


async def test_a_fork_inherits_the_setting(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_self_compact("s1", True)

    forked = store.fork("s1")

    assert store.session_self_compact(forked) is True
    assert store.session_self_compact("s1") is True, "and the original is untouched"


async def test_a_fork_of_a_session_that_never_chose_has_no_choice_either(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    assert store.session_self_compact(store.fork("s1")) is None


async def test_each_session_remembers_its_own_setting(tmp_path: Path):
    store = _store(tmp_path)
    await store.append("a", "req", UserMessage(content="hello"))
    await store.append("b", "req", UserMessage(content="hello"))

    store.set_self_compact("a", True)

    assert (store.session_self_compact("a"), store.session_self_compact("b")) == (True, None)


async def test_setting_it_does_not_move_the_age_the_list_shows(tmp_path: Path):
    """The list's age is conversation activity, and this is not conversation."""
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))
    before = (await store.list_sessions())[0].updated_at

    store.set_self_compact("s1", True)

    assert (await store.list_sessions())[0].updated_at == before


async def test_a_failed_write_raises_so_the_choice_is_not_reported_as_saved(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    await store.append("s1", "req", UserMessage(content="hello"))

    def fail(source, target):
        raise OSError("read-only")

    monkeypatch.setattr(metadata_module.os, "replace", fail)

    with pytest.raises(OSError, match="self-compaction"):
        store.set_self_compact("s1", True)

    assert store.session_self_compact("s1") is None, "and nothing half-written is read back"


async def test_a_failed_creation_raises_too(tmp_path: Path, monkeypatch):
    """The header is written first, so what can fail is the metadata write that follows it."""
    store = _store(tmp_path)
    real = store_module.write_session_metadata
    monkeypatch.setattr(store_module, "write_session_metadata", lambda path, metadata: False)

    with pytest.raises(OSError, match="self-compaction"):
        store.set_self_compact("fresh", True)

    monkeypatch.setattr(store_module, "write_session_metadata", real)
    assert store.session_self_compact("fresh") is None
