"""The gateway: the threads a page lists, what is sent and said in them, and the events that keep the page current.

A *thread* is one session as the page shows it: a daemon this machine runs, another session that is registered with
the broker, or a sender that once wrote to us. Everything about a thread comes from the SDK through :class:`.backend.Backend`
and nothing is stored here but what a page would otherwise forget: which of a thread's messages have been read.

Where the words are. A session's side of the conversation is in its stored conversation (``Backend.history``), and
that is what a thread shows, because a daemon does not always send what it concludes: its last answer may only be in
its own conversation. The broker's part is the control plane -- whether a message was taken, who is there, that
something arrived -- and the message a session sends us is shown from the stored conversation too, once, and not twice.
Only a sender with no stored conversation (a program that registered as external) is shown from what reached us.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import os
import re
import time
import unicodedata
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zettcode import __version__
from zettcode.sdk.errors import (
    ConfigurationError,
    DaemonStartError,
    SendError,
    SessionLockedError,
    SessionNotFoundError,
    ZettCodeError,
)
from zettcode.sdk.types import DaemonInfo, IncomingMessage, Peer, Receipt, StreamEvent, is_direct_notice

from .backend import Backend
from .chat import items_of, preview, spoken, with_reply_request
from .settings import Settings

#: Seconds between two looks at the daemons, the roster and the stored conversations when nothing woke the watcher.
POLL_SECONDS = 1.5

#: How long a probe of "does another process have this session open" is kept before it is asked again.
LOCK_PROBE_SECONDS = 5.0

#: The most of one turn's answer kept to show a page that opens in the middle of it, and how many tool calls.
LIVE_TEXT_LIMIT = 200_000
LIVE_TOOL_LIMIT = 40

#: A turn that has said nothing for this long while its session says it is idle is taken to have ended unseen.
LIVE_STALE_SECONDS = 4.0

#: How many notes about a session's failed direct turns a chat keeps.
NOTE_LIMIT = 4

#: The most messages kept from senders that have no stored conversation, per sender.
INBOX_LIMIT = 200

#: The most items a thread returns unless asked for all of them.
ITEM_LIMIT = 400

#: The longest a daemon's label may be.
NAME_LIMIT = 40

#: A session id as the store writes them.
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: The HTTP status of each reason a send can fail for; anything else is the sender's mistake.
SEND_STATUS = {
    "offline": 503,
    "unknown": 404,
    "ambiguous": 409,
    "gone": 410,
    "busy": 503,
    "rejected": 409,
    "rate": 429,
    "too_long": 413,
    "empty": 400,
    "timeout": 504,
    "lost": 504,
    "loop": 422,
}


class GatewayError(Exception):
    """A request the gateway refuses, as a status, a code a page can branch on and a sentence for a person."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        """Return the body the page receives."""
        return {"error": {"code": self.code, "message": str(self), **self.extra}}


@dataclass(slots=True)
class Meta:
    """What was learned from a thread's stored conversation the last time it changed."""

    stamp: tuple[int, int] | None = None
    preview: str = ""
    spoken: int = 0
    updated: float = 0.0
    opened: bool = False


