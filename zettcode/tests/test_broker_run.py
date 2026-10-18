"""The broker as a process runs it: taking the lock, announcing itself, and noticing when its files are tampered with."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

from broker_helpers import RawPeer, eventually
from zettcode.broker.files import LOCK_FILE, NOTE_FILE, Note, read_note, write_note
from zettcode.broker.protocol import PROTOCOL_VERSION
from zettcode.broker.runner import run
from zettcode.filelock import SingletonLock, is_held


@pytest.fixture
async def runs(tmp_path: Path):
    """Start brokers on the temporary directory and make sure none outlives the test."""
    tasks: list[asyncio.Task[int]] = []

    def start(**options) -> asyncio.Task[int]:
        options.setdefault("idle_exit", 60)
        options.setdefault("watch_interval", 0.05)
        task = asyncio.ensure_future(run(tmp_path, **options))
        tasks.append(task)
        return task

    start.directory = tmp_path  # type: ignore[attr-defined]
    yield start
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def announced(directory: Path) -> Note:
    return await eventually(lambda: read_note(directory), 3)


async def test_a_broker_takes_the_lock_announces_itself_and_serves(runs):
    runs()

    info = await announced(runs.directory)

    assert info.pid == os.getpid() and info.version == PROTOCOL_VERSION
    assert is_held(runs.directory / LOCK_FILE)
    peer = await RawPeer.connect(info.port, token=info.token)
    try:
        assert "error" not in await peer.register("s1", "serving")
    finally:
        await peer.close()


async def test_an_idle_broker_leaves_cleanly_with_nothing_behind(runs):
    task = runs(idle_exit=0.2)
    await announced(runs.directory)

    assert await asyncio.wait_for(task, 3) == 0

    assert read_note(runs.directory) is None and not (runs.directory / NOTE_FILE).exists()
    assert is_held(runs.directory / LOCK_FILE) is False


async def test_a_second_broker_finds_the_first_and_leaves_it_alone(runs, capfd):
    runs()
    first = await announced(runs.directory)

    second = runs()

    assert await asyncio.wait_for(second, 3) == 0
    assert read_note(runs.directory) == first, "the first broker's note is untouched"
    assert "another broker is already running" in capfd.readouterr().err


async def test_a_note_left_by_a_broker_that_died_is_replaced_at_start(runs):
    write_note(runs.directory, Note(pid=1, port=1, token="stale", version=PROTOCOL_VERSION))

    runs()
    info = await eventually(lambda: (i := read_note(runs.directory)) is not None and i.token != "stale" and i)

    assert info.port != 1 and info.pid == os.getpid()


async def test_a_broker_that_cannot_listen_says_so_frees_the_lock_and_leaves_no_note(runs, capfd):
    blocker = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = blocker.sockets[0].getsockname()[1]
    try:
        task = runs(port=port)

        assert await asyncio.wait_for(task, 3) == 1
    finally:
        blocker.close()
        await blocker.wait_closed()

    assert read_note(runs.directory) is None
    assert is_held(runs.directory / LOCK_FILE) is False
    assert "could not start" in capfd.readouterr().err


async def test_a_broker_that_arrives_while_a_session_is_glancing_at_the_lock_still_starts(runs):
    glance = SingletonLock(runs.directory / LOCK_FILE)
    assert glance.acquire()
    threading.Timer(
        0.1, glance.release
    ).start()  # a thread: the broker's wait blocks this loop, as it would in its own process

    runs()

    info = await announced(runs.directory)
    assert info.pid == os.getpid()


async def test_the_directory_it_makes_is_private(runs):
    target = runs.directory / "nested"
    task = asyncio.ensure_future(run(target, idle_exit=60, watch_interval=0.05))
    try:
        await announced(target)
        if sys.platform != "win32":
            assert (target.stat().st_mode & 0o777) == 0o700
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# -- when somebody tidies the directory by hand -----------------------------------------------------------------


async def test_a_broker_whose_note_is_deleted_writes_it_again_so_new_sessions_can_find_it(runs, capfd):
    runs()
    info = await announced(runs.directory)

    (runs.directory / NOTE_FILE).unlink()

    again = await announced(runs.directory)
    assert again.token == info.token and again.port == info.port
    assert "note was removed" in capfd.readouterr().err


async def test_a_note_that_another_token_overwrote_is_put_back(runs):
    runs()
    info = await announced(runs.directory)

    write_note(runs.directory, Note(pid=1, port=1, token="intruder", version=PROTOCOL_VERSION))

    await eventually(lambda: (i := read_note(runs.directory)) is not None and i.token == info.token)


@pytest.mark.skipif(sys.platform == "win32", reason="an open file cannot be deleted on Windows")
async def test_a_broker_whose_lock_file_was_deleted_steps_aside_so_there_is_never_a_second(runs, capfd):
    task = runs()
    await announced(runs.directory)

    (runs.directory / LOCK_FILE).unlink()

    assert await asyncio.wait_for(task, 3) == 0
    assert "stepping aside" in capfd.readouterr().err
    replacement = runs()
    info = await eventually(lambda: read_note(runs.directory))
    assert info is not None and not replacement.done(), "a new broker takes over cleanly"


@pytest.mark.skipif(sys.platform == "win32", reason="an open file cannot be deleted on Windows")
async def test_the_sessions_of_a_broker_that_stepped_aside_are_told_so(runs):
    task = runs()
    info = await announced(runs.directory)
    peer = await RawPeer.connect(info.port, token=info.token)
    try:
        (runs.directory / LOCK_FILE).unlink()
        await asyncio.wait_for(task, 3)

        assert await peer.ended(3)
    finally:
        await peer.close()
