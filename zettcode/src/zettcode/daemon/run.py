"""The background agent itself: one session, one broker connection, and the messages it answers.

It is not a new kind of agent. It is a session with nobody at the keyboard: the SDK client runs it, the broker
delivers what other sessions send, and every message becomes an ordinary relayed turn — stored in the session, and
answered with ``send_message`` if the model chooses to reply. :class:`Daemon` is the loop around that:

* one turn at a time, and up to :data:`MAX_WAITING` messages waiting behind it (the sender is told "busy" beyond
  that), because a model call is not something to run several of at once in one session;
* nobody to ask: the daemon runs at the shell level it was started with (``full`` unless ``spawn`` said otherwise;
  ``ask`` is refused, since there is no reader to answer it), and the ``ask_user`` tool is not offered at all;
* a state file and a heartbeat, so ``daemon list`` can say what it is doing and whether it is still doing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..sdk.types import DIRECT_EMPTY, DIRECT_FAILED, IncomingMessage, Receipt
from .state import Record, Registry, State

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Callable

    from ..sdk.client import Client

#: Messages that may wait behind the turn in progress. A daemon is a colleague, not a queue: beyond this the sender
#: is told it is busy and can try again, rather than its message living somewhere nobody looks.
MAX_WAITING = 4

#: How often the heartbeat is rewritten. A reader calls the record dead when it is older than
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
        name: A label the reader gave this daemon, so ``daemon list`` says what it is for.
        permission: The shell level it runs at: ``deny``, ``safe`` or ``full``. There is nobody to answer ``ask``.
    """

    workspace: Path
    token: str
    session: str | None = None
    model: str | None = None
    effort: str | None = None
    name: str | None = None
    permission: str = "full"


class Daemon:
    """One background agent, held by the process that runs it: its client, its record, its inbox and its log.

    ``serve`` is the whole life of the process: join the broker, say it is idle, answer messages until a signal
    arrives, and take the record away on the way out. Everything else here is one step of that.
    """

    def __init__(self, client: Client, options: Options) -> None:
        """Hold the session ``client`` runs, and the record its folder will hold."""
        self.client = client
        self.options = options
        self.record: Record = Registry().record(options.workspace, client.session.id, create=True)
        self.inbox = Inbox(self._start)
        self.stopping = asyncio.Event()
        #: When this process began, which is what the "for 8m" column counts from.
        self.started_at = time.time()

    # -- the life of the process -------------------------------------------------------------------
    async def serve(self) -> int:
        """Answer messages until the process is asked to stop; return the exit status."""
        _stop_on_signals(self.stopping)
        # Written before the connection is attempted: a start that fails after this point leaves a record the start
        # that made it can recognise as its own and remove, rather than a folder nobody can account for.
        await self.mark("starting")
        if not await self.client.join_sessions(self.inbox.offer, direct=True):
            self.record.log("the session broker is switched off, so no session can reach this daemon")
            self.record.remove()
            return EXIT_UNUSABLE
        await self.mark("idle")
        beating = asyncio.ensure_future(self._beat())
        try:
            await self.stopping.wait()
        finally:
            beating.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beating
            await self.mark("stopping")
            # The record goes with the process: a daemon that stopped cleanly is not an entry a reader has to clean
            # up, and the `kill` that asked it to stop waits for this rather than for a pid, which a zombie still
            # answers.
            self.record.remove()
        return EXIT_OK

    # -- what it answers ---------------------------------------------------------------------------
    def _start(self, message: IncomingMessage) -> None:
        """Begin a turn, and keep the daemon busy until the last waiting message is done."""
        asyncio.ensure_future(self._answer(message))

    async def _answer(self, message: IncomingMessage) -> None:
        """Run one turn, then the next waiting message, and go idle when there is none."""
        try:
            await self.mark("working")
            await self._turn(message)
        finally:
            following = self.inbox.done()
            if following is not None:
                asyncio.ensure_future(self._answer(following))
            else:
                await self.mark("idle")

    async def _turn(self, message: IncomingMessage) -> None:
        """Run one message as a relayed turn, and write how it ended into the log."""
        from ..sdk.errors import RunError

        # No approval handler and no question handler, on purpose. The sandbox (`safe`) is the policy, so a command
        # that stays inside it runs and one that does not is put to a reader — and there is none here, so it is
        # refused. Approving on the daemon's behalf would turn a sandboxed run into a full one with nobody deciding.
        try:
            if message.direct:
                await self._direct(message)
            else:
                async with self.client.session.relay(message) as run:
                    async for event in run:
                        self._see(event)
        except RunError as error:
            self.record.log(f"the turn failed: {error}")
            await self._failed(message, str(error))
        except Exception as error:  # noqa: BLE001 - a broken turn must not take the daemon down
            self.record.log(f"the turn failed: {type(error).__name__}: {error}")
            await self._failed(message, f"{type(error).__name__}: {error}")

    async def _direct(self, message: IncomingMessage) -> None:
        """Run a chat window's text as this session's own prompt: nothing frames it, and the answer goes back to it.

        Nobody at a daemon reads its conversation as it runs, so the window is told how the turn ended: its answer, or
        that it ended without one.
        """
        async with self.client.session.prompt(message.text) as run:
            async for event in run:
                self._see(event)
        answer = run.result.text if run.result is not None else ""
        await self.client.send_back(message, answer if answer.strip() else DIRECT_EMPTY)

    async def _failed(self, message: IncomingMessage, why: str) -> None:
        """Tell a chat window that its turn failed, so it is not left waiting for an answer that will not come."""
        if message.direct:
            await self.client.send_back(message, f"{DIRECT_FAILED}{why}"[:500])

    # -- what it says about itself -----------------------------------------------------------------
    async def mark(self, status: str) -> None:
        """Write the state file, so ``daemon list`` can say what this daemon is doing.

        The heartbeat is touched here as well as on its own clock: the first state a reader can see is written with
        proof of life beside it, so a daemon is never listed as dead between its start and its first beat.
        """
        self.record.beat()
        try:
            self.record.save(
                State(
                    session_id=self.client.session.id,
                    workspace=str(self.options.workspace),
                    pid=os.getpid(),
                    status=status,
                    token=self.options.token,
                    started_at=self.started_at,
                    model=self.client.model.name,
                    effort=self.client.effort,
                    title=self._title(),
                    name=self.options.name,
                    permission=self.options.permission,
                )
            )
        except OSError as error:
            self.record.log(f"the state file could not be written: {error}")

    @property
    def started_seconds(self) -> float:
        """Return how long this daemon has been running."""
        return time.time() - self.started_at

    async def _beat(self) -> None:
        """Keep the heartbeat fresh while this process lives."""
        while True:
            self.record.beat()
            await asyncio.sleep(BEAT_SECONDS)

    def _title(self) -> str | None:
        """Return the session's title, or ``None`` when it has none or cannot be read."""
        try:
            return self.client.session.title
        except Exception:  # noqa: BLE001 - a title is never worth failing a turn over
            return None

    def _see(self, event: Any) -> None:
        """Write the events worth knowing about: a tool's name, and a tool that failed."""
        from ..sdk.events import ToolFinished, ToolStarted

        if isinstance(event, ToolStarted):
            self.record.log(f"tool {event.name}")
        elif isinstance(event, ToolFinished) and not event.ok and not event.skipped:
            self.record.log(f"tool {event.name} failed: {event.output.strip()[:200]}")


