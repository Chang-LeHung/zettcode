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
import json
import logging
import secrets
import sqlite3
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from .protocol import (
    ACK_TIMEOUT,
    KIND_EXTERNAL,
    KIND_ZETTCODE,
    MAX_GROUP_MEMBERS,
    MAX_GROUPS,
    MAX_GROUPS_PER_SESSION,
    MAX_NAME,
    MAX_STREAM,
    PROTOCOL_VERSION,
    SESSION_ID,
    STREAM_TYPES,
    VIA_EXTERNAL,
    VIA_USER,
    ImageData,
    Limits,
    PeerInfo,
    Refused,
    SessionUpdate,
    group_name,
    parse_images,
    parse_send,
)
from .roster import Entry, Roster
from .store import KIND_GROUP, KIND_SESSION, MAX_WINDOW, Store
from .text import clean_text, clean_title, slug

#: Messages waiting for one session to say it took them. More are told the session is busy.
MAX_WAITING = 32

#: The pictures, as base64, that one session may have waiting for it at once: in messages it has not answered, and in
#: lines it has not read. A message may carry about 11 MiB of them, and a session that has stopped answering would
#: otherwise hold hundreds of those in the broker.
MAX_WAITING_PICTURES = 96 << 20

#: Lines queued for one session to read. A session that is this far behind has stopped reading and is dropped.
MAX_QUEUED = 256

#: How many sessions one connection may watch: there are rarely more than a few dozen sessions on a machine.
MAX_WATCHING = 256

#: The most messages a history query, and a replay of the past, returns when the asker does not say.
DEFAULT_HISTORY = 20

