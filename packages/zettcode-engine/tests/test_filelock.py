"""One broker at a time, and one session open in one terminal: a lock the operating system lets go of when the holder dies."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from zettcode.filelock import SingletonLock, is_held

# -- the lock ----------------------------------------------------------------------------------------------


def test_the_first_taker_gets_the_lock_and_the_second_does_not(tmp_path: Path):
    first, second = SingletonLock(tmp_path / "lock"), SingletonLock(tmp_path / "lock")

    assert first.acquire() is True
    try:
        assert second.acquire() is False
        assert not second.held
    finally:
        first.release()


def test_a_released_lock_can_be_taken_again(tmp_path: Path):
    first = SingletonLock(tmp_path / "lock")
    assert first.acquire()
    first.release()

    assert SingletonLock(tmp_path / "lock").acquire() is True


def test_holding_the_lock_twice_is_the_same_hold(tmp_path: Path):
    lock = SingletonLock(tmp_path / "lock")
    try:
        assert lock.acquire() and lock.acquire() and lock.held
    finally:
        lock.release()


def test_releasing_is_safe_when_not_held_and_safe_twice(tmp_path: Path):
    lock = SingletonLock(tmp_path / "lock")
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()

    assert not lock.held


def test_the_lock_makes_its_directory(tmp_path: Path):
    lock = SingletonLock(tmp_path / "a" / "b" / "lock")
    try:
        assert lock.acquire()
    finally:
        lock.release()


def test_a_failed_attempt_does_not_leave_the_loser_holding_anything(tmp_path: Path):
    winner, loser = SingletonLock(tmp_path / "lock"), SingletonLock(tmp_path / "lock")
    assert winner.acquire()
    assert not loser.acquire()
    winner.release()

    assert loser.acquire() is True, "the loser can try again once the winner has gone"
    loser.release()


HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from zettcode.filelock import SingletonLock, is_held

    lock = SingletonLock(Path(sys.argv[1]))
    print("held" if lock.acquire() else "refused", flush=True)
    time.sleep(60)
    """
)


def _holder(path: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen([sys.executable, "-c", HOLDER, str(path)], stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_lock_held_by_another_process_is_not_given_away(tmp_path: Path):
    holder = _holder(tmp_path / "lock")
    try:
        assert SingletonLock(tmp_path / "lock").acquire() is False
    finally:
        holder.kill()
        holder.wait()


def test_a_lock_dies_with_the_process_that_held_it_so_it_can_never_go_stale(tmp_path: Path):
    """This is why the broker uses a lock and not a pid in a file: a killed process cannot tidy up."""
    holder = _holder(tmp_path / "lock")
    holder.kill()
    holder.wait()

    deadline = time.monotonic() + 5
    taken = False
    lock = SingletonLock(tmp_path / "lock")
    while time.monotonic() < deadline and not taken:
        taken = lock.acquire()
        time.sleep(0.05)
    try:
        assert taken
    finally:
        lock.release()


# -- asking whether a broker is alive, and waiting for the lock ---------------------------------------------


def test_the_lock_says_whether_somebody_holds_it_and_looking_leaves_nothing_held(tmp_path: Path):
    path = tmp_path / "lock"

    assert is_held(path) is False
    assert is_held(path) is False, "looking is not holding"
    holder = _holder(path)
    try:
        assert is_held(path) is True
    finally:
        holder.kill()
        holder.wait()
    deadline = time.monotonic() + 5
    while is_held(path) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert is_held(path) is False, "a holder that was killed is gone, whatever it left behind"


def test_a_lock_in_a_directory_that_does_not_exist_is_simply_free(tmp_path: Path):
    assert is_held(tmp_path / "missing" / "lock") is False


def test_a_caller_that_is_willing_to_wait_gets_the_lock_when_the_holder_lets_go_in_time(tmp_path: Path):
    path = tmp_path / "lock"
    holder, waiter = SingletonLock(path), SingletonLock(path)
    assert holder.acquire()
    threading.Timer(0.15, holder.release).start()

    started = time.monotonic()
    got = waiter.acquire(wait=2.0)
    try:
        assert got and 0.1 < time.monotonic() - started < 1.5
    finally:
        waiter.release()


def test_a_caller_that_waits_gives_up_when_the_holder_does_not_let_go(tmp_path: Path):
    path = tmp_path / "lock"
    holder, waiter = SingletonLock(path), SingletonLock(path)
    assert holder.acquire()
    try:
        started = time.monotonic()

        assert waiter.acquire(wait=0.15) is False
        assert 0.1 < time.monotonic() - started < 1.0
    finally:
        holder.release()


def test_a_session_glancing_at_the_lock_does_not_make_a_starting_broker_think_another_is_running(tmp_path: Path):
    """The reason `acquire` can wait: the probe holds the lock for an instant, and the broker arrives in it."""
    path = tmp_path / "lock"
    glance = SingletonLock(path)
    assert glance.acquire()
    threading.Timer(0.05, glance.release).start()

    assert SingletonLock(path).acquire(wait=1.0) is True


@pytest.mark.skipif(sys.platform == "win32", reason="an open file cannot be deleted on Windows")
def test_the_holder_can_tell_that_its_lock_file_has_been_deleted_or_replaced(tmp_path: Path):
    path = tmp_path / "lock"
    lock = SingletonLock(path)
    assert lock.acquire() and lock.still_ours()
    try:
        path.unlink()
        assert lock.still_ours() is False, "deleted"

        path.write_bytes(b"")
        assert lock.still_ours() is False, "replaced by another file at the same path"
        assert SingletonLock(path).acquire() is True, "which is exactly how a second broker would get in"
    finally:
        lock.release()


def test_a_lock_not_held_is_not_ours(tmp_path: Path):
    assert SingletonLock(tmp_path / "lock").still_ours() is False