async def serve(options: Options) -> int:
    """Run the daemon ``options`` describes until it is stopped, and return the exit status."""
    from ..sdk.errors import ConfigurationError, SessionLockedError, SessionNotFoundError, WorkspaceConflictError

    try:
        client = _client(options)
    except (ConfigurationError, SessionLockedError, SessionNotFoundError, WorkspaceConflictError) as error:
        return _failed(str(error))
    try:
        async with client:
            if options.session is not None:
                try:
                    await client.sessions.open(options.session)
                except (ConfigurationError, SessionNotFoundError, SessionLockedError) as error:
                    return _failed(str(error))
            return await Daemon(client, options).serve()
    except KeyboardInterrupt:
        return EXIT_OK


def _client(options: Options) -> Client:
    """Return the client a daemon runs on: its shell level, reachable, and with nobody to ask.

    Three settings are the daemon's own, whatever the configuration says:

    * ``permission=options.permission`` — chosen when it was started, and ``full`` unless that said otherwise. There
      is no reader here to approve a command, so ``ask`` is refused before a daemon is made: it would only make
      every command fail.
    * ``sessions_enabled=True`` — being messaged is what a daemon is for; without the broker it can do nothing.
    * ``ask_user_enabled=False`` — the ``ask_user`` tool is not offered at all. Declining the question would work
      too, but it would cost the model a turn and teach it that its reader is unavailable, which is not the truth:
      it has no reader.
    """
    from ..sdk.client import Client

    return Client(
        options.workspace,
        model=options.model,
        effort=options.effort,
        permission=options.permission,
        sessions_enabled=True,
        ask_user_enabled=False,
    )
    from ..sdk.client import Client

    return Client(
        options.workspace,
        model=options.model,
        effort=options.effort,
        permission="full",
        sessions_enabled=True,
        ask_user_enabled=False,
    )


def _failed(said: str) -> int:
    """Say why the daemon could not start, where the start that made it can read it."""
    import sys

    sys.stderr.write(f"zettcode daemon: {said}\n")
    sys.stderr.flush()
    return EXIT_UNUSABLE


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
