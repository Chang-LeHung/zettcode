"""What a session uses to reach the broker: stay connected, say what this session is, send and receive.

It opens the session's WebSocket (which is what registers it), tells the broker what the session is now (and again
after every reconnection, so the broker always hears the latest and never an old value), keeps the roster the broker
pushes, hands each message that arrives to the shell, and sends the shell's messages with a plain ``POST /messages``
(see :mod:`.protocol`). Finding the broker, and starting it, is :mod:`.finder`'s.

The client lives on the shell's event loop and never blocks it. Nothing it does can fail the session: every error
ends as an unconnected client, or as a :class:`~.models.SendError` the caller reports. Delivery is at most once: a send
that was in flight when the connection ended fails with a reason that says the message may or may not have arrived,
and nothing is retried behind the caller's back.

When the connection ends it is made again: at once when the broker closed it with code 1012 (its way of saying it is
going away), after a growing delay otherwise, and slowly while the broker speaks a newer protocol than this client.

``httpx`` and ``websockets`` are imported where they are first used, because the shell imports this module with the
rest of the application and they are only wanted once there is a broker to talk to.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..modes import MODE_FOLLOWUP, MODE_STEER, MODES
from .finder import Finder
from .models import Delivered, Incoming, Receipt, RosterEntry, SendError, SessionInfo
from .protocol import (
    ACK_TIMEOUT,
    PROTOCOL_VERSION,
    VIA_AGENT,
    VIA_USER,
    VIAS,
    Limits,
    PeerInfo,
    Refused,
    roster_from_wire,
)
from .text import clean_text

#: What the broker closes a connection with when it is going away (WebSocket's "service restart").
GOODBYE = 1012

#: Seconds to wait for the broker's answer to anything but a send: the greeting, and the description of this session.
REQUEST_TIMEOUT = 5.0

#: Seconds between attempts to reach the broker, growing to the last one.
BACKOFF = (0.2, 0.5, 1.0, 2.0, 5.0)

#: Seconds between attempts while the broker speaks a newer protocol than this client can, which is the only case
#: that is waited out: an older one is ended and replaced. Looking costs one file read, so this is short.
INCOMPATIBLE_DELAY = 5.0

#: Seconds the broker may have been out of reach before the client says so.
PROBLEM_AFTER = 8.0


class _Outage:
    """Says, once, that the broker has been out of reach for a while, and once that it is back.

    Args:
        tell: Told the sentence, or ``None`` when the broker is back.
        after: Seconds out of reach before it speaks, unless the broker is there but cannot be spoken to.
    """

    def __init__(self, tell: Callable[[str | None], None] | None, after: float) -> None:
        self.tell = tell
        self._after = after
        self._since: float | None = None
        self._said: str | None = None

    def failed(self, reason: str, *, at_once: bool) -> None:
        now = time.monotonic()
        if self._since is None:
            self._since = now
        if now - self._since < self._after and not at_once:
            return
        if reason != self._said:
            self._said = reason
            self._speak(reason)

    def recovered(self) -> None:
        self._since = None
        if self._said is not None:
            self._said = None
            self._speak(None)

    def _speak(self, message: str | None) -> None:
        if self.tell is not None:
            with contextlib.suppress(Exception):
                self.tell(message)


class BrokerClient:
    """A session's connection to the broker.

    Args:
        on_message: Called, on the event loop, with each :class:`~.models.Incoming`; returns the
            :class:`~.models.Receipt` that is sent back. It must not block. An exception becomes a refusal.
        on_roster: Called with the roster each time it changes, and with an empty one when the connection is lost.
        on_conflict: Called with a sentence when the broker refuses this session's registration because another
            process holds it, and with ``None`` when that is no longer so.
        on_problem: Called once with a sentence when the broker has been out of reach for ``problem_after``
            seconds (or speaks another protocol), and with ``None`` when the connection is back.
        directory: The broker's directory; :func:`~.files.broker_dir` by default.
        spawner: Starts a broker when none answers; see :class:`~.finder.Finder`.
        reply_timeout: Seconds to wait for the answer to a send.
        request_timeout: Seconds to wait for the broker's answer to anything else.
        connect_timeout: Seconds to wait for a connection.
        spawn_wait: Seconds to wait for a broker that has just been started.
        backoff: Seconds to wait between attempts, growing.
        problem_after: Seconds out of reach before ``on_problem`` is told.
        incompatible_delay: Seconds between attempts while the broker speaks a newer protocol.
    """

    def __init__(
        self,
        *,
        on_message: Callable[[Incoming], Receipt] | None = None,
        on_roster: Callable[[tuple[PeerInfo, ...]], None] | None = None,
        on_conflict: Callable[[str | None], None] | None = None,
        on_problem: Callable[[str | None], None] | None = None,
        directory: Path | None = None,
        spawner: Callable[[Path], None] | None = None,
        reply_timeout: float = ACK_TIMEOUT + 5.0,
        request_timeout: float = REQUEST_TIMEOUT,
        connect_timeout: float = 2.0,
        spawn_wait: float = 5.0,
        backoff: tuple[float, ...] = BACKOFF,
        problem_after: float = PROBLEM_AFTER,
        incompatible_delay: float = INCOMPATIBLE_DELAY,
    ) -> None:
        self.on_message = on_message
        self.on_roster = on_roster
        #: Called, on the loop, with the id of a watched session and one thing its turn said (see ``STREAM_TYPES``).
        self.on_stream: Callable[[str, dict[str, Any]], None] | None = None
        self.on_conflict = on_conflict
        self.reply_timeout = reply_timeout
        self.request_timeout = request_timeout
        self.backoff = backoff
        self.incompatible_delay = incompatible_delay
        #: What the broker said it accepts, once connected.
        self.limits = Limits()
        self._finder = Finder(
            directory=directory, spawner=spawner, connect_timeout=connect_timeout, spawn_wait=spawn_wait
        )
        self._outage = _Outage(on_problem, problem_after)
        self._session: SessionInfo | None = None
        self._roster: tuple[PeerInfo, ...] = ()
        self._conflict: str | None = None
        # The connection that is up, if any.
        self._ws: Any = None
        self._http: Any = None
        self._connected = False
        #: Whether anybody watches this session's turns: the broker says so, and until it does nothing is streamed.
        self._watched = False
        self._watching: set[str] = set()
        self._outbox: deque[str] = deque(maxlen=512)
        self._asks: deque[tuple[str, str]] = deque()
        self._asker: asyncio.Task[None] | None = None
        self._streamer: asyncio.Task[None] | None = None
        self._goodbye = False
        self._came_up = asyncio.Event()
        # Asking the broker something over the WebSocket and waiting for its answer.
        self._replies: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._numbers = itertools.count(1)
        # Telling the broker what this session is.
        self._dirty = False
        self._pusher: asyncio.Task[None] | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._closing = False

    # -- what the shell asks ----------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        """Return whether this session is connected to a broker right now."""
        return self._connected

    @property
    def on_problem(self) -> Callable[[str | None], None] | None:
        """Told once when the broker has been out of reach for a while, and again when it is back."""
        return self._outage.tell

    @on_problem.setter
    def on_problem(self, tell: Callable[[str | None], None] | None) -> None:
        self._outage.tell = tell

    @property
    def last_error(self) -> str | None:
        """Return the last reason a connection attempt failed, for a person trying to find out why."""
        return self._finder.last_error

    @property
    def roster(self) -> tuple[PeerInfo, ...]:
        """Return every registered session, this one included, as of the last update."""
        return self._roster

    @property
    def session(self) -> SessionInfo | None:
        """Return what this session has told the broker, or will when it connects."""
        return self._session

    @property
    def conflict(self) -> str | None:
        """Return why registration was refused, or ``None``."""
        return self._conflict

    def others(self) -> tuple[PeerInfo, ...]:
        """Return the sessions that are not this one."""
        mine = self._session.session_id if self._session is not None else None
        return tuple(entry for entry in self._roster if entry.session_id != mine)

    # -- watching a turn --------------------------------------------------------------------------
    @property
    def watched(self) -> bool:
        """Return whether anybody is watching this session's turns right now."""
        return self._watched and self._connected

    def watch(self, session_id: str) -> None:
        """Ask to be told what a session's turns say, as they happen. Kept across a lost connection."""
        if session_id in self._watching:
            return
        self._watching.add(session_id)
        self._ask("watch", session_id)

    def unwatch(self, session_id: str) -> None:
        """Stop watching a session."""
        if session_id in self._watching:
            self._watching.discard(session_id)
            self._ask("unwatch", session_id)

    def _ask(self, op: str, session_id: str) -> None:
        """Ask the broker to ``watch`` or ``unwatch`` a session, one request after another in the order they were made.

        A ``watch`` the broker refuses (it caps what a connection watches) is forgotten rather than kept, so what this
        client believes it watches is what the broker does. Nothing is sent while disconnected: the connection that
        follows asks for every session still wanted.
        """
        if not self._connected:
            return
        self._asks.append((op, session_id))
        if self._asker is None or self._asker.done():
            self._asker = asyncio.ensure_future(self._ask_all())

    async def _ask_all(self) -> None:
        while self._asks:
            op, session_id = self._asks.popleft()
            try:
                await self._tell({"op": op, "session_id": session_id})
            except Refused:
                if op == "watch":
                    self._watching.discard(session_id)
            except Exception:  # noqa: BLE001 - a lost connection: what is still wanted is asked for on the next one
                self._asks.clear()
                return

    def publish(self, event: dict[str, Any]) -> None:
        """Say one thing about this session's turn to whoever watches it; nothing is sent when nobody does."""
        if self.watched:
            self._say({"op": "stream", "event": event})

    def _say(self, line: dict[str, Any]) -> None:
        """Send a line that expects no answer, in the order given. A connection that is down loses it."""
        if not self._connected:
            return
        self._outbox.append(json.dumps(line))
        if self._streamer is None or self._streamer.done():
            self._streamer = asyncio.ensure_future(self._pump())

    async def _pump(self) -> None:
        """Send what is queued, one line after another, until there is nothing."""
        while self._outbox and (ws := self._ws) is not None:
            try:
                await ws.send(self._outbox.popleft())
            except Exception:  # noqa: BLE001 - a lost connection: what was watched is asked for again on the next
                return

    def set_session(self, info: SessionInfo | None) -> None:
        """Say what this session is now: a new id, a new title, a new status.

        Safe to call at any time and from the loop only. While disconnected it is remembered and sent on
        connecting, so the broker always hears the latest and never an old value.
        """
        self._session = info
        self._schedule_push()

    async def start(self) -> None:
        """Begin connecting in the background; returns at once."""
        if self._supervisor is None and not self._closing:
            self._supervisor = asyncio.ensure_future(self._supervise())

    async def wait_connected(self, timeout: float) -> bool:
        """Wait until connected, for at most ``timeout`` seconds; used by tests and by callers that must know."""
        if not self._connected:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._came_up.wait(), timeout)
        return self._connected

    async def close(self) -> None:
        """Disconnect and stop trying. Quick, idempotent, and never raises."""
        self._closing = True
        for task in (self._pusher, self._supervisor, self._asker):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._pusher = self._supervisor = self._asker = None
        ws, http = self._ws, self._http
        self._drop()
        if http is not None:
            with contextlib.suppress(Exception):
                await http.aclose()
        if ws is not None:
            # Closing is waited for, briefly: it is what makes the broker see the connection end now and not
            # whenever the loop next turns, which at exit is never.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), 0.5)

    # -- sending ----------------------------------------------------------------------------------
    async def send(
        self, to: str, text: str, *, hops: int = 0, via: str = VIA_AGENT, direct: bool = False, mode: str = MODE_STEER
    ) -> Delivered:
        """Send a message to another session and return once it has taken it.

        Args:
            to: The session's handle or id.
            text: What to say.
            hops: How many sessions it has passed through already.
            via: How it came: the reader, the agent, or an external program.
            direct: Ask a session that can to run it as its own reader's prompt and answer the sender.
            mode: What a busy recipient does with it: ``"steer"`` (the default) hands it to the running request,
                ``"followup"`` waits until that request ends.

        Raises:
            SendError: There is no broker, or the broker or the recipient refused, or nobody answered in time, or
                the connection was lost with the message in flight.
        """
        import httpx

        http = self._http if self._connected else None
        if http is None:
            raise SendError("offline", "not connected to the session broker")
        if mode not in MODES:
            raise SendError("invalid", "mode is 'steer' or 'followup'")
        cleaned = clean_text(text)
        if not cleaned.strip():
            raise SendError("empty", "a message needs some text")
        if len(cleaned) > self.limits.max_text:
            raise SendError("too_long", f"a message is limited to {self.limits.max_text} characters")
        await self._registered()
        try:
            response = await http.post(
                "/messages",
                json={
                    "to": to,
                    "text": cleaned,
                    "via": via,
                    "hops": hops,
                    "mode": mode,
                    **({"direct": True} if direct else {}),
                },
                timeout=self.reply_timeout,
            )
        except httpx.TimeoutException:
            raise SendError(
                "timeout", "the session broker did not answer in time; the message may or may not have been delivered"
            ) from None
        except httpx.HTTPError:
            raise SendError(
                "lost", "the connection to the session broker was lost; the message may or may not have been delivered"
            ) from None
        return self._delivered(response)

    @staticmethod
    def _delivered(response: Any) -> Delivered:
        """Read the broker's answer to a send: who took the message, or why it did not."""
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            refused = Refused.from_wire(body.get("error") if isinstance(body, dict) else None)
            raise SendError(refused.reason, str(refused))
        recipient = PeerInfo.from_wire(body.get("to"))
        if recipient is None:
            raise SendError("internal", "the broker's answer did not say who took the message")
        disposition = body.get("disposition")
        return Delivered(recipient, disposition if isinstance(disposition, str) else "", body.get("direct") is True)

    async def _registered(self) -> None:
        """Wait, for a moment, until the broker has been told about this session.

        A connection is usable the moment the broker has greeted it, which is before the session has been described
        to it; a send in that gap would be refused for having no session. The wait is bounded and a failure of it is
        not this call's to report: the send that follows gets the broker's own answer.
        """
        pusher = self._pusher
        if pusher is not None and not pusher.done():
            with contextlib.suppress(Exception):  # the send that follows gets the broker's own answer
                await asyncio.wait_for(asyncio.shield(pusher), self.request_timeout)

    # -- staying connected ------------------------------------------------------------------------
    async def _supervise(self) -> None:
        """Stay connected: connect, serve until the connection ends, wait a little, again."""
        failures = 0
        while not self._closing:
            self._goodbye = False
            try:
                served = await self._serve_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a broker problem must never become its session's
                served = False
                self._finder.last_error = (
                    str(error) if isinstance(error, ConnectionError) else f"{type(error).__name__}: {error}"
                )
            self._drop()
            if self._closing:
                return
            failures = 0 if served else failures + 1
            if not served:
                self._outage.failed(
                    self._finder.last_error or "the session broker cannot be reached", at_once=self._finder.incompatible
                )
            await asyncio.sleep(self._delay(failures))

    def _delay(self, failures: int) -> float:
        """Return how long to wait before the next attempt."""
        if self._goodbye:
            return 0.05  # the broker said it was leaving: look for the next one at once
        if self._finder.incompatible:
            return self.incompatible_delay
        return self.backoff[min(failures, len(self.backoff) - 1)] if failures else self.backoff[0]

    def _drop(self) -> None:
        """Forget the connection: nothing can be sent now, and whatever was waiting on it has failed."""
        was, self._connected = self._connected, False
        self._watched = False
        self._outbox.clear()
        self._asks.clear()
        self._came_up.clear()
        self._ws = self._http = None
        for reply in self._replies.values():
            if not reply.done():
                reply.set_exception(ConnectionError("the connection ended"))
        if was and self._roster:
            self._roster = ()
            self._notify_roster()

    async def _serve_once(self) -> bool:
        """Connect once and serve it to the end; return whether it ever got as far as being greeted."""
        from websockets.exceptions import ConnectionClosed

        ws, note = await self._finder.open(lambda: self._closing)
        http = None
        greeted = False
        try:
            hello = await self._greeting(ws, note.pid)
            http = self._http_client(note.port, note.token, str(hello.get("key")))
            greeted = True
            self.limits = Limits.from_wire(hello.get("limits"))
            self._ws, self._http, self._connected = ws, http, True
            self._finder.incompatible = False
            self._finder.last_error = None
            self._outage.recovered()
            self._came_up.set()
            self._schedule_push()
            for watching in list(self._watching):
                self._ask("watch", watching)
            try:
                async for raw in ws:
                    await self._heard(ws, raw)
            except ConnectionClosed:
                pass
            self._goodbye = ws.close_code == GOODBYE
        finally:
            if http is not None:
                with contextlib.suppress(Exception):
                    await http.aclose()
            with contextlib.suppress(Exception):
                await ws.close()
        return greeted

    async def _greeting(self, ws: Any, pid: int) -> dict[str, Any]:
        """Read the broker's greeting, turning what can go wrong into a sentence."""
        from websockets.exceptions import ConnectionClosed

        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), self.request_timeout))
        except asyncio.TimeoutError:
            raise ConnectionError(f"the session broker (pid {pid}) is running but does not answer") from None
        except (ConnectionClosed, ValueError):
            raise ConnectionError("the session broker closed the connection while greeting") from None
        if not isinstance(hello, dict) or hello.get("op") != "hello" or hello.get("protocol") != PROTOCOL_VERSION:
            self._finder.incompatible = True
            raise ConnectionError(f"the session broker (pid {pid}) speaks another protocol")
        return hello

    @staticmethod
    def _http_client(port: int, token: str, key: str) -> Any:
        import httpx

        return httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            headers={"Authorization": f"Bearer {token}", "X-Session-Key": key},
            trust_env=False,  # the broker is on this machine; a proxy named in the environment is not for it
        )

    # -- what the broker says ---------------------------------------------------------------------
    async def _heard(self, ws: Any, raw: str | bytes) -> None:
        """Act on one line from the broker; one that makes no sense is ignored."""
        try:
            line = json.loads(raw)
        except ValueError:
            return
        if not isinstance(line, dict):
            return
        match line.get("op"):
            case "roster":
                self._roster = roster_from_wire(line.get("sessions"))
                self._notify_roster()
            case "watched":
                count = line.get("count")
                self._watched = isinstance(count, int) and not isinstance(count, bool) and count > 0
            case "stream":
                session_id, event = line.get("session_id"), line.get("event")
                if self.on_stream is not None and isinstance(session_id, str) and isinstance(event, dict):
                    with contextlib.suppress(Exception):  # a listener's bug must not end the connection
                        self.on_stream(session_id, event)
            case "deliver":
                await ws.send(json.dumps({"op": "ack", "id": line.get("id"), **self._deliver(line)}))
            case "done" | "refused":
                reply = self._replies.get(line["n"]) if isinstance(line.get("n"), int) else None
                if reply is not None and not reply.done():
                    reply.set_result(line)

    def _deliver(self, line: dict[str, Any]) -> dict[str, Any]:
        """Hand a message to the session and return what the session said, as the fields of an ack."""
        sender, text, hops, via = (
            PeerInfo.from_wire(line.get("from")),
            line.get("text"),
            line.get("hops"),
            line.get("via"),
        )
        if sender is None or not isinstance(text, str) or not isinstance(hops, int) or isinstance(hops, bool):
            return _ack(Receipt(False, "the message was malformed"))
        if self.on_message is None:
            return _ack(Receipt(False, "this session is not taking messages"))
        mode = line.get("mode")
        if not isinstance(mode, str):
            mode = MODE_STEER  # a peer that does not say: the protocol's default
        elif mode not in MODES:
            mode = MODE_FOLLOWUP  # one this version does not know: the safe half, not the disruptive one
        incoming = Incoming(
            sender,
            clean_text(text),
            hops,
            via if via in VIAS else VIA_AGENT,
            line.get("direct") is True and via == VIA_USER,
            mode,
        )
        try:
            return _ack(self.on_message(incoming))
        except Exception as error:  # noqa: BLE001 - the sender is told, the session carries on
            return _ack(Receipt(False, f"the session could not take it ({type(error).__name__})"))

    def _notify_roster(self) -> None:
        if self.on_roster is not None:
            with contextlib.suppress(Exception):  # a listener's bug must not end the connection
                self.on_roster(self._roster)

    # -- telling the broker what this session is --------------------------------------------------
    def _schedule_push(self) -> None:
        self._dirty = True
        if self._connected and (self._pusher is None or self._pusher.done()):
            self._pusher = asyncio.ensure_future(self._push())

    async def _push(self) -> None:
        """Send the session's latest description, and again if it changed while that was in flight."""
        while self._dirty and self._connected:
            self._dirty = False
            info = self._session
            try:
                await self._tell({"op": "leave"} if info is None else _describe(info))
                self._set_conflict(None)
            except Refused as error:
                if error.reason == "duplicate":
                    self._set_conflict(str(error))
            except Exception:  # noqa: BLE001 - a lost connection: the next one pushes the latest again
                return

    async def _tell(self, line: dict[str, Any]) -> dict[str, Any]:
        """Say something to the broker and return its ``done``; its refusal is raised.

        Raises:
            Refused: The broker refused.
        """
        ws = self._ws
        if ws is None:
            raise ConnectionError("not connected")
        number = next(self._numbers)
        reply: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._replies[number] = reply
        try:
            await ws.send(json.dumps({**line, "n": number}))
            answer = await asyncio.wait_for(reply, self.request_timeout)
        finally:
            self._replies.pop(number, None)
        if answer.get("op") == "refused":
            raise Refused.from_wire(answer.get("error"))
        return answer

    def _set_conflict(self, message: str | None) -> None:
        if message == self._conflict:
            return
        self._conflict = message
        if self.on_conflict is not None:
            with contextlib.suppress(Exception):
                self.on_conflict(message)


def _describe(info: SessionInfo) -> dict[str, Any]:
    """Return a session as the line that tells the broker what it is."""
    return {
        "op": "session",
        "session_id": info.session_id,
        "title": info.title,
        "workspace": info.workspace,
        "status": info.status,
        "kind": info.kind,
        "direct": info.direct,
    }


def _ack(receipt: Receipt) -> dict[str, Any]:
    """Return a receipt as the fields of an ``ack``."""
    return {"accepted": receipt.accepted, "reason": receipt.reason, "disposition": receipt.disposition}


__all__ = [
    "BACKOFF",
    "BrokerClient",
    "Delivered",
    "INCOMPATIBLE_DELAY",
    "Incoming",
    "PROBLEM_AFTER",
    "REQUEST_TIMEOUT",
    "Receipt",
    "RosterEntry",
    "SendError",
    "SessionInfo",
]