class Gateway:
    """The gateway's state and its rules. One per process."""

    def __init__(
        self,
        backend: Backend,
        settings: Settings,
        *,
        poll: float = POLL_SECONDS,
        clock: Any = time.time,
    ) -> None:
        """Hold a backend; nothing is read until :meth:`start`."""
        self.backend = backend
        self.settings = settings
        self.poll = poll
        self.clock = clock
        self._probes: dict[str, tuple[float, bool]] = {}
        #: What the turn running in each session has said so far, by session: for a page that opens in the middle of it.
        self._live: dict[str, dict[str, Any]] = {}
        self._finishing: set[asyncio.Task[None]] = set()
        self._turns = itertools.count(1)
        #: What a session said when a direct turn of ours ended without an answer: shown in its chat until we write again.
        self._notes: dict[str, list[str]] = {}
        #: The sessions we asked to see the turns of, so one that is no longer listed can be let go of.
        self._watching: set[str] = set()
        self.roots = tuple(root.expanduser().resolve() for root in settings.roots)
        self._views: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, Meta] = {}
        self._inbox: dict[str, deque[dict[str, Any]]] = {}
        self._senders: dict[str, str] = {}
        self._seen: dict[str, int] = self._load_seen()
        self._created: set[str] = set()
        self._sent: deque[float] = deque()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._watcher: asyncio.Task[None] | None = None
        self._reachable: bool | None = None

    # -- life -------------------------------------------------------------------------------------
    async def start(self, *, watch: bool = True) -> None:
        """Join the broker and begin watching; a test that wants to say when the gateway looks passes ``watch=False``."""
        await self.backend.start(self._received, self._wake_up)
        self.backend.on_stream(self._streamed)
        await self.refresh()
        if watch:
            self._watcher = asyncio.ensure_future(self._watch())

    async def close(self) -> None:
        """Stop watching and leave the broker."""
        finishing = list(self._finishing)
        for task in finishing:
            task.cancel()
        await asyncio.gather(*finishing, return_exceptions=True)
        watcher, self._watcher = self._watcher, None
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await self.backend.close()

    def _wake_up(self) -> None:
        self._wake.set()

    async def _watch(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a look that fails is tried again, and the page keeps what it has
                pass
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.poll)
            self._wake.clear()
            await asyncio.sleep(0.05)

    # -- what is there ----------------------------------------------------------------------------
    async def refresh(self) -> None:
        """Look at the daemons, the roster and the stored conversations once, and tell the pages what moved."""
        async with self._lock:
            daemons = {item.session_id: item for item in await asyncio.to_thread(self.backend.daemons)}
            mine = self.backend.gateway_id
            peers = {item.session_id: item for item in self.backend.peers() if item.session_id != mine}
            for session_id in peers:
                if session_id not in self._watching:
                    self._watching.add(session_id)
                    self.backend.watch(session_id)  # costs a session nothing until it works
            for gone in self._watching - peers.keys():
                self._watching.discard(gone)
                self.backend.unwatch(gone)  # every run is a new id: they would add up, and the broker caps them
            order = list(dict.fromkeys([*daemons, *peers, *self._inbox]))
            views: dict[str, dict[str, Any]] = {}
            moved: list[str] = []
            for session_id in order:
                daemon, peer = daemons.get(session_id), peers.get(session_id)
                meta = self._meta.setdefault(session_id, Meta())
                workspace = self._workspace_of(daemon, peer)
                stamp = self.backend.stamp(session_id, workspace) if workspace else None
                if stamp != meta.stamp:
                    # A session that is working changes its file all the time and is read when it goes quiet, so a
                    # long conversation is not parsed every look; one nobody is looking at is not read at all.
                    # A daemon is only different when nobody is running it: its record outlives its process, so a
                    # dead or offline daemon still has a conversation to show, while a working one is a peer.
                    working = peer is not None and peer.status == "working"
                    reading = meta.opened or peer is None or not working
                    if reading:
                        await self._learn(session_id, workspace, stamp, meta, wanted=True)
                        moved.append(session_id)
                views[session_id] = self._view(session_id, daemon, peer, meta)
            expired = self._expire_live(peers)
            for gone in {*self._meta, *self._probes, *self._notes} - views.keys():
                self._meta.pop(gone, None)
                self._probes.pop(gone, None)
                self._notes.pop(gone, None)
            reachable = self.backend.reachable
            changed = views != self._views
            self._views = views
        if changed or reachable != self._reachable:
            if reachable and self._reachable is False:
                # Pieces of every turn were missed while the broker was away: a bubble resumed mid-answer would be a
                # truncated one, so what is shown live is dropped and the next ``begin`` starts it again.
                for lost in list(self._live):
                    del self._live[lost]
                    self._publish({"type": "stream", "id": lost, "event": {"kind": "end"}})
            self._reachable = reachable
            self._publish({"type": "threads", "threads": self.threads(), "status": self.status()})
        for session_id in moved:
            self._publish({"type": "thread", "id": session_id})
        # After what was stored has been announced, as at the end of a turn that was heard: the page has the message
        # before the live one goes.
        for session_id in expired:
            self._publish({"type": "stream", "id": session_id, "event": {"kind": "end"}})

    @staticmethod
    def _workspace_of(daemon: DaemonInfo | None, peer: Peer | None) -> str:
        if daemon is not None and daemon.workspace:
            return daemon.workspace
        return peer.workspace if peer is not None else ""

    async def _learn(
        self, session_id: str, workspace: str, stamp: tuple[int, int] | None, meta: Meta, *, wanted: bool
    ) -> None:
        """Take in a thread's stored conversation: its last words and how much it has said to us."""
        meta.stamp = stamp
        meta.updated = stamp[0] / 1e9 if stamp else 0.0
        if stamp is None or not wanted:
            return
        try:
            messages = await self.backend.history(session_id, workspace)
        except (SessionNotFoundError, ZettCodeError, OSError):
            return
        items = items_of(messages, self.backend.gateway_id, handle=self.backend.handle)
        meta.preview = preview(items)
        meta.spoken = spoken(items)
        self._baseline(session_id, meta.spoken)

    def _baseline(self, session_id: str, count: int) -> None:
        """Count what a thread said before the page first saw it as read, unless we started the thread ourselves."""
        if session_id not in self._seen:
            self._seen[session_id] = 0 if session_id in self._created else count
            self._save_seen()

    def _view(self, session_id: str, daemon: DaemonInfo | None, peer: Peer | None, meta: Meta) -> dict[str, Any]:
        """Return one thread as a page lists it."""
        sender = self._senders.get(session_id, session_id[:8])
        if daemon is not None:
            kind = "daemon"
        elif peer is not None:
            kind = "external" if peer.kind == "external" else "session"
        else:
            kind = "external" if session_id.startswith("external:") else "session"
        title = (daemon.title if daemon is not None else None) or (peer.title if peer is not None else "")
        name = (daemon.name if daemon is not None else None) or title or (peer.handle if peer else "") or sender
        stored = meta.stamp is not None
        said = meta.spoken if stored else len(self._inbox.get(session_id, ()))
        # A stored conversation that is new to us is read up to now (see ``_baseline``); what reached us in this run is
        # all newer than the gateway.
        unread = max(0, said - self._seen.get(session_id, said if stored else 0))
        last = self._inbox[session_id][-1]["text"] if not stored and self._inbox.get(session_id) else ""
        return {
            "id": session_id,
            "kind": kind,
            "name": name,
            "handle": peer.handle if peer is not None else "",
            "title": title,
            "workspace": self._workspace_of(daemon, peer),
            "status": self._status(daemon, peer),
            "online": peer is not None,
            "model": daemon.model if daemon is not None else None,
            "effort": daemon.effort if daemon is not None else None,
            "permission": daemon.permission if daemon is not None else None,
            "pid": daemon.pid if daemon is not None else 0,
            "started_at": daemon.started_at if daemon is not None else 0.0,
            "updated_at": meta.updated or (daemon.started_at if daemon is not None else 0.0),
            "preview": meta.preview or _short(str(last)),
            "unread": unread,
            "direct": peer is not None and peer.direct,
            "locked": peer is None and stored and self._locked(session_id, self._workspace_of(daemon, peer)),
        }

    def _locked(self, session_id: str, workspace: str) -> bool:
        """Return whether another process has an unreachable session open, asked at most every few seconds."""
        now = self.clock()
        at, held = self._probes.get(session_id, (0.0, False))
        if now - at < LOCK_PROBE_SECONDS:
            return held
        try:
            held = bool(workspace) and self.backend.locked(session_id, workspace)
        except Exception:  # noqa: BLE001 - a probe that fails says nothing about the session
            held = False
        self._probes[session_id] = (now, held)
        return held

    async def recheck(self, session_id: str) -> dict[str, Any]:
        """Ask again whether another process still has a session open, and return the thread as it is now."""
        if session_id not in self._views:
            raise GatewayError(404, "not_found", "No such session is listed")
        self._probes.pop(session_id, None)
        await self.refresh()
        view = self._views.get(session_id)  # it may have gone while we looked
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        return view

    @staticmethod
    def _status(daemon: DaemonInfo | None, peer: Peer | None) -> str:
        """Return what a thread is doing: the roster's word when it is registered, the daemon's own otherwise."""
        if peer is not None:
            return "stopping" if daemon is not None and daemon.status == "stopping" else peer.status
        if daemon is None:
            return "offline"
        return daemon.status if daemon.status in ("starting", "stopping", "dead") else "offline"

    # -- what a page asks -------------------------------------------------------------------------
    def threads(self) -> list[dict[str, Any]]:
        """Return the threads, the most recently active first and the dead ones last."""
        return sorted(self._views.values(), key=lambda view: (view["status"] == "dead", -float(view["updated_at"])))

    def status(self) -> dict[str, Any]:
        """Return the gateway itself: who it is, whether the broker is there, and how much it may still send."""
        limits = self.backend.limits
        used = self._spent(limits.rate_window)
        return {
            "version": __version__,
            "gateway": {"id": self.backend.gateway_id, "handle": self.backend.handle},
            "broker": {"reachable": self.backend.reachable},
            "limits": {
                "max_text": limits.max_text,
                "rate_limit": limits.rate_limit,
                "rate_window": limits.rate_window,
                "used": used,
            },
        }

    def config(self) -> dict[str, Any]:
        """Return what the new-daemon form and the settings pages need to know."""
        try:
            models = self.backend.models()
        except ValueError as error:
            raise GatewayError(500, "config", str(error)) from error
        return {
            "version": __version__,
            "roots": [str(root) for root in self.roots],
            "allow_full": self.settings.allow_full,
            "permissions": ["deny", "safe", "full"],
            "models": [
                {
                    "name": model.name,
                    "model": model.model,
                    "default": index == 0,
                    "context_window": model.context_window,
                    "multimodal": model.multimodal,
                    "efforts": list(model.efforts),
                    "api": model.api,
                }
                for index, model in enumerate(models)
            ],
        }

    async def thread(self, session_id: str, *, everything: bool = False) -> dict[str, Any]:
        """Return a thread and its conversation as chat items."""
        view = self._views.get(session_id)
        if view is None:
            await self.refresh()
            view = self._views.get(session_id)
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        meta = self._meta.setdefault(session_id, Meta())
        meta.opened = True
        items: list[dict[str, Any]] = []
        stored = False
        if view["workspace"]:
            try:
                messages = await self.backend.history(session_id, view["workspace"])
            except (SessionNotFoundError, ZettCodeError, OSError):
                messages = []
            else:
                stored = True
            items = items_of(messages, self.backend.gateway_id, handle=self.backend.handle)
            if stored:
                meta.preview, meta.spoken = preview(items), spoken(items)
                self._baseline(session_id, meta.spoken)
        if not items:
            items = [dict(item) for item in self._inbox.get(session_id, ())]
        total = len(items)
        if not everything and total > ITEM_LIMIT:
            items = items[-ITEM_LIMIT:]
        # A turn that ended without an answer is not in the stored conversation, and the person is told here.
        notes = [{"kind": "note", "text": text} for text in self._notes.get(session_id, ())]
        items.extend(notes)
        total += len(notes)
        return {
            "thread": self._views.get(session_id, view),
            "items": items,
            "total": total,
            "truncated": total > len(items),
            "live": self._live_view(session_id),
        }

    async def read(self, session_id: str) -> None:
        """Mark everything a thread has said as read."""
        view = self._views.get(session_id)
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        meta = self._meta.setdefault(session_id, Meta())
        stored = meta.stamp is not None
        self._seen[session_id] = meta.spoken if stored else len(self._inbox.get(session_id, ()))
        self._save_seen()
        await self.refresh()

    # -- sending ----------------------------------------------------------------------------------
    async def send(self, session_id: str, text: str, *, reply: bool | None = None) -> dict[str, Any]:
        """Send a message to a thread and return who took it and what became of it.

        Args:
            session_id: The thread.
            text: What the person typed.
            reply: Whether to ask the agent to answer with ``send_message``. By default a daemon is asked, since it
                has nobody to answer to otherwise, and a session with a person at it is not.

        Raises:
            GatewayError: The message is empty or too long, the thread is not there, this gateway has used up what
                the broker allows, or the broker refused. A reason of ``timeout`` or ``lost`` means the message may
                or may not have arrived (``uncertain``), and nothing here sends it again.
        """
        view = self._views.get(session_id)
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        text = text.replace("\r\n", "\n").strip()
        if not text:
            raise GatewayError(400, "empty", "A message needs some text")
        if not view["online"]:
            raise GatewayError(409, "offline", f"{view['name']} is not connected, so it cannot be written to")
        # A session that runs the text as its own prompt answers by itself, and the broker brings the answer back; one that
        # does not is a colleague to be asked, and a daemon has nobody to answer to otherwise.
        direct = bool(view["direct"])
        asked = False if direct else (view["kind"] == "daemon" if reply is None else reply)
        body = with_reply_request(text, self.backend.gateway_id) if asked else text
        limits = self.backend.limits
        if len(body) > limits.max_text:
            room = max(0, limits.max_text - (len(body) - len(text)))
            raise GatewayError(413, "too_long", f"A message is limited to {room} characters here", limit=room)
        self._spend(limits.rate_limit, limits.rate_window)
        self._notes.pop(session_id, None)
        try:
            delivered = await self.backend.send(session_id, body, direct=direct)
        except SendError as error:
            raise GatewayError(
                SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
                uncertain=error.reason in ("timeout", "lost"),
            ) from error
        self._wake_up()
        return {"to": delivered.to, "disposition": delivered.disposition, "direct": delivered.direct}

    def _spent(self, window: float) -> int:
        now = self.clock()
        while self._sent and now - self._sent[0] > window:
            self._sent.popleft()
        return len(self._sent)

    def _spend(self, limit: int, window: float) -> None:
        """Count a send against what the broker allows, and refuse it here when that is used up."""
        if self._spent(window) >= limit:
            wait = max(1, int(window - (self.clock() - self._sent[0])) + 1)
            raise GatewayError(
                429, "rate", f"At most {limit} messages a minute can be sent; try again in {wait}s", retry_after=wait
            )
        self._sent.append(self.clock())

    def _received(self, message: IncomingMessage) -> Receipt:
        """Take a message a session sent to this gateway: keep it for a thread that has no stored conversation."""
        if is_direct_notice(message.text):
            # Said about a turn of ours that ended without an answer: a note in that chat, not a message to be read (the
            # conversation is stored, and a message here would show the line twice). A few are kept: any session can send one.
            notes = self._notes.setdefault(message.sender_id, [])
            notes[:] = [*notes, message.text][-NOTE_LIMIT:]
            self._senders[message.sender_id] = message.sender
            self._publish({"type": "thread", "id": message.sender_id})
            # Told like any message that arrives, so a failure is noticed when the chat is not open: it adds no item to
            # the conversation (that is the note), only the notification.
            self._publish(
                {
                    "type": "inbound",
                    "id": message.sender_id,
                    "sender": message.sender,
                    "text": _short(message.text, 140),
                }
            )
            return Receipt(True, disposition="delivered")
        box = self._inbox.setdefault(message.sender_id, deque(maxlen=INBOX_LIMIT))
        box.append({"kind": "in", "text": message.text, "via": message.via, "sender": message.sender})
        self._senders[message.sender_id] = message.sender
        self._publish(
            {
                "type": "inbound",
                "id": message.sender_id,
                "sender": message.sender,
                "text": _short(message.text, 140),
            }
        )
        self._wake_up()
        return Receipt(True, disposition="delivered")

    # -- daemons ----------------------------------------------------------------------------------
    async def spawn(self, form: Mapping[str, Any]) -> dict[str, Any]:
        """Start a daemon as the form says and return its thread, and how its first message went if it had one."""
        workspace = self.workspace(str(form.get("workspace") or ""))
        permission = str(form.get("permission") or "safe")
        if permission not in ("deny", "safe", "full"):
            raise GatewayError(400, "invalid", "The shell level is deny, safe or full")
        if permission == "full" and not self.settings.allow_full:
            raise GatewayError(
                403, "forbidden", "Starting a daemon with the full shell level was not allowed when the gateway started"
            )
        model, effort = self._model_and_effort(form.get("model"), form.get("effort"))
        resume = form.get("resume") or None
        if resume is not None and not (isinstance(resume, str) and SESSION_ID.match(resume)):
            raise GatewayError(400, "invalid", "A session to resume is named by its id")
        try:
            info = await self.backend.spawn(
                workspace,
                model=model,
                effort=effort,
                resume=resume,
                name=_label(form.get("name")),
                permission=permission,
            )
        except DaemonStartError as error:
            raise GatewayError(502, "start_failed", str(error)) from error
        except SessionLockedError as error:
            raise GatewayError(409, "locked", str(error)) from error
        except ConfigurationError as error:
            raise GatewayError(400, "invalid", str(error)) from error
        self._created.add(info.session_id)
        await self.refresh()
        answer: dict[str, Any] = {"thread": self._views.get(info.session_id)}
        first = str(form.get("message") or "").strip()
        if first:
            answer["first"] = await self._first_message(info.session_id, first)
        return answer

    async def _first_message(self, session_id: str, text: str) -> dict[str, Any]:
        """Send the first message of a new daemon once the broker lists it; a failure is reported, not raised."""
        for _ in range(50):
            if any(peer.session_id == session_id for peer in self.backend.peers()):
                break
            await asyncio.sleep(0.1)
        await self.refresh()
        try:
            return {"ok": True, **await self.send(session_id, text)}
        except GatewayError as error:
            return {"ok": False, **error.to_dict()}

    async def stop(self, session_id: str) -> dict[str, str]:
        """Stop a daemon and remove its record; its conversation stays."""
        if not SESSION_ID.match(session_id):
            raise GatewayError(400, "invalid", "A daemon is named by its session id")
        try:
            said = await self.backend.stop(session_id)
        except SessionNotFoundError as error:
            raise GatewayError(404, "not_found", str(error)) from error
        await self.refresh()
        return {"result": said}

    async def log(self, session_id: str) -> dict[str, Any]:
        """Return the end of a daemon's own log."""
        try:
            text = await asyncio.to_thread(self.backend.log, session_id, 300)
        except SessionNotFoundError as error:
            raise GatewayError(404, "not_found", str(error)) from error
        return {"text": text}

    def _model_and_effort(self, model: object, effort: object) -> tuple[str | None, str | None]:
        models = self.backend.models()
        chosen = str(model) if model else None
        if chosen is None:
            if effort:
                chosen_info = models[0] if models else None
            else:
                return None, None
        else:
            chosen_info = next((item for item in models if item.name == chosen), None)
            if chosen_info is None:
                raise GatewayError(400, "invalid", f"No model is called {chosen!r}")
        level = str(effort) if effort else None
        if level is not None and (chosen_info is None or level not in chosen_info.efforts):
            raise GatewayError(400, "invalid", f"{chosen or 'The default model'} has no reasoning level {level!r}")
        return chosen, level

    # -- where agents may work --------------------------------------------------------------------
    def _inside(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.roots)

    def workspace(self, text: str) -> Path:
        """Return the directory a daemon may work in, or refuse: it exists, and lies within a configured root."""
        if not text.strip():
            raise GatewayError(400, "invalid", "A daemon needs a workspace")
        if not self.roots:
            raise GatewayError(403, "forbidden", "The gateway was started with no directories agents may work in")
        path = Path(text).expanduser().resolve()
        if not self._inside(path):
            raise GatewayError(403, "forbidden", "That directory is outside the ones this gateway may start agents in")
        if not path.is_dir():
            raise GatewayError(400, "invalid", f"No such directory: {path}")
        return path

    def browse(self, text: str) -> dict[str, Any]:
        """List the directories under a path, for the page's folder picker.

        With no path, the person's home directory when it is allowed, and the roots themselves when it is not.
        """
        if not text.strip():
            home = Path.home().resolve()
            if self._inside(home):
                return self.browse(str(home))
            return {"path": "", "parent": None, "dirs": [{"name": str(root), "path": str(root)} for root in self.roots]}
        path = self.workspace(text)
        try:
            children = sorted(
                (child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")),
                key=lambda child: child.name.lower(),
            )
        except OSError as error:
            raise GatewayError(403, "forbidden", f"That directory cannot be read: {error.strerror or error}") from error
        if path == path.parent:
            parent: str | None = None  # the top of the filesystem
        elif path in self.roots:
            parent = ""  # back to the list of roots
        else:
            parent = str(path.parent)
        return {
            "path": str(path),
            "parent": parent,
            "dirs": [{"name": child.name, "path": str(child)} for child in children[:300]],
        }

    # -- events -----------------------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Return a queue of events, starting with the state of everything, for one connected page."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        queue.put_nowait({"type": "threads", "threads": self.threads(), "status": self.status()})
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Forget a page that has gone."""
        self._subscribers.discard(queue)

    # -- a turn as it happens ---------------------------------------------------------------------
    def _streamed(self, event: StreamEvent) -> None:
        """Take one thing a watched session's turn said: keep it for a page that opens later, and pass it on."""
        session_id = event.session_id
        if session_id == self.backend.gateway_id:
            return
        live = self._live.get(session_id)
        kind = event.kind
        if kind == "begin":
            live = self._live[session_id] = self._new_turn()
        elif kind == "end":
            self._finish_later(session_id, live["turn"] if live is not None else None)
            return
        elif live is None:
            live = self._live[session_id] = self._new_turn()
        live["at"] = self.clock()
        wire: dict[str, Any] = {"kind": kind}
        if kind == "text":
            live["thinking"] = False
            live["text"] = (live["text"] + event.text)[-LIVE_TEXT_LIMIT:]
            wire["text"] = event.text
        elif kind == "thinking":
            live["thinking"] = True
        elif kind == "tool":
            live["thinking"] = False
            live["tools"] = [
                *live["tools"],
                {"id": event.call_id, "name": event.name, "brief": event.brief, "ok": None},
            ][-LIVE_TOOL_LIMIT:]
            wire.update(id=event.call_id, name=event.name, brief=event.brief)
        elif kind == "tool_end":
            for tool in live["tools"]:
                if tool["id"] == event.call_id:
                    tool["ok"] = event.ok
            wire.update(id=event.call_id, ok=event.ok)
        self._publish({"type": "stream", "id": session_id, "event": wire})

    def _new_turn(self) -> dict[str, Any]:
        """Return the state of a turn that has just been seen to begin, marked so its end is told from the next one's."""
        return {"turn": next(self._turns), "text": "", "thinking": False, "tools": [], "at": self.clock()}

    def _live_view(self, session_id: str) -> dict[str, Any] | None:
        """Return the turn running in a session as a page reads it (without the gateway's own bookkeeping)."""
        live = self._live.get(session_id)
        return None if live is None else {key: value for key, value in live.items() if key not in ("at", "turn")}

    def _finish_later(self, session_id: str, turn: int | None) -> None:
        task = asyncio.ensure_future(self._finish(session_id, turn))
        self._finishing.add(task)
        task.add_done_callback(self._finishing.discard)

    async def _finish(self, session_id: str, turn: int | None) -> None:
        """The turn ended: read what it wrote first, so the page has the stored message before the live one goes.

        Reading yields, and the session may begin its next turn meanwhile: that one is not this one's to end, and one
        that was already dropped (its session vanished) has been ended for the pages.
        """
        with contextlib.suppress(Exception):
            await self.refresh()
        live = self._live.get(session_id)
        if live is not None and live["turn"] == turn:
            del self._live[session_id]
            self._publish({"type": "stream", "id": session_id, "event": {"kind": "end"}})
        self._publish({"type": "thread", "id": session_id})

    def _expire_live(self, peers: dict[str, Peer]) -> list[str]:
        """Drop a live turn whose session has gone, or has been idle and silent: its end was never heard.

        Returns the sessions it dropped, for the caller to tell the pages once what was stored has been announced.
        """
        now = self.clock()
        expired: list[str] = []
        for session_id, live in list(self._live.items()):
            peer = peers.get(session_id)
            if peer is None or (peer.status != "working" and now - float(live["at"]) > LIVE_STALE_SECONDS):
                del self._live[session_id]
                expired.append(session_id)
        return expired

    def _publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A page that stopped reading is dropped, and told to go: its socket is closed so that it reconnects and
                # asks for everything again, instead of sitting on stale data believing it is live.
                self._subscribers.discard(queue)
                with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                    queue.get_nowait()
                    queue.put_nowait({"type": "close"})

    # -- what the page remembers ------------------------------------------------------------------
    def _seen_path(self) -> Path:
        return self.settings.directory / "ui.json"

    def _load_seen(self) -> dict[str, int]:
        try:
            data = json.loads(self._seen_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        seen = data.get("seen") if isinstance(data, dict) else None
        if not isinstance(seen, dict):
            return {}
        return {key: value for key, value in seen.items() if isinstance(key, str) and isinstance(value, int)}

    def _save_seen(self) -> None:
        """Write which messages have been read; a failure only costs the marks, so it is not raised."""
        path = self._seen_path()
        temporary = path.with_name(f".ui.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"seen": self._seen}), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass


def _short(text: str, limit: int = 90) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "\u2026"


def _label(value: object) -> str | None:
    """Return a daemon's label cleaned of control characters and cut to size, or ``None`` when nothing is left."""
    if not isinstance(value, str):
        return None
    kept = "".join(char for char in value if unicodedata.category(char)[0] != "C" or char == " ")
    line = " ".join(kept.split())[:NAME_LIMIT]
    return line or None
