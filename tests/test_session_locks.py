"""The lock on a session: one process at a time may have it open, and a process that dies lets go of it."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from zettcode.app.agent.storage import (
    LOCK_FILE,
    LOCKED_MESSAGE,
    STORE_FILE,
    NoLocks,
    SessionLocked,
    SessionLocks,
    SessionStore,
)

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


@pytest.fixture
def locks(tmp_path: Path) -> SessionLocks:
    """A process's lock over a store in a temporary directory."""
    store = SessionStore(tmp_path, tmp_path / "work")
    held = SessionLocks(store.session_dir)
    yield held
    held.release()


def another_process(locks: SessionLocks) -> SessionLocks:
    """A second holder over the same store: what another process is, as far as the operating system can tell."""
    return SessionLocks(locks._directory_of)


# -- taking it ---------------------------------------------------------------------------------------------------


def test_a_session_nobody_has_open_is_taken_and_the_lock_file_lives_in_its_own_folder(locks: SessionLocks):
    assert locks.claim(A) is True

    assert locks.held == A and locks.holds(A) and not locks.holds(B)
    assert (locks._directory_of(A) / LOCK_FILE).is_file()


def test_a_session_another_process_has_open_cannot_be_taken(locks: SessionLocks):
    other = another_process(locks)
    assert other.claim(A) is True

    assert locks.claim(A) is False
    assert locks.held is None and not locks.holds(A)
    other.release()


def test_two_sessions_are_independent_and_each_can_be_held_by_a_different_process(locks: SessionLocks):
    other = another_process(locks)

    assert locks.claim(A) is True and other.claim(B) is True
    assert locks.holds(A) and other.holds(B)
    other.release()


def test_asking_again_for_the_session_already_held_is_a_yes_and_changes_nothing(locks: SessionLocks):
    locks.claim(A)
    first = locks._lock

    assert locks.claim(A) is True and locks._lock is first


def test_a_process_holds_one_session_so_taking_another_lets_go_of_the_first(locks: SessionLocks):
    other = another_process(locks)
    locks.claim(A)

    assert locks.claim(B) is True

    assert locks.held == B and not locks.holds(A)
    assert other.claim(A) is True, "the one left behind is free for anybody"
    other.release()


def test_a_session_that_could_not_be_taken_still_lets_go_of_the_one_that_was_held(locks: SessionLocks):
    """The process is no longer working in the first, whatever happened to the second."""
    other = another_process(locks)
    other.claim(B)
    locks.claim(A)

    assert locks.claim(B) is False

    assert locks.held is None
    assert another_process(locks).claim(A) is True
    other.release()


def test_the_lock_can_be_taken_again_once_the_other_holder_has_let_go(locks: SessionLocks):
    other = another_process(locks)
    other.claim(A)
    assert locks.claim(A) is False

    other.release()

    assert locks.claim(A) is True


def test_an_id_the_store_could_not_have_written_is_refused_before_any_file_is_made(locks: SessionLocks, tmp_path: Path):
    for bad in ("../escape", "a/b", "", ".hidden", "x" * 5 + ".."):
        with pytest.raises(ValueError):
            locks.claim(bad)

    assert not list(tmp_path.rglob(LOCK_FILE))


# -- letting go --------------------------------------------------------------------------------------------------


def test_releasing_twice_and_releasing_nothing_are_safe(locks: SessionLocks):
    locks.release()
    locks.claim(A)
    locks.release()
    locks.release()

    assert locks.held is None


def test_a_session_that_was_never_written_leaves_no_folder_behind(locks: SessionLocks):
    folder = locks._directory_of(A)
    locks.claim(A)
    assert folder.is_dir()

    locks.release()

    assert not folder.exists(), "a launch closed unused must not leave an empty session on disk"


def test_a_session_with_a_conversation_keeps_its_folder_and_its_lock_file(locks: SessionLocks):
    folder = locks._directory_of(A)
    locks.claim(A)
    (folder / STORE_FILE).write_text("{}\n", encoding="utf-8")

    locks.release()

    assert (folder / STORE_FILE).exists() and (folder / LOCK_FILE).exists()
    assert another_process(locks).claim(A) is True


def test_a_folder_with_other_files_in_it_is_never_removed(locks: SessionLocks):
    folder = locks._directory_of(A)
    locks.claim(A)
    (folder / "tool-output").mkdir()

    locks.release()

    assert (folder / "tool-output").is_dir()


# -- the operating system, not a file, is what holds it -------------------------------------------------------------

HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from zettcode.app.agent.storage import SessionLocks, SessionStore

    store = SessionStore(Path(sys.argv[1]), Path(sys.argv[1]) / "work")
    locks = SessionLocks(store.session_dir)
    print("held" if locks.claim(sys.argv[2]) else "refused", flush=True)
    time.sleep(120)
    """
)


def _holder(tmp_path: Path, session_id: str) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tmp_path), session_id], stdout=subprocess.PIPE, text=True
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_session_another_real_process_has_open_cannot_be_taken_and_is_free_when_that_process_ends(
    locks: SessionLocks, tmp_path: Path
):
    holder = _holder(tmp_path, A)
    try:
        assert locks.claim(A) is False
    finally:
        holder.terminate()
        holder.wait(timeout=10)

    # The operating system lets go of a dead process's lock a moment after it has gone, and on Windows not at once.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not locks.claim(A):
        time.sleep(0.05)
    assert locks.holds(A)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_a_process_that_is_killed_does_not_leave_its_session_locked(locks: SessionLocks, tmp_path: Path):
    """The point of an operating-system lock over a pid in a file: nothing stale to clear by hand."""
    holder = _holder(tmp_path, A)
    assert locks.claim(A) is False

    os.kill(holder.pid, signal.SIGKILL)
    holder.wait(timeout=10)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not locks.claim(A):
        time.sleep(0.05)

    assert locks.holds(A)
    assert (locks._directory_of(A) / LOCK_FILE).exists(), "the file stayed; the lock did not"


# -- what it is for ------------------------------------------------------------------------------------------------


def test_the_error_for_a_write_to_a_locked_session_is_a_value_error_with_a_plain_message():
    error = SessionLocked()

    assert isinstance(error, ValueError) and str(error) == LOCKED_MESSAGE
    assert "another ZettCode process" in LOCKED_MESSAGE and "read-only" in LOCKED_MESSAGE


def test_a_runtime_with_no_store_shares_nothing_so_everything_is_held():
    guard = NoLocks()

    assert guard.claim("anything") and guard.holds("anything")
    guard.release()
