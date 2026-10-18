"""The broker as a real process: started on demand, single, found again after it is killed, gone when idle.

Everything else about the broker is tested in-process; these start `python -m zettcode.broker` for
real, because what makes it a *background process* — detaching, the lock, the note on disk, exiting
by itself — only exists there.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from broker_helpers import Inbox, eventually, session
from zettcode.broker.client import BrokerClient
from zettcode.broker.files import (
    DIRECTORY_VARIABLE,
    LOCK_FILE,
    LOG_FILE,
    NOTE_FILE,
    Note,
    read_note,
    write_note,
)
from zettcode.broker.finder import spawn_broker
from zettcode.broker.protocol import PROTOCOL_VERSION
from zettcode.broker.runner import IDLE_VARIABLE, idle_seconds
from zettcode.filelock import SingletonLock

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    """A broker directory of the test's own, an idle time worth waiting for, and no broker left over."""
    directory = tmp_path / "broker"
    monkeypatch.setenv(DIRECTORY_VARIABLE, str(directory))
    monkeypatch.setenv(IDLE_VARIABLE, "1.5")
    yield directory
    info = read_note(directory)
    if info is not None:
        try:
            os.kill(info.pid, signal.SIGTERM)
        except OSError:
            pass
    _wait_until(lambda: SingletonLock(directory / LOCK_FILE).acquire() or False, 5)


def _wait_until(check, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    return None


def _real_client(directory: Path, **options) -> BrokerClient:
    options.setdefault("backoff", (0.05, 0.1, 0.2))
    options.setdefault("spawn_wait", 8.0)
    return BrokerClient(directory=directory, spawner=spawn_broker, **options)


async def _wait_async(check, timeout: float = 10.0):
    """Poll without blocking the loop: the client's own connections close on it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        await asyncio.sleep(0.05)
    return None


def _broker_is_gone(directory: Path) -> bool:
    """The lock is free and the note is removed: nothing is running there."""
    probe = SingletonLock(directory / LOCK_FILE)
    if not probe.acquire():
        return False
    probe.release()
    return read_note(directory) is None


# -- the setting -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2.5", 2.5),
        ("0.1", 0.1),
        ("", 30.0),
        ("abc", 30.0),
        ("0", 30.0),
        ("-3", 30.0),
        ("nan", 30.0),
        ("inf", 30.0),
        ("-inf", 30.0),
    ],
)
def test_the_idle_time_comes_from_the_environment_when_it_is_a_positive_finite_number(monkeypatch, value, expected):
    monkeypatch.setenv(IDLE_VARIABLE, value)

    assert idle_seconds() == expected


def test_with_nothing_in_the_environment_the_broker_waits_half_a_minute(monkeypatch):
    monkeypatch.delenv(IDLE_VARIABLE, raising=False)

    assert idle_seconds() == 30.0


# -- starting it -------------------------------------------------------------------------------------------------


async def test_a_session_that_finds_no_broker_starts_one_and_two_sessions_talk_through_it(home: Path):
    inbox = Inbox()
    first = _real_client(home)
    second = _real_client(home, on_message=inbox)
    first.set_session(session(A, "First one"))
    second.set_session(session(B, "Second one"))
    try:
        await first.start()
        await second.start()
        assert await first.wait_connected(12), first.last_error
        assert await second.wait_connected(12), second.last_error
        await eventually(lambda: any(e.handle == "second-one" for e in first.others()), 5)

        delivered = await first.send("second-one", "through a real process")

        assert delivered.to.session_id == B
        assert inbox.messages[0].text == "through a real process"
    finally:
        await first.close()
        await second.close()


async def test_a_program_outside_zettcode_reaches_a_real_broker_with_plain_http_and_the_token_from_the_note(home: Path):
    import httpx

    inbox = Inbox()
    client = _real_client(home, on_message=inbox)
    client.set_session(session(B, "Receiver"))
    try:
        await client.start()
        assert await client.wait_connected(12), client.last_error
        await eventually(lambda: any(e.session_id == B for e in client.roster), 5)
        note = read_note(home)
        assert note is not None
        headers = {"Authorization": f"Bearer {note.token}"}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{note.port}", headers=headers, trust_env=False) as web:
            listed = (await web.get("/sessions")).json()["sessions"]
            answer = await web.post(
                "/messages", json={"to": "receiver", "text": "from a script", "from": {"name": "cron"}}
            )
            refused = await httpx.AsyncClient(trust_env=False).get(f"http://127.0.0.1:{note.port}/sessions")

        assert [e["handle"] for e in listed] == ["receiver"]
        assert answer.status_code == 200 and answer.json()["disposition"] == "started"
        assert inbox.messages[0].via == "external" and inbox.messages[0].sender.handle == "cron"
        assert refused.status_code == 401
    finally:
        await client.close()


async def test_the_broker_outlives_the_session_that_started_it_and_exits_by_itself_when_idle(home: Path):
    client = _real_client(home)
    client.set_session(session(A, "a"))
    await client.start()
    assert await client.wait_connected(12), client.last_error
    info = read_note(home)
    assert info is not None

    await client.close()

    assert await _wait_async(lambda: _broker_is_gone(home), 10), "the broker did not exit when nobody was left"
    assert not (home / NOTE_FILE).exists()


async def test_the_broker_stays_while_a_session_is_connected(home: Path):
    client = _real_client(home)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)

        await asyncio.sleep(3.5)  # more than twice the idle time

        assert client.connected and not _broker_is_gone(home)
    finally:
        await client.close()


async def test_the_note_is_readable_by_its_owner_only(home: Path):
    client = _real_client(home)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)

        if os.name != "nt":
            assert (home / NOTE_FILE).stat().st_mode & 0o777 == 0o600
    finally:
        await client.close()


async def test_the_broker_writes_a_log_instead_of_a_screen(home: Path):
    client = _real_client(home)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)

        log = (home / LOG_FILE).read_text(encoding="utf-8")
        assert "listening on 127.0.0.1" in log
    finally:
        await client.close()


async def test_the_broker_does_not_hold_the_directory_the_session_was_started_in(
    home: Path, tmp_path: Path, monkeypatch
):
    """A background process that kept its parent's working directory would stop that directory being removed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    client = _real_client(home)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)
        info = read_note(home)
        assert info is not None
        if sys.platform.startswith("linux"):
            assert Path(f"/proc/{info.pid}/cwd").resolve() == home.resolve()
    finally:
        await client.close()


# -- exactly one -------------------------------------------------------------------------------------------------


def test_two_brokers_started_together_leave_exactly_one_running(home: Path):
    environment = dict(os.environ)
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "zettcode.broker"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(3)
    ]
    try:
        info = _wait_until(lambda: read_note(home))
        assert info is not None

        survivors = _wait_until(
            lambda: (
                [p for p in processes if p.poll() is None]
                if sum(p.poll() is not None for p in processes) == 2
                else None
            )
        )

        assert survivors is not None and len(survivors) == 1, (
            "two of the three should have found the lock taken and exited"
        )
        assert [p.returncode for p in processes if p.poll() is not None] == [0, 0]
        if sys.platform != "win32":  # there the interpreter in a venv is a launcher, and its pid is not the broker's
            assert survivors[0].pid == info.pid
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()


