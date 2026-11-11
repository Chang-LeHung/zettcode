"""A small, high-level surface for programs that join the broker as an external session.

The protocol has two kinds of outside participant: an HTTP sender, which has no inbox and can only put a message
into the broker, and a registered session, which has a WebSocket, a handle in the roster, and can receive and
answer. :class:`ExternalSession` is the second one, written for a program that is not ZettCode itself; it wraps
:class:`~.client.BrokerClient`, so reconnection, registration, acknowledgements and the limits stay in one place.

:class:`ExternalPublisher` is for the first kind: a one-way script that only needs ``send``.

The broker's token is the owner credential, not a per-session password: any local program holding it may claim any
``session_id``. A handle is a claimed name in the roster, not an authentication.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeAlias

from zettcode.modes import MODE_FOLLOWUP, MODE_STEER

from .client import BrokerClient
from .files import broker_dir, read_note
from .models import Delivered, GroupDelivered, GroupInfo, Incoming, Receipt, SendError, SessionInfo
from .protocol import KIND_EXTERNAL, KIND_ZETTCODE, VIA_AGENT, VIA_EXTERNAL, PeerInfo

logger = logging.getLogger("zettcode.broker")

#: What an external session does with a delivered message. ``None`` accepts it without a reply; a string is sent
#: back to the sender; a :class:`Receipt` is the exact answer. An awaitable is acked ``queued`` before it runs, so
#: it can no longer refuse the message; return a Receipt first if the answer must be a refusal.
#:
#: A plain (non-async) handler runs on the WebSocket receive loop. It must return promptly: use an async handler for
#: work that waits on a process, a network call or a lock.
Handler: TypeAlias = Callable[[Incoming], Receipt | str | None | Awaitable[Receipt | str | None]]


class ExternalError(Exception):
    """The base of the errors a high-level external client reports."""


class ExternalNotConnected(ExternalError):
    """No broker answered, the session was closed, or it speaks a protocol this client does not."""


class ExternalConflict(ExternalError):
    """Another process already has this ``session_id`` in the broker's roster."""