logger = logging.getLogger("zettcode.broker")

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
        #: The sessions whose turns this connection asked to see.
        self.watching: set[str] = set()
        #: Whether this connection asked to be told of every message that passes (the gateway's graph does).
        self.observing = False
        self._waiting: dict[int, asyncio.Future[dict[str, Any]]] = {}
        #: The size, as base64, of the pictures in the messages in ``_waiting``.
        self._weight = 0
        #: The size, as base64, of the pictures in the lines still in ``outbox``, which a message whose ack timed out
        #: leaves behind: a socket that never drains must not be able to hold more than the budget.
        self._queued = 0
        self._deliveries = itertools.count(1)

    def push(self, line: dict[str, Any]) -> None:
        """Queue a line for this session without waiting for it to be read; one that stopped reading is dropped."""
        try:
            self.outbox.put_nowait(line)
        except asyncio.QueueFull:
            if not self._dropped:
                self._dropped = True
                self.close(STOPPED_READING)
        else:
            self._queued += _picture_weight(line)

    async def next_line(self) -> dict[str, Any]:
        """Take the next queued line, for the writer to send: its pictures stop counting against this session's budget."""
        line = await self.outbox.get()
        self._queued -= _picture_weight(line)
        return line

    def push_lossy(self, line: dict[str, Any]) -> None:
        """Queue a line that may be lost: when this session is half a queue behind it is skipped, not dropped for it.

        What a turn streams is only ever a view of what is stored, so a reader that cannot keep up misses some of it
        and sees the rest when the turn is written down, rather than being disconnected for it.
        """
        if self.outbox.qsize() < MAX_QUEUED // 2:
            self.push(line)

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
        weight = sum(len(picture.get("data", "")) for picture in message.get("images", ()))
        if weight and self._weight + self._queued + weight > MAX_WAITING_PICTURES:
            raise Refused("busy", "that session has too many pictures waiting")
        number = next(self._deliveries)
        ack: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiting[number] = ack
        self._weight += weight
        try:
            self.push({"op": "deliver", "id": number, **message})
            return await asyncio.wait_for(ack, timeout)
        finally:
            self._waiting.pop(number, None)
            self._weight -= weight

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
        store: What is remembered across restarts: messages and groups. Memory only when none is given.
    """

    def __init__(
        self,
        *,
        ack_timeout: float = ACK_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        store: Store | None = None,
    ) -> None:
        self.ack_timeout = ack_timeout
        self.clock = clock
        self.store = store if store is not None else Store()
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
        if not self.closing:
            for watched in session.watching:
                self._tell_watched(watched)
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
                case "watch" | "unwatch":
                    self._on_watch(session, n, line)
                case "observe" | "unobserve":
                    session.observing = line.get("op") == "observe"
                    if n is not None:
                        session.push({"op": "done", "n": n})
                case "stream":
                    self._on_stream(session, line)
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
        self._tell_watched(update.session_id)
        if entry.public() != shown:
            self._announce()
        else:
            self._tell_groups(session)

    def _on_watch(self, session: Session, n: int | None, line: dict[str, Any]) -> None:
        session_id = line.get("session_id")
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise Refused("invalid", "a session id is 1-64 letters, digits, '.', '_' or '-'")
        watching = line.get("op") == "watch"
        if watching and session_id not in session.watching and len(session.watching) >= MAX_WATCHING:
            raise Refused("busy", f"a session may watch at most {MAX_WATCHING} others")
        changed = (session_id in session.watching) != watching
        session.watching.add(session_id) if watching else session.watching.discard(session_id)
        # Said again, it changes nothing and costs nobody a line; a client sends these without a number and wants no
        # answer, and one that asks for it is told.
        if n is not None:
            session.push({"op": "done", "n": n})
        if changed:
            self._tell_watched(session_id)

    def _watchers(self, session_id: str) -> list[Session]:
        return [other for other in self.sessions.values() if session_id in other.watching]

    def _tell_watched(self, session_id: str) -> None:
        """Tell the session that holds ``session_id`` how many are watching it, so it streams only while any are."""
        owner = self.roster.owner_of(session_id)
        holder = self.sessions.get(owner) if owner is not None else None
        if holder is not None:
            holder.push({"op": "watched", "count": len(self._watchers(session_id))})

    def _on_stream(self, session: Session, line: dict[str, Any]) -> None:
        """Pass what a turn says to the sessions watching it. Nothing is kept, and nobody is told when it is not wanted."""
        entry = self.roster.of(session.number)
        event = line.get("event")
        if entry is None or not isinstance(event, dict) or event.get("t") not in STREAM_TYPES:
            return
        watchers = self._watchers(entry.session_id)
        if not watchers or len(json.dumps(event)) > MAX_STREAM:
            return
        for watcher in watchers:
            watcher.push_lossy({"op": "stream", "session_id": entry.session_id, "event": event})

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
        group = body.get("group")
        # Looked at, not yet decoded: a message that may not carry pictures is turned away before they cost anything.
        offered = body.get("images")
        if group is not None:
            if offered:
                raise Refused("invalid", "pictures go to one session, not to a group")
            if body.get("to") not in (None, ""):
                raise Refused("invalid", "name a session in 'to' or a group in 'group', not both")
            # The group's name stands where a session's would while the text, the hops and the mode are checked.
            _, text, via, hops, mode = parse_send({**body, "to": "group"}, self.limits)
            if via == VIA_EXTERNAL and not sender.external:
                raise Refused("invalid", "via is 'user' or 'agent'")
            return await self._send_group(sender, group_name(group), text, via, hops, mode)
        to, text, via, hops, mode = parse_send(body, self.limits, may_be_silent=bool(offered))
        if via == VIA_EXTERNAL and not sender.external:
            raise Refused("invalid", "via is 'user' or 'agent'")
        target = self.roster.resolve(to, asker=sender.connection)
        recipient = self.sessions.get(target.owner)
        if recipient is None:
            raise Refused("gone", f"@{target.handle} is no longer connected")
        message = {"from": sender.info.to_wire(), "text": text, "hops": hops + 1, "via": via, "mode": mode}
        # A reader's chat window may ask for its text to be run as the recipient's own prompt, but only of a session
        # that said it can; for any other the flag is dropped and the message is delivered the ordinary way.
        if body.get("direct") is True and via == VIA_USER and not sender.external and target.direct:
            message["direct"] = True
        pictures: tuple[ImageData, ...] = ()
        if offered:
            # Only a session that runs the message as its reader's own prompt has anywhere to put a picture: for any
            # other the pictures would be dropped on the way in, and the sender told it went through.
            if message.get("direct") is not True:
                raise Refused(
                    "invalid",
                    f"@{target.handle} does not take pictures: it does not run a chat's text as its own prompt",
                )
            pictures = parse_images(offered)
            message["images"] = [picture.to_wire() for picture in pictures]
        ack = await self._hand_over(recipient, message, target.handle)
        stored = self._remember(
            sender,
            KIND_SESSION,
            (target.session_id, target.handle, target.title),
            [target.session_id],
            _with_pictures(text, len(pictures)),
            via,
            hops + 1,
            mode,
            "delivered",
            ack["disposition"],
        )
        return {"to": target.public().to_wire(), **ack, **({"id": stored["id"]} if stored else {})}

    async def _send_group(self, sender: Sender, name: str, text: str, via: str, hops: int, mode: str) -> dict[str, Any]:
        """Hand a message to every other member of a group that is connected, and say who took it and who did not."""
        found = self.store.group(name)
        if found is None:
            raise Refused("unknown", f"there is no group #{name}")
        if sender.external or sender.info.session_id not in found["members"]:
            raise Refused("denied", f"only a member of #{name} may write to it")
        targets: list[tuple[Session, Entry]] = []
        for member in found["members"]:
            owner = self.roster.owner_of(member)
            if owner is None or member == sender.info.session_id:
                continue
            holder, entry = self.sessions.get(owner), self.roster.of(owner)
            if holder is not None and entry is not None:
                targets.append((holder, entry))
        if not targets:
            raise Refused("gone", f"no other member of #{name} is connected")
        message = {
            "from": sender.info.to_wire(),
            "text": text,
            "hops": hops + 1,
            "via": via,
            "mode": mode,
            "group": name,
        }

        async def one(holder: Session, entry: Entry) -> dict[str, Any]:
            ack = await self._hand_over(holder, dict(message), entry.handle)
            return {"to": entry.public().to_wire(), "disposition": ack["disposition"]}

        results = await asyncio.gather(*(one(h, e) for h, e in targets), return_exceptions=True)
        delivered: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for (_, entry), result in zip(targets, results, strict=True):
            if isinstance(result, Refused):
                failed.append({"handle": entry.handle, "reason": result.reason, "message": str(result)[:300]})
            elif isinstance(result, BaseException):
                # Not one of ours: it is reported as that member failing, and what did land is still written down.
                logger.error("group.send_failed", exc_info=result)
                failed.append({"handle": entry.handle, "reason": "internal", "message": type(result).__name__})
            else:
                delivered.append(result)
        if not delivered:
            first = failed[0]
            raise Refused(first["reason"], f"#{name}: nobody took it. @{first['handle']}: {first['message']}")
        stored = self._remember(
            sender,
            KIND_GROUP,
            (name, name, ""),
            [item["to"]["session_id"] for item in delivered],
            text,
            via,
            hops + 1,
            mode,
            "partial" if failed else "delivered",
            "",
        )
        return {
            "group": name,
            "delivered": delivered,
            "failed": failed,
            **({"id": stored["id"]} if stored else {}),
        }

    # -- what is remembered -----------------------------------------------------------------------
    def _remember(
        self,
        sender: Sender,
        kind: str,
        to: tuple[str, str, str],
        recipients: list[str],
        text: str,
        via: str,
        hops: int,
        mode: str,
        status: str,
        disposition: str,
    ) -> dict[str, Any] | None:
        """Write a handed-over message down and tell the observers; a store that fails loses the record, not the send."""
        try:
            stored = self.store.add_message(
                sender=(sender.info.session_id, sender.info.handle, sender.info.title),
                kind=kind,
                to=to,
                recipients=recipients,
                text=text,
                via=via,
                hops=hops,
                mode=mode,
                status=status,
                disposition=disposition,
            )
        except Exception:  # noqa: BLE001 - messages flow whether or not they are remembered
            logger.exception("store.failed")
            return None
        self._tell_observers({"op": "traffic", "kind": "message", "message": stored})
        return stored

    def _tell_observers(self, line: dict[str, Any]) -> None:
        for session in list(self.sessions.values()):
            if session.observing:
                session.push_lossy(line)

    # -- groups -----------------------------------------------------------------------------------
    def _group_wire(self, group: Mapping[str, Any]) -> dict[str, Any]:
        return {"name": group["name"], "created": group["created"], "members": list(group["members"])}

    def groups_of(self, session_id: str) -> list[dict[str, Any]]:
        """Return the groups a session may write to."""
        return [self._group_wire(group) for group in self.store.groups_of(session_id)]

    def manage_group(self, key: str | None, body: dict[str, Any]) -> dict[str, Any]:
        """Create a group, change who is in it, leave it or delete it, as the session the key belongs to.

        ``action`` is ``create``, ``add``, ``remove``, ``leave`` or ``delete``; ``name`` is the group and ``members``
        the sessions (handles or ids) an ``add``, ``remove`` or ``create`` concerns. A request without a key is the
        owner of the broker and may do all of it but ``leave``.

        Raises:
            Refused: ``invalid``, ``duplicate`` for a name taken, ``unknown`` for a group or session that is not there,
                ``denied`` for a group the asker is not in, ``busy`` for a limit.
        """
        actor: str | None = None
        if key:
            sender = self._sender(key, {})
            if sender.external:
                raise Refused("denied", "only a ZettCode session may use groups")
            actor = sender.info.session_id
        action = body.get("action")
        name = group_name(body.get("name"))
        raw = body.get("members", [])
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise Refused("invalid", "members is a list of sessions")
        found = self.store.group(name)
        if action == "create":
            if found is not None:
                raise Refused("duplicate", f"#{name} already exists")
            if len(self.store.group_names()) >= MAX_GROUPS:
                raise Refused("busy", f"at most {MAX_GROUPS} groups")
            members = self._resolve_members(raw, None)
            if actor is not None and actor not in members:
                members.insert(0, actor)
            if not members:
                raise Refused("invalid", "a group needs at least one member")
            if len(members) > MAX_GROUP_MEMBERS:
                raise Refused("busy", f"a group holds at most {MAX_GROUP_MEMBERS} sessions")
            self._check_room(members)
            try:
                self.store.create_group(name, actor or "", members)
            except sqlite3.IntegrityError:
                raise Refused("duplicate", f"#{name} already exists") from None
        else:
            if action not in ("add", "remove", "leave", "delete"):
                raise Refused("invalid", "action is create, add, remove, leave or delete")
            if found is None:
                raise Refused("unknown", f"there is no group #{name}")
            if actor is not None and actor not in found["members"]:
                raise Refused("denied", f"only a member of #{name} may change it")
            if action == "add":
                members = self._resolve_members(raw, None)
                if len(set(found["members"]) | set(members)) > MAX_GROUP_MEMBERS:
                    raise Refused("busy", f"a group holds at most {MAX_GROUP_MEMBERS} sessions")
                self._check_room([m for m in members if m not in found["members"]])
                for member in members:
                    self.store.add_member(name, member)
            elif action == "remove":
                for member in self._resolve_members(raw, found["members"]):
                    self.store.remove_member(name, member)
            elif action == "leave":
                if actor is None:
                    raise Refused("invalid", "only a session can leave a group")
                self.store.remove_member(name, actor)
            else:
                self.store.delete_group(name)
        self._announce_groups()
        after = self.store.group(name)
        return {"group": self._group_wire(after) if after is not None else None}

    def _check_room(self, members: list[str]) -> None:
        """Refuse (``busy``) when one of these sessions would be in more than :data:`MAX_GROUPS_PER_SESSION` groups."""
        for member in members:
            if len(self.store.groups_of(member)) >= MAX_GROUPS_PER_SESSION:
                owner = self.roster.owner_of(member)
                held = self.roster.of(owner) if owner is not None else None
                who = held.handle if held is not None else member[:8]
                raise Refused("busy", f"@{who} is already in {MAX_GROUPS_PER_SESSION} groups, which is the most")

    def _resolve_members(self, names: list[str], among: list[str] | None) -> list[str]:
        """Turn handles and ids into session ids: a connected session by the roster's rules, or (for removal) a member."""
        found: list[str] = []
        for name in names:
            try:
                sid = self.roster.resolve(name).session_id
            except Refused as refused:
                if refused.reason != "unknown" or among is None or name.lstrip("@") not in among:
                    raise
                sid = name.lstrip("@")
            if sid not in found:
                found.append(sid)
        return found

    def listing_groups(self, key: str | None) -> dict[str, Any]:
        """Return the groups a key's session is in, or every group for the owner (no key)."""
        if key:
            sender = self._sender(key, {})
            return {"groups": self.groups_of(sender.info.session_id)}
        return {"groups": [self._group_wire(group) for group in self.store.groups()]}

    def _tell_groups(self, session: Session) -> None:
        entry = self.roster.of(session.number)
        mine = self.groups_of(entry.session_id) if entry is not None and entry.kind == KIND_ZETTCODE else []
        session.push({"op": "groups", "groups": mine})

    def _announce_groups(self) -> None:
        for session in list(self.sessions.values()):
            self._tell_groups(session)
        self._tell_observers({"op": "traffic", "kind": "graph"})

    # -- what was said ----------------------------------------------------------------------------
    def history(self, key: str | None, query: Mapping[str, str]) -> dict[str, Any]:
        """Return stored messages: a session's with one other, a group's, or all of a session's own.

        With a key the asker sees only what it sent or received, or what was said in a group it is in. Without one
        (the broker's owner) ``a`` and ``b`` name the two sessions and any group may be read.

        Raises:
            Refused: ``invalid``, ``unknown``, ``ambiguous``, ``denied``.
        """
        limit = _count(query.get("limit"), DEFAULT_HISTORY)
        if query.get("before") not in (None, "") and _count(query.get("before"), -1) < 1:
            raise Refused("invalid", "before is a message id")
        before = _count(query.get("before"), 0) or None
        group, other = query.get("group"), query.get("with")
        me: str | None = None
        if key:
            sender = self._sender(key, {})
            if sender.external:
                raise Refused("denied", "only a ZettCode session has a history")
            me = sender.info.session_id
        if group:
            name = group_name(group)
            found = self.store.group(name)
            if found is None:
                raise Refused("unknown", f"there is no group #{name}")
            if me is not None and me not in found["members"]:
                raise Refused("denied", f"only a member of #{name} may read it")
            return {"messages": self.store.in_group(name, limit=limit, before=before)}
        if me is None:
            a, b = query.get("a"), query.get("b")
            if not a or not b:
                raise Refused("invalid", "name two sessions: a and b")
            return {
                "messages": self.store.between(self._session_id(a), self._session_id(b), limit=limit, before=before)
            }
        if not other:
            return {"messages": self.store.involving(me, limit=limit, before=before)}
        peer = self._session_id(other)
        if peer == me:
            raise Refused("self", "a session has no conversation with itself")
        return {
            "peer": peer,
            "messages": self.store.between(me, peer, limit=limit, before=before),
        }

    def _session_id(self, name: str) -> str:
        """Return the id a typed name means: a connected session first, then an id the history knows."""
        try:
            return self.roster.resolve(name).session_id
        except Refused as refused:
            if refused.reason != "unknown":
                raise
        clean = name.strip().lstrip("@")
        if SESSION_ID.match(clean) and (self.store.involving(clean, limit=1) or self.store.groups_of(clean)):
            return clean
        found = self.store.session_by_handle(clean.lower())
        if found is None:
            raise Refused("unknown", f"no session called '{name}' is active or in the history")
        return found

    def timeline(self, since: float, until: float, limit: int) -> dict[str, Any]:
        """Return the messages of a stretch of the past, oldest first, for a front end to replay on screen.

        Nothing is sent again: this is only what was stored. When more than ``limit`` messages fall in the stretch the
        newest are returned and ``truncated`` says so, so that a replay can say it is missing the start of the stretch
        rather than draw a flow that is quietly incomplete.
        """
        # One less than the most a read may return, so that the extra row asked for below is always really read: at the
        # cap itself the count could never exceed the limit, and a stretch of fifty thousand would be called complete.
        limit = max(1, min(limit, MAX_WINDOW - 1))
        found = self.store.window(since, until, limit=limit + 1)
        truncated = len(found) > limit
        span = self.store.span()
        return {
            "messages": found[-limit:] if truncated else found,
            "truncated": truncated,
            "span": list(span) if span else None,
            "now": time.time(),
        }

    def older(self, before: int, limit: int) -> dict[str, Any]:
        """Return the ``limit`` messages stored before id ``before`` (any kind), oldest first, and whether more remain.

        This is what a feed reads when its reader scrolls back past what it holds. Nothing is sent again.
        """
        limit = max(1, min(limit, 200))
        found = self.store.before(before, limit)
        return {"messages": found, "more": bool(found) and self.store.has_before(found[0]["id"])}

    def graph(self) -> dict[str, Any]:
        """Return who is here, the groups, how much each pair has said and the latest messages: the gateway's graph."""
        return {
            "sessions": [entry.to_wire() for entry in self.roster.snapshot()],
            "groups": [self._group_wire(group) for group in self.store.groups()],
            "edges": self.store.edges(),
            "recent": self.store.recent(limit=50),
        }

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

    async def _hand_over(self, recipient: Session, message: dict[str, Any], handle: str) -> dict[str, Any]:
        """Give the recipient the message and turn its ack into what the sender is told."""
        try:
            ack = await recipient.deliver(message, self.ack_timeout)
        except _Gone:
            raise Refused("gone", f"@{handle} is no longer connected") from None
        except asyncio.TimeoutError:
            # The message was handed to the session's queue before the ack was waited for, so a session that has
            # not answered may still read it later; saying "not delivered" would invite a sender to send it twice.
            raise Refused(
                "timeout",
                f"@{handle} did not answer in {self.ack_timeout:g} seconds; it may still receive the message",
            ) from None
        if ack.get("accepted") is not True:
            reason = ack.get("reason")
            said = clean_text(reason)[:300] if isinstance(reason, str) else ""
            if not isinstance(ack.get("accepted"), bool):
                said = "the session's answer was not understood"
            raise Refused("rejected", said or "not accepted")
        disposition = ack.get("disposition")
        # Whether it went as the recipient's own prompt is what the broker decided, which the sender cannot know: the
        # roster it read may be a moment older.
        return {
            "disposition": disposition if isinstance(disposition, str) else "",
            "direct": message.get("direct") is True,
        }

    # -- telling the sessions ---------------------------------------------------------------------
    def _announce(self) -> None:
        """Tell every session who is registered now, and which groups each may write to."""
        for session in list(self.sessions.values()):
            self._tell_roster(session)
            self._tell_groups(session)
        self._tell_observers({"op": "traffic", "kind": "graph"})

    def _tell_roster(self, session: Session) -> None:
        session.push({"op": "roster", "sessions": [entry.to_wire() for entry in self.roster.snapshot()]})


def _picture_weight(line: Mapping[str, Any]) -> int:
    """Return the size, as base64, of the pictures a line carries: a ``deliver`` is the only line that has any."""
    images = line.get("images")
    if not isinstance(images, list):
        return 0
    return sum(len(item.get("data", "")) for item in images if isinstance(item, dict))


def _with_pictures(text: str, count: int) -> str:
    """Return what the history keeps of a message: its words, and how many pictures went with it, never the pictures."""
    if not count:
        return text
    note = f"[{count} picture{'s' if count != 1 else ''}]"
    return f"{text}\n{note}" if text.strip() else note


def _count(raw: object, default: int) -> int:
    """Read a count from a query string; one that is not a number is the default."""
    try:
        return max(0, int(str(raw)))
    except ValueError:
        return default