async def test_two_sessions_starting_at_once_end_up_on_the_same_broker(home: Path):
    inbox = Inbox()
    clients = [_real_client(home, on_message=inbox if n == 1 else None) for n in range(2)]
    clients[0].set_session(session(A, "one"))
    clients[1].set_session(session(B, "two"))
    try:
        await asyncio.gather(*(client.start() for client in clients))
        assert all(await asyncio.gather(*(client.wait_connected(15) for client in clients)))
        await eventually(lambda: any(e.handle == "two" for e in clients[0].others()), 5)

        await clients[0].send("two", "same broker")

        assert inbox.messages[0].text == "same broker"
    finally:
        for client in clients:
            await client.close()


# -- dying -------------------------------------------------------------------------------------------------------


async def test_a_killed_broker_is_replaced_and_the_session_registers_again(home: Path):
    inbox = Inbox()
    receiver = _real_client(home, on_message=inbox)
    sender = _real_client(home)
    receiver.set_session(session(B, "Receiver"))
    sender.set_session(session(A, "Sender"))
    try:
        await receiver.start()
        await sender.start()
        assert await receiver.wait_connected(12) and await sender.wait_connected(12)
        first = read_note(home)
        assert first is not None

        os.kill(first.pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)

        await eventually(lambda: not sender.connected and not receiver.connected, 10)
        assert await sender.wait_connected(20) and await receiver.wait_connected(20)
        await eventually(lambda: any(e.handle == "receiver" for e in sender.others()), 10)
        second = read_note(home)
        assert second is not None and second.pid != first.pid

        await sender.send("receiver", "after the kill")
        assert inbox.messages[-1].text == "after the kill"
    finally:
        await sender.close()
        await receiver.close()


