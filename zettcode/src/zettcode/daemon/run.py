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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..error_text import may_pass
from ..sdk.types import DIRECT_EMPTY, DIRECT_FAILED, IncomingMessage, Receipt
from .state import Record, Registry, State

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Callable

    from ..sdk.client import Client

#: Messages that may wait behind the turn in progress. A daemon is a colleague, not a queue: beyond this the sender
#: is told it is busy and can try again, rather than its message living somewhere nobody looks.
MAX_WAITING = 4

#: How many times a turn that failed in a way that may pass is tried again, and how long to wait before each try.
#: The retry continues the interrupted request; a failure that would fail again is not retried at all.
TURN_RETRIES = 3
RETRY_DELAYS = (1.0, 2.0, 4.0)

#: How often the heartbeat is rewritten. A reader calls the record dead when it is older than
#: :data:`~.state.STALE_SECONDS`, so a missed beat or two is tolerated.
BEAT_SECONDS = 5.0

#: Exit statuses, as the daemon's own process reports them.
EXIT_OK = 0
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
        title: What to call the session, when the reader named it at the start; ``None`` lets it name itself.
        permission: The shell level it runs at: ``deny``, ``safe`` or ``full``. There is nobody to answer ``ask``.
    """

    workspace: Path
    token: str
    session: str | None = None
    model: str | None = None
    effort: str | None = None
    name: str | None = None
    title: str | None = None
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
        #: How often this process has asked the model for a title. A session the model cannot name is left unnamed
        #: rather than costing a call at the end of every turn.
        self._naming_attempts = 0

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
            await self._apply_requests()
            await self.mark("working")
            await self._turn(message)
            await self._name_it()
        finally:
            following = self.inbox.done()
            if following is not None:
                asyncio.ensure_future(self._answer(following))
            else:
                await self.mark("idle")

    async def _apply_requests(self) -> None:
        """Put a model or effort a reader asked for in force, then clear the request.

        ``daemon update --model/--effort`` writes the request into the record, so the reader does not have to reach
        this process; the beat tries it too, so a change lands without waiting for a message. The request is cleared
        once tried — a model this configuration does not have would otherwise be attempted at every turn — and why
        it could not be met is left in the record for ``daemon list`` to show. Clearing is by value: a request the
        reader replaced while this one was being applied is kept for the next try.
        """
        state = State.load(self.record.folder)
        if state is None or (state.requested_model is None and state.requested_effort is None):
            return
        wanted_model, wanted_effort = state.requested_model, state.requested_effort
        failure: str | None = None
        try:
            if wanted_model is not None:
                self.client.use_model(wanted_model)
            if wanted_effort is not None:
                self.client.use_effort(wanted_effort)
        except Exception as error:  # noqa: BLE001 - a request that cannot be met leaves the daemon working
            failure = f"{type(error).__name__}: {error}"
            self.record.log(f"the requested model or effort could not be applied: {failure}")
        else:
            self.record.log(f"now running {self.client.model.name} · effort {self.client.effort}")

        def applied(current: State | None) -> State:
            base = current or state
            clears_model = base.requested_model == wanted_model
            clears_effort = base.requested_effort == wanted_effort
            return replace(
                base,
                requested_model=None if clears_model else base.requested_model,
                requested_effort=None if clears_effort else base.requested_effort,
                # A request the reader replaced while this one was being applied has not failed: the error is about
                # the request that was tried, so it is written only when that one is the one left in the record.
                requested_error=failure if clears_model and clears_effort else base.requested_error,
                model=self.client.model.name,
                effort=self.client.effort,
                context_window=self._window(),
            )

        try:
            self.record.change(applied, wait=0)
        except OSError as error:
            self.record.log(f"the applied request could not be cleared: {error}")

    async def _turn(self, message: IncomingMessage) -> None:
        """Run one message, trying again when the failure may pass, and tell the sender if it still fails.

        A failure the provider may recover from — a timeout, a dropped connection, a rate limit, a server error —
        is tried again up to :data:`TURN_RETRIES` times. The retry continues the interrupted request rather than
        sending the prompt over: the library tells the model which tools were cut short and lets it decide, so a
        tool is never run twice on its own. A failure that would fail again is not retried. Either way the sender is
        told how the turn ended when it can be reached, so an agent that asked is not left waiting for an answer
        that will not come.
        """
        from ..sdk.errors import RunError

        # No approval handler and no question handler, on purpose. The sandbox (`safe`) is the policy, so a command
        # that stays inside it runs and one that does not is put to a reader — and there is none here, so it is
        # refused. Approving on the daemon's behalf would turn a sandboxed run into a full one with nobody deciding.
        why = ""
        answer: str | None = None
        succeeded = False
        for attempt in range(TURN_RETRIES + 1):
            try:
                if attempt == 0:
                    await self._once(message)
                else:
                    try:
                        if await self.client.session.resumable() is None:
                            # The conversation has nothing interrupted to pick up, so there is no request to
                            # continue; sending the prompt again is not what this loop does.
                            self.record.log("the turn is not retried: there is no interrupted request to continue")
                            break
                        answer = await self._resume()
                    except RunError:
                        # The continued request failed again: that is the turn failing, counted like any other.
                        raise
                    except Exception as error:  # noqa: BLE001 - the turn's own failure is what is reported
                        self.record.log(f"the turn could not be continued: {type(error).__name__}: {error}")
                        break
                succeeded = True
                break
            except RunError as error:
                why = str(error)
                retryable = error.retryable
            except Exception as error:  # noqa: BLE001 - a broken turn must not take the daemon down
                why = f"{type(error).__name__}: {error}"
                retryable = may_pass(error)
            self.record.log(f"the turn failed (attempt {attempt + 1} of {TURN_RETRIES + 1}): {why}")
            if not retryable:
                self.record.log("the turn is not retried: this failure would happen again")
                break
            if attempt == TURN_RETRIES:
                self.record.log(f"the turn failed after {TURN_RETRIES + 1} attempts")
                break
            await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
        if not succeeded:
            await self._failed(message, why or "the turn failed")
            return
        if message.direct and answer is not None:
            # The first attempt answered the window itself; a continued one must do it too, or the window waits
            # for a turn that has already finished. Delivering it outside the retry loop keeps a send failure
            # from being taken for a turn failure and continued a second time.
            await self._tell(message, answer if answer.strip() else DIRECT_EMPTY, what="how the continued turn ended")

    async def _once(self, message: IncomingMessage) -> None:
        """Run the message once: as this session's own prompt when it is direct, and as a relayed turn otherwise."""
        if message.direct:
            await self._direct(message)
            return
        async with self.client.session.relay(message) as run:
            async for event in run:
                self._see(event)

    async def _resume(self) -> str:
        """Pick up the request that failed where it stopped, so nobody's prompt is sent a second time."""
        async with self.client.session.resume_stream() as run:
            async for event in run:
                self._see(event)
        return run.result.text if run.result is not None else ""

    async def _direct(self, message: IncomingMessage) -> None:
        """Run a chat window's text as this session's own prompt: nothing frames it, and the answer goes back to it.

        Nobody at a daemon reads its conversation as it runs, so the window is told how the turn ended: its answer, or
        that it ended without one.
        """
        async with self.client.session.prompt(message.text) as run:
            async for event in run:
                self._see(event)
        answer = run.result.text if run.result is not None else ""
        await self._tell(message, answer if answer.strip() else DIRECT_EMPTY, what="how the turn ended")

    async def _failed(self, message: IncomingMessage, why: str) -> None:
        """Tell the sender that its turn failed, so it is not left waiting for an answer that will not come.

        A sender with no session to answer — ``daemon prompt`` speaks as an external name — cannot be told; the
        reason is left in the log, which is the only place it can be read afterwards.
        """
        await self._tell(message, f"{DIRECT_FAILED}{why}"[:500], what=f"the turn failed: {why}")

    async def _tell(self, message: IncomingMessage, text: str, *, what: str) -> None:
        """Send a line back to the sender, and leave the fact in the log when there is nobody to receive it."""
        delivered = await self.client.send_back(message, text)
        if delivered is None:
            self.record.log(f"the sender could not be told {what}")

    async def _name_it(self) -> None:
        """Ask the model for a title from the first exchange, unless the session has one.

        A daemon has no reader to name its conversation, and what it is called is how the reader finds it again in
        ``/resume``; the record's title is the session's, so the next mark carries it. Naming is a nicety: a model
        that cannot name the session leaves it unnamed (twice is enough to try), and the turn is not failed for it.
        """
        if self._title() is not None or self._naming_attempts >= 2:
            return
        self._naming_attempts += 1
        try:
            await self.client.session.name_it()
        except Exception as error:  # noqa: BLE001 - a title is never worth failing a turn over
            self.record.log(f"the session could not be named: {type(error).__name__}: {error}")

    # -- what it says about itself -----------------------------------------------------------------
    async def mark(self, status: str) -> None:
        """Write the state file, so ``daemon list`` can say what this daemon is doing, and what it has spent.

        The heartbeat is touched here as well as on its own clock: the first state a reader can see is written with
        proof of life beside it, so a daemon is never listed as dead between its start and its first beat.
        """
        self.record.beat()
        sent, made, context = self._spend()
        state = State(
            session_id=self.client.session.id,
            workspace=str(self.options.workspace),
            pid=os.getpid(),
            status=status,
            token=self.options.token,
            started_at=self.started_at,
            model=self.client.model.name,
            effort=self.client.effort,
            title=self._title(),
            name=self.options.name,  # replaced inside the lock by the label the record already holds
            permission=self.options.permission,
            input_tokens=sent,
            output_tokens=made,
            context_tokens=context,
            context_window=self._window(),
            broker=self._connected(),
        )
        # The lock is tried, not waited for: this runs on the event loop, and a reader changing a label holds it for
        # a moment. A write that missed is made by the next mark — the turn did not fail for it.
        for attempt in range(3):
            try:
                self.record.change(
                    lambda current: replace(
                        state,
                        name=self._label(current),
                        requested_model=current.requested_model if current is not None else None,
                        requested_effort=current.requested_effort if current is not None else None,
                        requested_error=current.requested_error if current is not None else None,
                    ),
                    wait=0,
                )
                return
            except OSError as error:
                if attempt == 2:
                    self.record.log(f"the state file could not be written: {error}")
                    return
                await asyncio.sleep(0.02)

    def _spend(self) -> tuple[int | None, int | None, int | None]:
        """Return what the session has sent and generated, and how full the context was, when that is known."""
        try:
            usage = self.client.usage
        except Exception:  # noqa: BLE001 - counters are a nicety beside the status a reader needs
            return None, None, None
        return usage.input_tokens, usage.output_tokens, usage.context_tokens

    def _window(self) -> int | None:
        """Return the window of the model in use, or ``None`` when it cannot be read.

        The counters are a nicety; a client that cannot answer must not take the state write, and with it the turn
        loop, down. ``_spend`` does the same for what it reads.
        """
        try:
            return self.client.model.context_window
        except Exception:  # noqa: BLE001 - see above
            return None

    def _connected(self) -> bool | None:
        """Return whether the session broker is reachable now, or ``None`` when the client cannot say."""
        try:
            return self.client.reachable
        except Exception:  # noqa: BLE001 - connectivity is a nicety beside the status a reader needs
            return None

    async def _note_connection(self) -> None:
        """Record a change in whether the session broker is reachable, so ``list`` shows a daemon nobody can reach.

        A broker this session cannot register with — another protocol, a refused token — leaves the process healthy
        and idle, which is indistinguishable from a reachable daemon in the record unless this is written down.
        """
        connected = self._connected()
        if connected is None:
            return
        current = State.load(self.record.folder)
        if current is None or current.broker is connected:
            return
        try:
            self.record.change(lambda state: replace(state or current, broker=connected), wait=0)
        except OSError as error:
            self.record.log(f"the connection could not be recorded: {error}")

    async def _beat(self) -> None:
        """Keep the heartbeat fresh while this process lives, and take up a setting a reader asked for.

        A request is applied between turns: a run in progress already holds the model and the level it started with,
        and swapping them under it would change the compression it is halfway through.
        """
        while True:
            self.record.beat()
            if not self.inbox.busy:
                await self._apply_requests()
            await self._note_connection()
            await asyncio.sleep(BEAT_SECONDS)

    def _title(self) -> str | None:
        """Return the session's title, or ``None`` when it has none or cannot be read."""
        try:
            return self.client.session.title
        except Exception:  # noqa: BLE001 - a title is never worth failing a turn over
            return None

    def _label(self, current: State | None) -> str | None:
        """Return this daemon's label: the one it was started with, or the one a reader set in the record since.

        ``daemon update --name`` writes the record of a running daemon too, so when the state read inside the lock
        is this daemon's own, its label is the answer; a record another run left behind is not.
        """
        if current is not None and current.session_id == self.client.session.id and current.token == self.options.token:
            return current.name
        return self.options.name

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
            if options.title:
                # The session this process holds, so the name is written where the daemon and `/resume` both read it.
                try:
                    await client.session.rename(options.title)
                except (OSError, ValueError, SessionLockedError) as error:
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