class ExternalSession:
    """One external program's identity in the broker.

    Subclass it and override :meth:`on_message`, or pass ``on_message``; each instance is a separate WebSocket and a
    separate entry in the broker's roster. The broker gives it a handle derived from ``title``, which other sessions
    address with ``@handle``.

    The program is an ``external`` session by default: it can exchange one-to-one messages and, when the broker's
    owner adds it, receive and write to groups. It cannot create or manage groups with its own key, read a group's
    history, or use the ``direct`` chat-window semantics; those are limits of the broker's permission model, not
    this wrapper.

    Args:
        session_id: The stable id this program registers with. It must be a broker session id (letters, digits,
            ``.``, ``_`` and ``-``). This is a claimed name: the broker does not verify who made it.
        title: What the roster shows. A handle is derived from it.
        workspace: An optional path shown in the roster.
        kind: ``external`` for an ordinary outside program, or ``zettcode`` for a trusted gateway plugin that also
            needs group chats and history. The broker treats the kind as the program's claim.
        on_message: How to answer a message; :meth:`on_message` is used when this is ``None``. A sync handler must
            not block the event loop.
        directory: The broker's directory; :func:`~.files.broker_dir` by default.
        spawner: How to start a broker when none answers; the broker's own default when ``None``.
        on_roster: Called whenever the roster changes.
        on_problem: Called once when the broker has been out of reach for a while, and again when it is back.
        on_conflict: Called when another process claims this ``session_id``, and with ``None`` when it is free.
        inbox_size: Messages the default handler may queue before it refuses with ``busy``; ``0`` is unbounded.
        connect_timeout: Seconds to wait for the connection and registration.
        request_timeout: Seconds to wait for an answer from the broker.
    """

    #: Defaults for a subclass that does not pass them to ``__init__``.
    session_id: str = ""
    title: str = ""

    def __init__(
        self,
        session_id: str = "",
        title: str = "",
        *,
        workspace: str = "",
        kind: str = KIND_EXTERNAL,
        on_message: Handler | None = None,
        directory: Path | None = None,
        spawner: Callable[[Path], None] | None = None,
        on_roster: Callable[[tuple[PeerInfo, ...]], None] | None = None,
        on_problem: Callable[[str | None], None] | None = None,
        on_conflict: Callable[[str | None], None] | None = None,
        inbox_size: int = 1000,
        connect_timeout: float = 5.0,
        request_timeout: float = 5.0,
    ) -> None:
        if inbox_size < 0:
            raise ValueError("inbox_size is 0 (unbounded) or a positive count")
        self.session_id = session_id or type(self).session_id
        if not self.session_id:
            raise ValueError("an external session needs a session_id")
        self.title = title or type(self).title or self.session_id
        if kind not in (KIND_EXTERNAL, KIND_ZETTCODE):
            raise ValueError("kind is 'external' or 'zettcode'")
        self.workspace = workspace
        self.kind = kind
        self.inbox: asyncio.Queue[Incoming] = asyncio.Queue(maxsize=inbox_size)
        self._handler = on_message
        self._on_roster = on_roster
        self._connect_timeout = connect_timeout
        self._tasks: set[asyncio.Future[None]] = set()
        self._closed = False
        self._client = BrokerClient(
            on_message=self._dispatch,
            on_roster=self._changed,
            on_problem=on_problem,
            on_conflict=on_conflict,
            directory=directory or broker_dir(),
            spawner=spawner,
            request_timeout=request_timeout,
            connect_timeout=connect_timeout,
        )
        self._client.set_session(
            SessionInfo(
                session_id=self.session_id,
                title=self.title,
                workspace=workspace,
                status="idle",
                kind=kind,
            )
        )

    async def __aenter__(self) -> ExternalSession:
        """Connect and register; leave with ``async with`` to close the connection."""
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Connect, register, and wait until the broker lists this session.

        A closed session cannot be reused; make a new one.

        Raises:
            ExternalNotConnected: The broker is absent, does not answer, speaks another protocol, or this session
                was closed.
            ExternalConflict: Another process already holds ``session_id``.
        """
        if self._closed:
            raise ExternalNotConnected("this external session was closed; make a new one")
        await self._client.start()
        if not await self._client.wait_connected(self._connect_timeout):
            self._closed = True
            await self._client.close()
            raise ExternalNotConnected(self._client.last_error or "no broker answered")
        if not await self._client.wait_registered(self._connect_timeout):
            conflict = self._client.conflict
            self._closed = True
            await self._client.close()
            if conflict:
                raise ExternalConflict(conflict)
            raise ExternalNotConnected("the broker did not register this session")

    async def close(self) -> None:
        """Disconnect, stop reconnecting, and cancel handler tasks. Safe to call more than once."""
        self._closed = True
        await self._client.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def connected(self) -> bool:
        """Whether the WebSocket is up right now."""
        return self._client.connected

    @property
    def roster(self) -> tuple[PeerInfo, ...]:
        """Every registered session, this one included, as of the last update."""
        return self._client.roster

    @property
    def limits(self) -> Any:
        """What the broker accepts from a sender, as announced at connection."""
        return self._client.limits

    def watch(self, session_id: str) -> None:
        """Ask the broker to stream another session's turn."""
        self._client.watch(session_id)

    def unwatch(self, session_id: str) -> None:
        """Stop streaming another session's turn."""
        self._client.unwatch(session_id)

    def on_stream(self, callback: Callable[[str, dict[str, Any]], None] | None) -> None:
        """Receive the stream lines of watched sessions."""
        self._client.on_stream = callback

    def observe(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        """Receive every message that passes through the broker."""
        self._client.observe(callback)

    @property
    def groups(self) -> tuple[GroupInfo, ...]:
        """The group chats this session is in, as of the last broker update."""
        return self._client.groups

    @property
    def handle(self) -> str:
        """The handle the broker gave this session, or an empty string before registration."""
        for entry in self._client.roster:
            if entry.session_id == self.session_id:
                return entry.handle
        return ""

    async def receive(self) -> Incoming:
        """Wait for the next message; useful when no handler was passed.

        A closed session with an empty inbox raises instead of waiting for a message that cannot arrive.
        """
        if self._closed and self.inbox.empty():
            raise ExternalNotConnected("this external session was closed; make a new one")
        return await self.inbox.get()

    async def send(self, to: str, text: str, *, mode: str = MODE_FOLLOWUP) -> Delivered:
        """Send one message to a session, by handle, id, or a prefix of its id.

        Raises:
            ExternalNotConnected: This session is not connected.
            SendError: The broker or the recipient refused, or the connection was lost.
        """
        if mode not in (MODE_STEER, MODE_FOLLOWUP):
            raise ValueError("mode is 'steer' or 'followup'")
        if self._closed:
            raise ExternalNotConnected("this external session was closed; make a new one")
        if not self._client.connected:
            raise ExternalNotConnected("the external session is not connected")
        via = VIA_EXTERNAL if self.kind == KIND_EXTERNAL else VIA_AGENT
        return await self._client.send(to, text, via=via, mode=mode)

    async def reply(self, message: Incoming, text: str, *, mode: str = MODE_FOLLOWUP) -> Delivered:
        """Answer the sender of ``message``; the stable sender id is used, not its handle."""
        return await self.send(message.sender.session_id, text, mode=mode)

    async def send_group(self, group: str, text: str, *, mode: str = MODE_FOLLOWUP) -> GroupDelivered:
        """Write to a group this session is in; membership is what the broker checks, not the kind."""
        if self._closed or not self._client.connected:
            raise ExternalNotConnected("the external session is not connected")
        via = VIA_EXTERNAL if self.kind == KIND_EXTERNAL else VIA_AGENT
        return await self._client.send_group(group, text, via=via, mode=mode)

    async def join_group(self, group: str) -> GroupInfo | None:
        """Join a group as the broker's owner; a gateway-managed session uses this, and the broker decides."""
        if self._closed or not self._client.connected:
            raise ExternalNotConnected("the external session is not connected")
        return await self._client.join_group(group)

    async def set_status(self, status: str) -> None:
        """Say whether this session is ``idle`` or ``working``."""
        if self._closed:
            raise ExternalNotConnected("this external session was closed; make a new one")
        if status not in ("idle", "working"):
            raise ValueError("status is 'idle' or 'working'")
        self._client.set_session(
            SessionInfo(
                session_id=self.session_id,
                title=self.title,
                workspace=self.workspace,
                status=status,
                kind=self.kind,
            )
        )

    async def on_message(self, message: Incoming) -> Receipt:
        """Default handler: put the message on :attr:`inbox` and accept it.

        The ack means the message is in this process's queue, not that it was handled. When the queue is full the
        broker is told ``busy`` so it holds the message and offers it again.
        """
        try:
            self.inbox.put_nowait(message)
        except asyncio.QueueFull:
            return Receipt(False, reason="this external session's inbox is full", busy=True)
        return Receipt(True, disposition="delivered")

    def _changed(self, roster: tuple[PeerInfo, ...]) -> None:
        if self._on_roster is not None:
            self._on_roster(roster)

    def _dispatch(self, message: Incoming) -> Receipt:
        """Turn a handler's answer into the ack the broker wants, scheduling an awaitable for later."""
        handler = self._handler or self.on_message
        try:
            result = handler(message)
        except Exception as error:  # noqa: BLE001 - a bad handler is a refusal, not a dead session
            logger.exception("external.handler")
            return Receipt(False, f"the handler failed ({type(error).__name__})")
        if inspect.isawaitable(result):
            self._spawn(self._later(message, result))
            return Receipt(True, disposition="queued")
        return self._receipt(message, result)

    def _receipt(self, message: Incoming, result: Receipt | str | None) -> Receipt:
        if result is None:
            return Receipt(True, disposition="delivered")
        if isinstance(result, Receipt):
            return result
        if isinstance(result, str):
            self._spawn(self._say_later(message, result))
            return Receipt(True, disposition="queued")
        logger.warning("external.handler", extra={"result": type(result).__name__})
        return Receipt(False, "the handler returned something that is not Receipt, str or None")

    def _spawn(self, work: Awaitable[None]) -> None:
        """Keep a handler task alive until it finishes, so ``close`` can cancel and collect it."""
        task = asyncio.ensure_future(work)
        if self._closed:
            task.cancel()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _later(self, message: Incoming, result: Awaitable[Receipt | str | None]) -> None:
        try:
            answer = await result
        except Exception:  # noqa: BLE001 - the ack already went; keep the session alive
            logger.exception("external.handler")
            return
        if isinstance(answer, str):
            await self._say_later(message, answer)
        elif isinstance(answer, Receipt):
            # The broker already has its ack; a late Receipt cannot change it.
            logger.warning("external.late_receipt", extra={"accepted": answer.accepted})

    async def _say_later(self, message: Incoming, text: str) -> None:
        try:
            await self.reply(message, text)
        except (SendError, ExternalNotConnected) as error:
            logger.warning("external.reply_failed", extra={"reason": str(error)})


class ExternalPublisher:
    """A one-way external sender: no WebSocket, no roster, no replies.

    It is the high-level form of ``POST /messages`` without a session key. The broker names the sender from
    ``name`` and marks the message ``via="external"``. It keeps one broker address and token: after a broker
    restart, call :meth:`connect` again before sending.
    """

    def __init__(
        self,
        name: str = "external",
        *,
        directory: Path | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.name = name
        self.directory = directory or broker_dir()
        self.timeout = timeout
        self._http: Any = None

    async def __aenter__(self) -> ExternalPublisher:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Read the broker's note and open its HTTP client.

        Raises:
            ExternalNotConnected: There is no broker note, or it cannot be read.
        """
        note = read_note(self.directory)
        if note is None:
            raise ExternalNotConnected(f"there is no broker note in {self.directory}")
        import httpx

        await self.close()
        self._http = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{note.port}",
            headers={"Authorization": f"Bearer {note.token}"},
            trust_env=False,
            timeout=self.timeout,
        )

    async def close(self) -> None:
        """Close the HTTP client; safe to call twice."""
        http, self._http = self._http, None
        if http is not None:
            await http.aclose()

    async def send(self, to: str, text: str, *, mode: str = MODE_FOLLOWUP) -> Delivered:
        """Put one message into the broker as an external source.

        Raises:
            ExternalNotConnected: :meth:`connect` has not run.
            SendError: The broker refused, or the connection failed. A connection that never opened is ``offline``;
                one that ended while the message was being written is ``lost`` or ``timeout``.
        """
        http = self._http
        if http is None:
            raise ExternalNotConnected("ExternalPublisher is not connected")
        if mode not in (MODE_STEER, MODE_FOLLOWUP):
            raise ValueError("mode is 'steer' or 'followup'")
        try:
            response = await http.post(
                "/messages",
                json={"to": to, "text": text, "from": {"name": self.name}, "mode": mode},
            )
        except Exception as error:  # noqa: BLE001 - httpx's exception hierarchy is wide; map the useful ones
            import httpx

            if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
                raise SendError("offline", "no broker answered") from None
            if isinstance(error, httpx.TimeoutException):
                raise SendError("timeout", "the broker did not answer in time; the message may have arrived") from None
            raise SendError("lost", f"the broker could not be reached ({type(error).__name__})") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            refusal = body.get("error") if isinstance(body, dict) else None
            if isinstance(refusal, dict) and isinstance(refusal.get("reason"), str):
                raise SendError(refusal["reason"], str(refusal.get("message", "")))
            raise SendError("internal", f"the broker answered {response.status_code}")
        to_info = PeerInfo.from_wire(body.get("to"))
        if to_info is None:
            raise SendError("internal", "the broker's answer did not say who took the message")
        disposition = body.get("disposition")
        return Delivered(to_info, disposition if isinstance(disposition, str) else "")


__all__ = [
    "ExternalConflict",
    "ExternalError",
    "ExternalNotConnected",
    "ExternalPublisher",
    "ExternalSession",
    "Handler",
]
