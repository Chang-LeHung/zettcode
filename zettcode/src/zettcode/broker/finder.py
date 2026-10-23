"""Finding the broker, and starting it when it is not there.

Finding it is a question the operating system answers, not a file: the broker holds a lock for as long as it lives
(:mod:`zettcode.filelock`), so *a held lock means a broker is there* and a free one means there is not, however the
last one died. The note it leaves (:mod:`.files`) says where to connect; a note that outlives its broker is only ever
a connection that is refused. A broker is started only when the lock is free, so a hung broker is reported as hung
instead of being "replaced" by a second one that would just exit.

A broker of another version is not spoken to. An *older* one is ended (only if it is recognised as ZettCode's own, see
:mod:`.process`, and at most a few times per process) and replaced, because it would otherwise stay until its last
session left, which can be hours; a *newer* one is waited for, and never ended, or sessions of two versions would end
each other's brokers in turn for ever.

``websockets`` is imported where it is first used: the shell imports this module with the rest of the application,
and the library is only wanted once there is a broker to talk to.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..filelock import is_held
from . import process
from .files import MODULE, Note, broker_dir, ensure_directory, lock_path, log_path, read_note
from .protocol import MAX_BODY, PROTOCOL_VERSION

#: A broker is started at most this often, so one that dies at once is not restarted in a loop.
SPAWN_INTERVAL = 3.0

#: Seconds between attempts to end the same older broker. Ending it starts a process lookup, which on Windows is a
#: PowerShell call that can be slow or time out under load; a lookup that failed says nothing about the process, so
#: the attempt is made again rather than the broker being left in the way for ever.
REPLACE_RETRY = 2.0

#: How many times one process is asked to end. A pid is not a name, and the note naming it may have been written by
#: anything, so a process that has refused this many times is left alone.
REPLACE_ATTEMPTS = 3

#: The log is cut to nothing when it passes this size as a broker is started.
MAX_LOG = 512 * 1024


def spawn_broker(directory: Path) -> None:
    """Start the broker as a process of its own, detached from this one.

    It must outlive the session that started it (other sessions are using it), so it gets its own session or
    process group, no terminal, and a log file instead of a screen to write to.
    """
    ensure_directory(directory)
    log = log_path(directory)
    try:
        if log.stat().st_size > MAX_LOG:
            log.write_bytes(b"")
    except OSError:
        pass
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "cwd": str(directory), "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined,unused-ignore]
        )
    else:
        options["start_new_session"] = True
    with open(log, "ab") as output:
        subprocess.Popen([sys.executable, "-m", MODULE], stdout=output, stderr=output, **options)  # noqa: S603


class Finder:
    """Opens a WebSocket to the broker, starting one if there is none.

    Args:
        directory: The broker's directory; :func:`~.files.broker_dir` by default, asked at each attempt.
        spawner: Starts a broker when none answers; :func:`spawn_broker` by default, looked up when it is needed so
            that a test can replace it.
        connect_timeout: Seconds to wait for the connection.
        spawn_wait: Seconds to wait for a broker that has just been started.

    Attributes:
        last_error: The last reason an attempt failed, for a person trying to find out why.
        incompatible: A broker is there that speaks another protocol.
    """

    def __init__(
        self,
        *,
        directory: Path | None = None,
        spawner: Callable[[Path], None] | None = None,
        connect_timeout: float = 2.0,
        spawn_wait: float = 5.0,
    ) -> None:
        self.directory = directory
        self.spawner = spawner
        self.connect_timeout = connect_timeout
        self.spawn_wait = spawn_wait
        self.last_error: str | None = None
        self.incompatible = False
        self._last_spawn = float("-inf")
        #: Each process asked to end: how many times, and when the last attempt began. A failed attempt is retried,
        #: but not on every look, and not for ever: the note may name a process that is not ours.
        self._tried: dict[int, tuple[int, float]] = {}

    async def open(self, giving_up: Callable[[], bool]) -> tuple[Any, Note]:
        """Return a connection to the broker and its note, for as long as ``giving_up()`` is false.

        The note is tried first, because trying is cheap and the token makes a wrong guess harmless. Then, for as
        long as it is willing to wait, the lock is asked whether a broker is alive: a free lock means there is none
        and one is started; a held lock means there is one that is starting, busy, stuck or on its way out, and
        starting another would only make a second process that exits. It is asked again each time round, not once,
        because a broker that has just closed its connections still holds the lock for a moment.

        Raises:
            ConnectionError: No broker could be reached, and why.
        """
        directory = self.directory or broker_dir()
        found = await self._try(directory)
        deadline = time.monotonic() + self.spawn_wait
        while found is None and not giving_up():
            if not is_held(lock_path(directory)):
                self._start(directory)
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
            found = await self._try(directory)
        if found is None:
            raise ConnectionError(self.last_error or self._why_not(directory))
        return found

    async def _try(self, directory: Path) -> tuple[Any, Note] | None:
        note = read_note(directory)
        if note is None:
            return None
        if note.version != PROTOCOL_VERSION:
            # Another version's wire is not this one, so there is nothing to say to it. An older broker is ours to
            # end, which is not a protocol to wait on: an attempt that fails is retried with the ordinary backoff,
            # not reported as an incompatibility and then left alone for seconds at a time.
            if note.version < PROTOCOL_VERSION:
                await self._replace(directory, note)
                return None
            # Incompatible only while one is still there in the way: a newer broker that was killed, or a note it
            # left behind, is just an absence, and the start that follows is not a failure to report.
            self.incompatible = is_held(lock_path(directory))
            return None
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus, WebSocketException

        try:
            ws = await connect(
                f"ws://127.0.0.1:{note.port}/inbox",
                additional_headers={"Authorization": f"Bearer {note.token}"},
                proxy=None,  # never through a proxy named in the environment: the broker is on this machine
                compression=None,
                max_size=MAX_BODY,
                open_timeout=self.connect_timeout,
            )
        except InvalidStatus as refused:
            self.last_error = (
                f"the session broker (pid {note.pid}) refused this session (HTTP {refused.response.status_code})"
            )
            return None
        except (OSError, asyncio.TimeoutError, WebSocketException):
            return None
        return ws, note

    def _start(self, directory: Path) -> None:
        """Start a broker, at most once in :data:`SPAWN_INTERVAL`."""
        now = time.monotonic()
        if now - self._last_spawn < SPAWN_INTERVAL:
            return
        self._last_spawn = now
        try:
            (self.spawner or spawn_broker)(directory)
        except OSError as error:
            self.last_error = f"could not start the session broker: {error}"

    def _why_not(self, directory: Path) -> str:
        """Say why no broker could be reached, from what is on disk."""
        note = read_note(directory)
        if is_held(lock_path(directory)):
            if note is not None and note.version > PROTOCOL_VERSION:
                self.incompatible = True
                return (
                    f"the session broker (pid {note.pid}) speaks another protocol and is still serving other sessions"
                )
            if note is not None and note.version < PROTOCOL_VERSION:
                # Ours to end: a failure here is an outage that is being retried, not one this session waits on.
                return f"the session broker (pid {note.pid}) speaks an older protocol and could not be ended yet"
            where = f" (pid {note.pid})" if note is not None else ""
            return f"the session broker{where} is running but does not answer"
        return "no session broker answered"

    async def _replace(self, directory: Path, note: Note) -> None:
        """End an older broker that holds the lock, so that this session can start one of its own.

        The wait for it runs off the loop, because it can take seconds and the session is drawn on it. An attempt
        that did not free the lock is retried: recognising the process can fail for a reason that is not the
        process's own (a command-line lookup that timed out on a busy machine), and one such failure must not leave
        the session reporting an incompatible broker while that broker keeps the next one out.
        """
        lock = lock_path(directory)
        if not is_held(lock):
            return
        attempts, last = self._tried.get(note.pid, (0, float("-inf")))
        if attempts >= REPLACE_ATTEMPTS or time.monotonic() - last < REPLACE_RETRY:
            return
        self._tried[note.pid] = (attempts + 1, time.monotonic())
        await asyncio.to_thread(process.end, note.pid, MODULE, released=lambda: not is_held(lock))
