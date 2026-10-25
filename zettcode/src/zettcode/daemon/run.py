"""The background agent itself: one session, one broker connection, and the messages it answers.

It is not a new kind of agent. It is a session with nobody at the keyboard: the SDK client runs it, the broker
delivers what other sessions send, and every message becomes an ordinary relayed turn — stored in the session, and
answered with ``send_message`` if the model chooses to reply. What this module adds is the loop around that:

* one turn at a time, and up to :data:`MAX_WAITING` messages waiting behind it (the sender is told "busy" beyond
  that), because a model call is not something to run several of at once in one session;
* nobody to ask: the daemon runs the shell permission ``full``, and a question the model asks is declined, since
  there is no reader here to answer it;
* a state file and a heartbeat, so ``daemon list`` can say what it is doing and whether it is still doing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import os
import signal
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..sdk.types import IncomingMessage, Receipt
from .state import State, beat, log_line, remove, session_folder

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Callable

    from ..sdk.client import Client
    from ..sdk.handlers import ApprovalHandler

#: Messages that may wait behind the turn in progress. A daemon is a colleague, not a queue: beyond this the sender
#: is told it is busy and can try again, rather than its message living somewhere nobody looks.
MAX_WAITING = 4

#: How often the heartbeat is rewritten. A reader calls the entry dead when it is older than
#: :data:`~.state.STALE_SECONDS`, so a missed beat or two is tolerated.
BEAT_SECONDS = 5.0

#: Exit statuses, as the daemon's own process reports them.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNUSABLE = 2


class Inbox:
    """The messages a daemon has taken and not yet finished, in the order they arrived.

    The receiver the broker calls runs on the loop and must not block, so it never runs a turn itself: it starts one
    when nothing is running, and queues the message otherwise. The cap is what the sender's agent reads in the
    :class:`Receipt`, so it knows the daemon is busy rather than gone.
    """

    def __init__(self, start: Callable[[IncomingMessage], None], *, limit: int = MAX_WAITING) -> None:
        """Start with nothing running."""
        self._start = start
        self._limit = limit
        self._waiting: deque[IncomingMessage] = deque()
        self._busy = False

    @property
    def busy(self) -> bool:
        """Return whether a turn is running now."""
        return self._busy

    @property
    def waiting(self) -> int:
        """Return how many messages are waiting behind the one running."""
        return len(self._waiting)

    def offer(self, message: IncomingMessage) -> Receipt:
        """Take a message: start it now when nothing runs, hold it when there is room, refuse when there is not."""
        if not self._busy:
            self._busy = True
            self._start(message)
            return Receipt(True, disposition="started")
        if len(self._waiting) < self._limit:
            self._waiting.append(message)
            return Receipt(True, disposition="queued")
        return Receipt(False, f"this daemon already has {self._limit} messages waiting; try again when it is less busy")

    def done(self) -> IncomingMessage | None:
        """Close the turn that ended: return the next message to run, or ``None`` when the daemon is idle again."""
        if self._waiting:
            return self._waiting.popleft()
        self._busy = False
        return None


@dataclass(frozen=True, slots=True)
class Options:
    """What ``zettcode daemon run`` was asked to do.

    Attributes:
        workspace: The directory the session works in.
        token: The word the process that spawned it waits for.
        session: A stored session to continue, or ``None`` for a fresh one.
        model: The model to run on, or ``None`` for the first configured.
        effort: The reasoning level, or ``None`` for the model's own default.
    """

    workspace: Path
    token: str
    session: str | None = None
    model: str | None = None
    effort: str | None = None


async def serve(options: Options) -> int:
    """Run the daemon until it is stopped: answer the messages the broker delivers, one at a time.

    Returns:
        The exit status: 0 when it was stopped, 2 when it could not start at all.
    """
    from ..sdk.client import Client
    from ..sdk.errors import ConfigurationError, SessionLockedError, SessionNotFoundError, WorkspaceConflictError

    try:
        client = Client(
            options.workspace,
            model=options.model,
            effort=options.effort,
            permission="full",
            # A daemon exists to be messaged: the broker connection is not something it can do without, so it is
            # asked for whatever the configuration says. Nothing else about the session changes.
            sessions_enabled=True,
        )
    except (ConfigurationError, SessionLockedError, SessionNotFoundError, WorkspaceConflictError) as error:
        return _failed(str(error))
    try:
        async with client:
            if options.session is not None:
                try:
                    await client.sessions.open(options.session)
                except (ConfigurationError, SessionNotFoundError, SessionLockedError) as error:
                    return _failed(str(error))
            return await _loop(client, options)
    except KeyboardInterrupt:
        return EXIT_OK


def _failed(said: str) -> int:
    """Say why the daemon could not start, where the spawn that started it can read it."""
    import sys

    sys.stderr.write(f"zettcode daemon: {said}\n")
    sys.stderr.flush()
    return EXIT_UNUSABLE


async def _loop(client: Client, options: Options) -> int:
    """Hold the session open and answer messages until the process is asked to stop."""
    from ..sdk.handlers import approve_all

    folder = session_folder(options.workspace, client.session.id, create=True)
    log = _Log(folder)
    stopping = asyncio.Event()
    _stop_on_signals(stopping)
    held = _Held(client, folder, options, log)

    async def run_message(message: IncomingMessage) -> None:
        try:
            await held.mark("working")
            await _turn(client, message, approve_all, log)
        finally:
            following = inbox.done()
            if following is not None:
                asyncio.ensure_future(run_message(following))
            else:
                await held.mark("idle")

    def start(message: IncomingMessage) -> None:
        asyncio.ensure_future(run_message(message))

    inbox = Inbox(start)
    # Written before the connection is attempted: a start that fails after this point leaves a record the spawn that
    # started it can recognise as its own and remove, rather than a folder nobody can account for.
    await held.mark("starting")
    if not await client.join_sessions(inbox.offer):
        log("the session broker is switched off, so no session can reach this daemon")
        remove(folder)
        return EXIT_UNUSABLE
    await held.mark("idle")
    beating = asyncio.ensure_future(_beat(folder))
    try:
        await stopping.wait()
    finally:
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating
        await held.mark("stopping")
        # The record goes with the process: a daemon that stopped cleanly is not an entry a reader has to clean up,
        # and the `kill` that asked it to stop waits for this rather than for a pid, which a zombie still answers.
        remove(folder)
    return EXIT_OK


async def _turn(client: Client, message: IncomingMessage, approve_all: ApprovalHandler, log: _Log) -> None:
    """Run one message as a turn, and write how it ended into the log."""
    from ..sdk.errors import RunError

    try:
        async with client.session.relay(message, on_approval=approve_all) as run:
            async for event in run:
                log.see(event)
    except RunError as error:
        log(f"the turn failed: {error}")
    except Exception as error:  # noqa: BLE001 - a broken turn must not take the daemon down
        log(f"the turn failed: {type(error).__name__}: {error}")


class _Held:
    """What one daemon holds while it runs: its client, its folder and its log."""

    def __init__(self, client: Client, folder: Path, options: Options, log: _Log) -> None:
        self.client = client
        self.folder = folder
        self.options = options
        self.log = log

    async def mark(self, status: str) -> None:
        """Write the state file, so ``daemon list`` can say what this daemon is doing.

        The heartbeat is touched here as well as on its own clock: the first state a reader can see is written with
        proof of life beside it, so a daemon is never listed as dead between its start and its first beat.
        """
        beat(self.folder)
        try:
            State(
                session_id=self.client.session.id,
                workspace=str(self.options.workspace),
                pid=os.getpid(),
                status=status,
                token=self.options.token,
                started_at=self.log.started_at,
                model=self.client.model.name,
                effort=self.client.effort,
                title=self._title(),
            ).write(self.folder)
        except OSError as error:
            self.log(f"the state file could not be written: {error}")

    def _title(self) -> str | None:
        """Return the session's title, or ``None`` when it has none or cannot be read."""
        try:
            return self.client.session.title
        except Exception:  # noqa: BLE001 - a title is never worth failing a turn over
            return None


