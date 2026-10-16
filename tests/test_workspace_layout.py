"""The workspace folder is named after the project's path, and an older base64 folder is moved to that name."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.app.agent.storage import (
    LOCK_FILE,
    STORE_FILE,
    SessionStore,
    find_workspace,
    legacy_workspace_key,
    open_workspace,
    workspace_key,
)
from zettcode.app.agent.storage import layout as layout_module
from zettcode.app.agent.storage.layout import OWNER_FILE
from zettcode.app.agent.storage.ledger import LedgerReader
from zettcode.filelock import SingletonLock

SESSION = "01a10b75-aaaa-7000-8000-000000000001"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A project directory that exists, so its path resolves to itself."""
    path = tmp_path / "projects" / "api"
    path.mkdir(parents=True)
    return path.resolve()


async def seeded_legacy(root: Path, work: Path) -> Path:
    """A store the way an older version left it: one session under the base64 name."""
    store = SessionStore(root, work)
    await store.append(SESSION, "req", UserMessage(content="hello"))
    old = root / legacy_workspace_key(work)
    store.workspace_dir.rename(old)
    (old / OWNER_FILE).unlink()
    return old


@pytest.fixture
def roomy(monkeypatch: pytest.MonkeyPatch) -> None:
    """No cap on the name: a temporary directory's own path is already longer than the real one."""
    monkeypatch.setattr(layout_module, "MAX_KEY_CHARS", 10_000)


def test_the_levels_of_the_path_are_joined_with_a_dash(tmp_path: Path, roomy: None):
    path = tmp_path.resolve() / "projects" / "api"

    key = workspace_key(path)

    assert key.endswith("-projects-api")
    assert os.sep not in key
    assert "/" not in key


def test_a_character_a_file_name_cannot_hold_becomes_a_dash(tmp_path: Path, roomy: None):
    path = tmp_path.resolve() / "my project+v2" / "a_b.c-d"

    key = workspace_key(path)

    assert key.endswith("-my-project-v2-a_b.c-d")
    assert " " not in key
    assert "+" not in key


def test_a_very_long_path_keeps_a_digest_and_stays_apart_from_another():
    one = workspace_key("/" + "deep/" * 200 + "one")
    two = workspace_key("/" + "deep/" * 200 + "two")

    assert len(one) <= 120
    assert len(two) <= 120
    assert one != two


def test_a_new_workspace_gets_the_readable_folder_and_a_note_of_whose_it_is(tmp_path: Path, work: Path):
    store = SessionStore(tmp_path / "store", work)

    assert store.workspace_dir == tmp_path / "store" / workspace_key(work)
    assert store.workspace_dir.name != legacy_workspace_key(work)
    assert (store.workspace_dir / OWNER_FILE).read_text().strip() == str(work)
    assert not (tmp_path / "store" / legacy_workspace_key(work)).exists()


async def test_an_old_base64_folder_is_moved_to_the_readable_name_with_its_sessions(tmp_path: Path, work: Path):
    root = tmp_path / "store"
    old = await seeded_legacy(root, work)
    before = (old / SESSION / STORE_FILE).read_bytes()

    store = SessionStore(root, work)

    assert store.workspace_dir == root / workspace_key(work)
    assert not old.exists()
    assert (store.workspace_dir / SESSION / STORE_FILE).read_bytes() == before
    assert [session.session_id for session in await store.list_sessions()] == [SESSION]
    assert (store.workspace_dir / OWNER_FILE).read_text().strip() == str(work)
    assert sorted(path.name for path in root.iterdir()) == [workspace_key(work)]


async def test_when_the_rename_fails_the_old_folder_keeps_being_used(
    tmp_path: Path, work: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "store"
    old = await seeded_legacy(root, work)

    def refuse(source: object, target: object) -> None:
        raise PermissionError("a file in the folder is open")

    monkeypatch.setattr(layout_module.os, "rename", refuse)
    store = SessionStore(root, work)

    assert store.workspace_dir == old
    assert not (root / workspace_key(work)).exists()
    assert [session.session_id for session in await store.list_sessions()] == [SESSION]
    await store.append(SESSION, "req2", UserMessage(content="more"))
    assert sorted(path.name for path in root.iterdir()) == [old.name]

    monkeypatch.undo()
    later = SessionStore(root, work)
    assert later.workspace_dir == root / workspace_key(work)
    assert len(later.read(SESSION).messages) == 2


async def test_a_folder_with_a_session_open_in_a_process_is_not_moved(tmp_path: Path, work: Path):
    root = tmp_path / "store"
    old = await seeded_legacy(root, work)
    lock = SingletonLock(old / SESSION / LOCK_FILE)
    assert lock.acquire()
    try:
        store = SessionStore(root, work)
        assert store.workspace_dir == old
        assert not (root / workspace_key(work)).exists()
    finally:
        lock.release()

    assert SessionStore(root, work).workspace_dir == root / workspace_key(work)


async def test_another_process_that_moved_it_first_is_not_an_error(
    tmp_path: Path, work: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "store"
    old = await seeded_legacy(root, work)
    real = os.rename

    def lose_the_race(source: object, target: object) -> None:
        real(source, target)  # type: ignore[arg-type]
        raise FileNotFoundError(source)

    monkeypatch.setattr(layout_module.os, "rename", lose_the_race)
    store = SessionStore(root, work)

    assert store.workspace_dir == root / workspace_key(work)
    assert not old.exists()
    assert [session.session_id for session in await store.list_sessions()] == [SESSION]


def test_two_paths_that_read_alike_do_not_share_a_folder(tmp_path: Path, roomy: None):
    root = tmp_path / "store"
    one = tmp_path / "a-b" / "c"
    two = tmp_path / "a" / "b-c"
    one.mkdir(parents=True)
    two.mkdir(parents=True)
    assert workspace_key(one) == workspace_key(two)

    first = SessionStore(root, one)
    second = SessionStore(root, two)

    assert first.workspace_dir == root / workspace_key(one)
    assert second.workspace_dir == root / legacy_workspace_key(two)
    assert first.workspace_dir != second.workspace_dir
    # The one that found the name taken is stable: it finds its own folder the next time too.
    assert SessionStore(root, two).workspace_dir == second.workspace_dir
    assert SessionStore(root, one).workspace_dir == first.workspace_dir


async def test_looking_for_a_workspace_changes_nothing_on_disk(tmp_path: Path, work: Path):
    root = tmp_path / "store"

    assert find_workspace(root, work) == root / workspace_key(work)
    assert not root.exists()

    old = await seeded_legacy(root, work)
    before = sorted(path.name for path in root.iterdir())

    assert find_workspace(root, work) == old
    assert sorted(path.name for path in root.iterdir()) == before
    assert not (root / workspace_key(work)).exists()


async def test_opening_twice_is_the_same_folder(tmp_path: Path, work: Path):
    root = tmp_path / "store"

    assert open_workspace(root, work) == open_workspace(root, work)
    assert find_workspace(root, work) == open_workspace(root, work)


async def test_usage_is_read_from_the_old_folder_before_the_move_and_from_the_new_one_after(tmp_path: Path, work: Path):
    root = tmp_path / "store"
    old = await seeded_legacy(root, work)

    assert LedgerReader(root, work, index=False).directory == old
    SessionStore(root, work)

    assert LedgerReader(root, work, index=False).directory == root / workspace_key(work)
    assert not old.exists()