def test_a_note_left_by_a_broker_that_was_killed_does_not_stop_a_new_one(home: Path):
    first = subprocess.Popen(
        [sys.executable, "-m", "zettcode.broker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        old = _wait_until(lambda: read_note(home))
        assert old is not None
        os.kill(old.pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # the broker's own pid: see _pid_alive
        first.wait()
        assert (home / NOTE_FILE).exists(), "a killed broker cannot remove its note"

        second = subprocess.Popen(
            [sys.executable, "-m", "zettcode.broker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            fresh = _wait_until(lambda: (info := read_note(home)) is not None and info.token != old.token and info)
            assert fresh and second.poll() is None
        finally:
            second.kill()
            second.wait()
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()


# -- things that go wrong with real processes ---------------------------------------------------------------------

SESSION_PROCESS = """
import asyncio, sys
from pathlib import Path
from zettcode.broker.client import BrokerClient, Receipt, SessionInfo
from zettcode.broker.finder import spawn_broker

async def main():
    client = BrokerClient(directory=Path(sys.argv[1]), spawner=spawn_broker, on_message=lambda m: Receipt(True, "", "started"))
    client.set_session(SessionInfo(sys.argv[2], sys.argv[3], "/work", "idle"))
    await client.start()
    await client.wait_connected(10)
    print("up", flush=True)
    await asyncio.sleep(120)

asyncio.run(main())
"""


def _session_process(directory: Path, session_id: str, title: str) -> subprocess.Popen[str]:
    env = dict(os.environ, **{DIRECTORY_VARIABLE: str(directory), IDLE_VARIABLE: "1.5"})
    process = subprocess.Popen(
        [sys.executable, "-c", SESSION_PROCESS, str(directory), session_id, title],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "up"
    return process


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
async def test_a_session_that_is_killed_leaves_the_roster_and_its_id_can_be_taken_again(home: Path):
    watcher = _real_client(home)
    watcher.set_session(session(B, "watcher"))
    try:
        await watcher.start()
        assert await watcher.wait_connected(12)
        victim = _session_process(home, A, "victim")
        await _wait_async(lambda: any(e.handle == "victim" for e in watcher.others()))

        victim.kill()  # SIGKILL: no goodbye of any kind
        victim.wait()

        assert await _wait_async(lambda: not watcher.others(), 5), "the broker saw the connection end"
        again = _session_process(home, A, "victim again")
        try:
            assert await _wait_async(lambda: any(e.handle == "victim-again" for e in watcher.others()))
        finally:
            again.kill()
            again.wait()
    finally:
        await watcher.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
async def test_a_frozen_broker_is_not_replaced_by_a_second_one_and_is_reported(home: Path):
    first = _real_client(home)
    first.set_session(session(A, "first"))
    try:
        await first.start()
        assert await first.wait_connected(12)
        info = read_note(home)
        assert info is not None

        os.kill(info.pid, signal.SIGSTOP)  # the broker hangs: it keeps its lock and answers nothing
        problems: list[str | None] = []
        second = _real_client(
            home,
            on_problem=problems.append,
            problem_after=0.5,
            spawn_wait=0.5,
            connect_timeout=0.5,
            request_timeout=0.5,
        )
        second.set_session(session(B, "second"))
        try:
            await second.start()
            await _wait_async(lambda: problems, 8)

            assert problems and f"pid {info.pid}" in problems[0] and "does not answer" in problems[0]
            assert read_note(home) == info, "nobody replaced the note, and no second broker started"
        finally:
            await second.close()
            os.kill(info.pid, signal.SIGCONT)
    finally:
        await first.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
async def test_a_session_that_loses_its_broker_to_a_kill_reports_nothing_if_a_new_one_comes_up_quickly(home: Path):
    problems: list[str | None] = []
    client = _real_client(home, on_problem=problems.append)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)
        info = read_note(home)
        assert info is not None

        os.kill(info.pid, signal.SIGKILL)

        await _wait_async(lambda: not client.connected, 5)
        assert await _wait_async(lambda: client.connected, 12)
        assert problems == [], "a broker that is back within a few seconds is not a problem worth a line"
        fresh = read_note(home)
        assert fresh is not None and fresh.pid != info.pid
    finally:
        await client.close()


@pytest.mark.skipif(sys.platform == "win32", reason="an open file cannot be deleted on Windows")
async def test_a_broker_whose_directory_is_wiped_steps_aside_and_the_sessions_find_a_new_one(home: Path):
    client = _real_client(home)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        assert await client.wait_connected(12)
        info = read_note(home)
        assert info is not None

        (home / LOCK_FILE).unlink()
        (home / NOTE_FILE).unlink()

        await _wait_async(lambda: not client.connected, 8)
        assert await _wait_async(lambda: client.connected, 15), client.last_error
        fresh = read_note(home)
        assert fresh is not None and fresh.pid != info.pid
        assert _wait_until(lambda: _pid_gone(info.pid), 5), "the old broker exited"
    finally:
        await client.close()


def _pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_terminating_the_broker_with_sigterm_says_goodbye_and_leaves_nothing_behind(home: Path):
    spawn_broker(home)
    info = _wait_until(lambda: read_note(home))
    assert info is not None

    os.kill(info.pid, signal.SIGTERM)

    assert _wait_until(lambda: _broker_is_gone(home), 8)
    assert "broker exiting" in (home / LOG_FILE).read_text()


def test_a_log_that_has_grown_too_large_is_started_afresh(home: Path):
    home.mkdir(parents=True)
    (home / LOG_FILE).write_bytes(b"x" * (600 * 1024))

    spawn_broker(home)

    assert _wait_until(lambda: read_note(home))
    assert (home / LOG_FILE).stat().st_size < 10_000


# -- a broker left over from before an upgrade ------------------------------------------------------------------


def _age_the_note(home: Path, version: int) -> None:
    """Make the running broker's note say it speaks an older protocol, as the one an upgrade leaves behind does."""
    info = read_note(home)
    assert info is not None
    write_note(home, Note(pid=info.pid, port=info.port, token=info.token, version=version))


async def test_a_session_that_finds_a_broker_of_an_older_protocol_ends_it_and_starts_its_own_at_once(home: Path):
    """The bug: after an upgrade the new session sat on "speaks another protocol, trying again" for as long as the
    old broker had a session connected, which was hours."""
    leftover = _real_client(home)
    leftover.set_session(session(A, "left over"))
    await leftover.start()
    assert await leftover.wait_connected(15), leftover.last_error
    old = read_note(home)
    assert old is not None
    _age_the_note(home, PROTOCOL_VERSION - 1)
    problems: list[str | None] = []
    upgraded = _real_client(home, on_problem=problems.append)
    upgraded.set_session(session(B, "upgraded"))
    try:
        started = time.monotonic()
        await upgraded.start()
        assert await upgraded.wait_connected(20), upgraded.last_error

        fresh = read_note(home)
        assert fresh is not None and fresh.pid != old.pid and fresh.version == PROTOCOL_VERSION
        assert time.monotonic() - started < 15
        assert problems == []
        await _wait_async(lambda: not _pid_alive(old.pid), 5)
        assert not _pid_alive(old.pid), "the older broker is gone"
    finally:
        await upgraded.close()
        await leftover.close()


async def test_a_session_still_connected_to_the_replaced_broker_is_told_and_looks_for_the_next(home: Path):
    leftover = _real_client(home)
    leftover.set_session(session(A, "left over"))
    await leftover.start()
    assert await leftover.wait_connected(15), leftover.last_error
    _age_the_note(home, PROTOCOL_VERSION - 1)
    upgraded = _real_client(home)
    upgraded.set_session(session(B, "upgraded"))
    try:
        await upgraded.start()
        assert await upgraded.wait_connected(20), upgraded.last_error

        # It spoke this version all along (only the note was aged), so once told, it finds the new broker too.
        assert await leftover.wait_connected(20), leftover.last_error
        await eventually(lambda: any(e.session_id == A for e in upgraded.others()), 10)
    finally:
        await upgraded.close()
        await leftover.close()


async def test_a_broker_of_a_newer_protocol_is_left_running_and_reported(home: Path):
    first = _real_client(home)
    first.set_session(session(A, "first"))
    await first.start()
    assert await first.wait_connected(15), first.last_error
    info = read_note(home)
    assert info is not None
    _age_the_note(home, PROTOCOL_VERSION + 1)
    problems: list[str | None] = []
    older = _real_client(home, on_problem=problems.append, incompatible_delay=0.2, problem_after=60)
    older.set_session(session(B, "older"))
    try:
        await older.start()
        await _wait_async(lambda: problems, 10)

        assert problems and "another protocol" in str(problems[0]) and not older.connected
        assert _pid_alive(info.pid), "a newer broker is never ended by an older session"
        assert read_note(home).pid == info.pid  # type: ignore[union-attr]
    finally:
        await older.close()
        await first.close()


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in listing.split()
    listing = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(listing) and not listing.startswith("Z")