async def _beat(folder: Path) -> None:
    """Keep the heartbeat fresh while this process lives."""
    while True:
        beat(folder)
        await asyncio.sleep(BEAT_SECONDS)


class _Log:
    """The daemon's log: the errors and the tool calls, in the folder of its session."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.started_at = time.time()

    def __call__(self, text: str) -> None:
        log_line(self.folder, text)

    def see(self, event: Any) -> None:
        """Write the events worth knowing about: a tool's name, and a tool that failed."""
        from ..sdk.events import ToolFinished, ToolStarted

        if isinstance(event, ToolStarted):
            self(f"tool {event.name}")
        elif isinstance(event, ToolFinished) and not event.ok and not event.skipped:
            self(f"tool {event.name} failed: {event.output.strip()[:200]}")


def _stop_on_signals(stopping: asyncio.Event) -> None:
    """Stop on SIGTERM and SIGINT, on either platform."""
    loop = asyncio.get_running_loop()
    for number in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGBREAK", None)):
        if number is None:
            continue
        try:
            loop.add_signal_handler(number, stopping.set)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows: no loop-level handlers for these. A plain handler still stops an idle daemon.
            with contextlib.suppress(ValueError, OSError, RuntimeError):
                signal.signal(number, lambda *_: stopping.set())


def started_at_text(seconds: float) -> str:
    """Say when a daemon started, in the local time a reader reads."""
    return datetime.datetime.fromtimestamp(seconds).strftime("%H:%M")
