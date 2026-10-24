"""A session that never held a conversation leaves nothing in the store.

An unused launch is closed the ordinary way (it tidies its own folder, and the project's folder with it when
that is bare), or it was killed (the next launch sweeps what it left, if no process has it open).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.storage import LOCK_FILE, STORE_FILE, SessionLocks, SessionStore, prune_empty
from zettcode.filelock import SingletonLock

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"
C = "03c30d97-cccc-7000-8000-000000000003"


def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    (tmp_path / "work").mkdir(exist_ok=True)
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        sessions_enabled=False,
    )
    return runtime_module.ZettCodeEngine.preview(config)


def entries(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*")) if root.exists() else []


def test_opening_a_store_creates_nothing(tmp_path: Path):
    SessionStore(tmp_path / "sessions", tmp_path / "work")

    assert not (tmp_path / "sessions").exists()


async def test_a_launch_that_is_closed_unused_leaves_nothing_behind(tmp_path: Path, monkeypatch):
    started = runtime(tmp_path, monkeypatch)
    folder = started.persistence.session_dir(started.session_id)
    assert (folder / LOCK_FILE).is_file(), "while it runs, the lock is on disk"

    await started.aclose()

    assert not folder.exists()
    assert not started.persistence.workspace_dir.exists(), "and the project's folder goes with it"
    assert entries(tmp_path / "sessions") == []


async def test_a_launch_that_held_a_conversation_keeps_its_folders(tmp_path: Path, monkeypatch):
    started = runtime(tmp_path, monkeypatch)
    await started.persistence.append(started.session_id, "req", UserMessage(content="hello"))

    await started.aclose()

    folder = started.persistence.session_dir(started.session_id)
    assert (folder / STORE_FILE).is_file()
    assert started.persistence.workspace_dir.is_dir()


async def test_leaving_an_unused_session_for_another_removes_the_first(tmp_path: Path, monkeypatch):
    started = runtime(tmp_path, monkeypatch)
    first = started.persistence.session_dir(started.session_id)

    second_id = started.new_session()

    assert not first.exists()
    assert started.persistence.session_dir(second_id).is_dir()
    started.session_locks.release()


def test_the_workspace_folder_stays_while_another_session_is_in_it(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / "work")
    other = SessionLocks(store.session_dir)
    mine = SessionLocks(store.session_dir)
    assert other.claim(A) and mine.claim(B)

    mine.release()

    assert not store.session_dir(B).exists()
    assert store.workspace_dir.is_dir(), "the other session's folder is still in it"
    other.release()
    assert not store.workspace_dir.exists()


# -- what a killed process left ---------------------------------------------------------------------------------


def stale(store: SessionStore, session_id: str) -> Path:
    """A session folder as a killed process leaves it: a lock file nobody holds, and no conversation."""
    folder = store.session_dir(session_id)
    folder.mkdir(parents=True)
    (folder / LOCK_FILE).touch()
    return folder


def test_a_folder_a_killed_launch_left_is_swept(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / "work")
    one, two = stale(store, A), stale(store, B)

    assert prune_empty(store.workspace_dir) == 2

    assert not one.exists() and not two.exists()
    assert not store.workspace_dir.exists(), "nothing is left in the project's folder either"


def test_a_folder_another_process_has_open_is_left_alone(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / "work")
    open_elsewhere = stale(store, A)
    abandoned = stale(store, B)
    holder = SingletonLock(open_elsewhere / LOCK_FILE)
    assert holder.acquire()
    try:
        assert prune_empty(store.workspace_dir) == 1
        assert open_elsewhere.is_dir() and not abandoned.exists()
    finally:
        holder.release()


async def test_a_session_with_a_conversation_or_anything_else_in_it_is_never_swept(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / "work")
    await store.append(A, "req", UserMessage(content="hello"))
    (store.session_dir(A) / LOCK_FILE).touch()
    odd = stale(store, B)
    (odd / "notes.txt").write_text("keep me")

    assert prune_empty(store.workspace_dir) == 0

    assert (store.session_dir(A) / STORE_FILE).is_file()
    assert (odd / "notes.txt").read_text() == "keep me"


def test_a_folder_that_is_not_there_is_not_an_error(tmp_path: Path):
    assert prune_empty(tmp_path / "never made") == 0


async def test_starting_a_launch_sweeps_what_an_earlier_one_left(tmp_path: Path, monkeypatch):
    started = runtime(tmp_path, monkeypatch)
    old = stale(started.persistence, C)

    monkeypatch.setattr(runtime_module.ZettCodeEngine, "_build", _no_build)
    await started.start()
    await started._tidying

    assert not old.exists()
    assert started.persistence.session_dir(started.session_id).is_dir(), "its own, held, is not touched"
    await started.aclose()


async def _no_build(self):
    return self
