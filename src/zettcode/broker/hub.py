"""What the broker *decides*: who is here, who a message is from, whether it may pass, and who is told.

The hub knows nothing of HTTP, of WebSockets or of uvicorn (that is :mod:`.web`) and nothing of the process (that is
:mod:`.server` and :mod:`.runner`). A connection reaches it as a :class:`Session`: a queue of lines to be sent to
whoever is on the other end, and a key. Everything the hub says it says with :meth:`Session.push`, so it can be
driven, and tested, by calling it.

A message is routed from its sender to its recipient and the sender is answered only when the recipient has said it
took it. The rules it has to pass are in :mod:`.protocol` (its length, its hop count) and here (who sent it, how fast
one sender may send, whether the recipient exists and is still connected); the recipient decides what to do with it —
the shell starts a turn, or queues it, or refuses because it is full — and says so in its ack, which is what the
sender is told.
"""

from __future__ import annotations

import asyncio
import itertools
import secrets
import time
from collections import deque
from collections.abc import Callable
from typing import Any, NamedTuple

from .protocol import (
    ACK_TIMEOUT,
    KIND_EXTERNAL,
    MAX_NAME,
    PROTOCOL_VERSION,
    VIA_EXTERNAL,
    Limits,
    PeerInfo,
    Refused,
    SessionUpdate,
    parse_send,
)
from .roster import Roster
from .text import clean_text, clean_title, slug

#: Messages waiting for one session to say it took them. More are told the session is busy.
MAX_WAITING = 32

#: Lines queued for one session to read. A session that is this far behind has stopped reading and is dropped.
MAX_QUEUED = 256

#: What a connection is closed with when it has stopped reading (WebSocket's "policy violation").
STOPPED_READING = 1008


class _Gone(Exception):
    """The session a message was handed to went away before it answered."""


class Sender(NamedTuple):
    """Who a message is from, as the broker has established it."""

    info: PeerInfo
    #: Not a ZettCode session: its word about itself is not checked, and it cannot pass itself off as one.
    external: bool
    #: The connection that sent it, or ``None`` when it came from outside every connection.
    connection: int | None


class Session:
    """One open connection, as the hub sees it.

    Args:
        number: What tells it apart from the others.
        close: Closes the connection with a code; given by whoever owns the connection.
    """

    def __init__(self, number: int, close: Callable[[int], None]) -> None:
        self.number = number
        #: Its credential for sending: how a message says whom it is from.
        self.key = secrets.token_urlsafe(18)
        self.outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue(MAX_QUEUED)
        #: Closes the connection with a code.
        self.close = close
        self._dropped = False
        self._waiting: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._deliveries = itertools.count(1)

    def push(self, line: dict[str, Any]) -> None:
        """Queue a line for this session without waiting for it to be read; one that stopped reading is dropped."""
        try:
            self.outbox.put_nowait(line)
        except asyncio.QueueFull:
            if not self._dropped:
                self._dropped = True
                self.close(STOPPED_READING)

    @property
    def waiting(self) -> int:
        """How many messages are waiting for this session to say it took them."""
        return len(self._waiting)

    async def deliver(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Hand this session a message and return its ack.

        Raises:
            Refused: ``busy`` when too many are already waiting.
            asyncio.TimeoutError: It did not answer in ``timeout`` seconds.
            _Gone: It went away first.
        """
        if self.waiting >= MAX_WAITING:
            raise Refused("busy", "that session has too many messages waiting")
        number = next(self._deliveries)
        ack: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiting[number] = ack
        try:
            self.push({"op": "deliver", "id": number, **message})
            return await asyncio.wait_for(ack, timeout)
        finally:
            self._waiting.pop(number, None)

    def acked(self, line: dict[str, Any]) -> None:
        """Take an ack; one for something that was never asked, or already answered, is ignored."""
        number = line.get("id")
        ack = self._waiting.get(number) if isinstance(number, int) else None
        if ack is not None and not ack.done():
            ack.set_result(line)

    def gone(self) -> None:
        """Fail every message that was waiting on this session."""
        for ack in self._waiting.values():
            if not ack.done():
                ack.set_exception(_Gone())


class Hub:
    """The sessions, the roster, and the rules for a message.

    Args:
        ack_timeout: Seconds to wait for a recipient to say it took a message.
        clock: Time source for the rate limit, injectable for tests.
    """

    def __init__(self, *, ack_timeout: float = ACK_TIMEOUT, clock: Callable[[], float] = time.monotonic) -> None:
        self.ack_timeout = ack_timeout
        self.clock = clock
        self.limits = Limits()
        self.roster = Roster()
        #: Every open connection, by number, and by key.
        self.sessions: dict[int, Session] = {}
        self.by_key: dict[str, Session] = {}
        #: Set when the broker is going away: nobody is told who left.
        self.closing = False
        self._numbers = itertools.count(1)
        self._sends: dict[str, deque[float]] = {}

    # -- connections ------------------------------------------------------------------------------
    def admit(self, close: Callable[[int], None]) -> Session:
        """Take a new connection: greet it with the limits and its key, and tell it who is here."""
        session = Session(next(self._numbers), close)
        self.sessions[session.number] = session
        self.by_key[session.key] = session
        session.push({"op": "hello", "protocol": PROTOCOL_VERSION, "key": session.key, "limits": self.limits.to_wire()})
        self._tell_roster(session)
        return session

    def release(self, session: Session) -> None:
        """Forget a connection that has ended, and tell the others if it was registered."""
        self.sessions.pop(session.number, None)
        self.by_key.pop(session.key, None)
        session.gone()
        if self.roster.drop(session.number) is not None and not self.closing:
            self._announce()

    def listing(self) -> dict[str, Any]:
        """Return who is registered and what is allowed, as ``GET /sessions`` answers."""
        return {"sessions": [entry.to_wire() for entry in self.roster.snapshot()], "limits": self.limits.to_wire()}

    # -- what a session says ----------------------------------------------------------------------
    def hear(self, session: Session, line: dict[str, Any]) -> None:
        """Act on one line from a session; a refusal is answered, anything unknown is ignored."""
        n = line.get("n")
        n = n if isinstance(n, int) and not isinstance(n, bool) else None
        try:
            match line.get("op"):
                case "session":
                    self._on_session(session, n, line)
                case "leave":
                    self._on_leave(session, n)
                case "ack":
                    session.acked(line)
        except Refused as refused:
            session.push({"op": "refused", "n": n, "error": refused.to_wire()})

    def _on_session(self, session: Session, n: int | None, line: dict[str, Any]) -> None:
        update = SessionUpdate.parse(line)
        before = self.roster.of(session.number)
        shown = before.public() if before is not None else None
        entry = self.roster.set(session.number, update)
        session.push({"op": "done", "n": n, "handle": entry.handle})
        if entry.public() != shown:
            self._announce()

    def _on_leave(self, session: Session, n: int | None) -> None:
        dropped = self.roster.drop(session.number) is not None
        session.push({"op": "done", "n": n})
        if dropped:
            self._announce()

    # -- a message --------------------------------------------------------------------------------
    async def send(self, key: str | None, body: dict[str, Any]) -> dict[str, Any]:
        """Check a message, hand it to its recipient, and wait for the recipient's answer.

        Raises:
            Refused: For every reason in :mod:`.protocol` a message can fail.
        """
        sender = self._sender(key, body)
        self._throttle(sender.info.session_id)
        if sender.external:
            body = {**body, "via": VIA_EXTERNAL}
        to, text, via, hops = parse_send(body, self.limits)
        if via == VIA_EXTERNAL and not sender.external:
            raise Refused("invalid", "via is 'user' or 'agent'")
        target = self.roster.resolve(to, asker=sender.connection)
        recipient = self.sessions.get(target.owner)
        if recipient is None:
            raise Refused("gone", f"@{target.handle} is no longer connected")
        message = {"from": sender.info.to_wire(), "text": text, "hops": hops + 1, "via": via}
        ack = await self._hand_over(recipient, message, target.handle)
        return {"to": target.public().to_wire(), **ack}

    def _sender(self, key: str | None, body: dict[str, Any]) -> Sender:
        """Work out who a message is from: the session its key belongs to, or an outsider who names itself."""
        if key:
            owner = self.by_key.get(key)
            if owner is None:
                raise Refused("auth", "that session key is not one of this broker's")
            entry = self.roster.of(owner.number)
            if entry is None:
                raise Refused("not_registered", "this session has not said who it is")
            return Sender(entry.public(), entry.kind == KIND_EXTERNAL, owner.number)
        origin = body.get("from")
        name = clean_title(origin.get("name") if isinstance(origin, dict) else None, MAX_NAME) or "external"
        handle = slug(name) or "external"
        return Sender(PeerInfo(f"external:{handle}", handle, name, "", "idle", KIND_EXTERNAL), True, None)

    def _throttle(self, sender: str) -> None:
        """Count this send against the sender's allowance, and refuse it when the allowance is spent."""
        now = self.clock()
        sends = self._sends.setdefault(sender, deque())
        while sends and now - sends[0] > self.limits.rate_window:
            sends.popleft()
        if len(sends) >= self.limits.rate_limit:
            raise Refused("rate", f"at most {self.limits.rate_limit} messages a minute; try again later")
        sends.append(now)

    async def _hand_over(self, recipient: Session, message: dict[str, Any], handle: str) -> dict[str, str]:
        """Give the recipient the message and turn its ack into what the sender is told."""
        try:
            ack = await recipient.deliver(message, self.ack_timeout)
        except _Gone:
            raise Refused("gone", f"@{handle} is no longer connected") from None
        except asyncio.TimeoutError:
            raise Refused("timeout", f"@{handle} did not answer in {self.ack_timeout:g} seconds") from None
        if ack.get("accepted") is not True:
            reason = ack.get("reason")
            said = clean_text(reason)[:300] if isinstance(reason, str) else ""
            if not isinstance(ack.get("accepted"), bool):
                said = "the session's answer was not understood"
            raise Refused("rejected", said or "not accepted")
        disposition = ack.get("disposition")
        return {"disposition": disposition if isinstance(disposition, str) else ""}

    # -- telling the sessions ---------------------------------------------------------------------
    def _announce(self) -> None:
        """Tell every session who is registered now."""
        for session in list(self.sessions.values()):
            self._tell_roster(session)

    def _tell_roster(self, session: Session) -> None:
        session.push({"op": "roster", "sessions": [entry.to_wire() for entry in self.roster.snapshot()]})
