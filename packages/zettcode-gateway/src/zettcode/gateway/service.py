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
import base64
import contextlib
import logging
import re
import time
import unicodedata
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zettcode.broker.protocol import spell_group
from zettcode.sdk.errors import (
    ConfigurationError,
    DaemonStartError,
    SendError,
    SessionLockedError,
    SessionNotFoundError,
    ZettCodeError,
)
from zettcode.sdk.types import (
    IMAGE_TYPES,
    DaemonInfo,
    Image,
    IncomingMessage,
    Message,
    ModelInfo,
    Peer,
    Receipt,
    SendLimits,
    SessionStatsInfo,
    StreamEvent,
    is_direct_notice,
)
from zettcode.version import __version__

from .agents import AgentError, AgentManager
from .backend import Backend
from .chat import first_unread, items_of, preview, spoken, with_reply_request
from .chat import picture_id as picture_name
from .jsonfile import read_json, write_json
from .live import LiveTurns
from .profiles import ProfileError, Profiles
from .settings import Settings

#: Seconds between two looks at the daemons, the roster and the stored conversations when nothing woke the watcher.
POLL_SECONDS = 1.5

#: How long a probe of "does another process have this session open" is kept before it is asked again.
LOCK_PROBE_SECONDS = 5.0

#: How long after its process started a daemon that has not registered yet still counts as starting.
STARTUP_GRACE_SECONDS = 30.0

#: How often the watcher tries again to bring back an external agent on the roster that is not running.
AGENT_RETRY_SECONDS = 10.0

#: How many notes about a session's failed direct turns a chat keeps.
NOTE_LIMIT = 4

#: How many chats' pictures are kept in memory for the page to fetch one by one, and the most bytes of pictures one chat
#: may have kept; a chat with more keeps only their names, and its bytes are read when they are asked for.
PICTURE_CHATS = 4
PICTURE_BYTES = 32 << 20

#: What a picture's name looks like (see :func:`~.chat.picture_id`): anything else is not one, and nothing is read for it.
PICTURE_NAME = re.compile(r"^[0-9a-f]{20}$")

#: The most messages kept from senders that have no stored conversation, per sender.
INBOX_LIMIT = 200

#: The most threads of that kind written to disk: a program that registered once is never listed again to be deleted.
INBOX_THREADS = 50

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
    "invalid": 400,
    "duplicate": 409,
}
#: Why an external agent is not put in a group: two of them would answer each other without end.
EXTERNAL_IN_GROUP = "An external agent cannot be in a group yet: two of them would answer each other without end"


def _group_name(raw: object) -> str:
    """Return a group's name as the broker spells it (``" #Review "`` is ``review``).

    The broker is the authority on what a name may be and refuses a bad one; this only makes every route spell the
    same name the same way, so that the one a page sends is the one it later deletes, leaves or reads. It is the
    broker's own function, so the two cannot drift apart.
    """
    return spell_group(raw)


def _totals_of(stats: SessionStatsInfo) -> dict[str, Any]:
    """Return one session's totals as a page reads them; ``cache_rate`` is ``None`` when its replies did not say."""
    return {
        "requests": stats.requests,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "cache_read_tokens": stats.cache_read_tokens,
        "reasoning_tokens": stats.reasoning_tokens,
        "cache_rate": stats.cache_share,
        "cache_input_tokens": stats.input_tokens if stats.cache_reported else 0,
    }


def _sum_totals(items: Sequence[SessionStatsInfo]) -> dict[str, Any]:
    """Return the totals of several sessions.

    The cached share is taken over the sessions that measured it, so ``cache_input_tokens`` (their input) is what
    ``cache_read_tokens`` is a share of: ``input_tokens`` also counts the sessions that did not say, and a page that
    divides by it gets a lower number than ``cache_rate``.
    """
    measured = [item for item in items if item.cache_reported]
    sent = sum(item.input_tokens for item in measured)
    return {
        "requests": sum(item.requests for item in items),
        "input_tokens": sum(item.input_tokens for item in items),
        "output_tokens": sum(item.output_tokens for item in items),
        "cache_read_tokens": sum(item.cache_read_tokens for item in items),
        "reasoning_tokens": sum(item.reasoning_tokens for item in items),
        "cache_rate": sum(item.cache_read_tokens for item in measured) / sent if sent else None,
        "cache_input_tokens": sent,
    }


def read_pictures(raw: object, limits: SendLimits) -> list[Image]:
    """Read the pictures a page sent (``[{media_type, data}]``, the file in base64) and refuse what the broker would.

    Checked here so that a page is told at once and in its own terms: how many, how large, and of a type a model takes.
    That what a file says it is matches what it is, the broker decides.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise GatewayError(400, "invalid", "images is a list")
    if len(raw) > limits.max_images:
        raise GatewayError(413, "too_long", f"At most {limits.max_images} pictures go with one message")
    pictures: list[Image] = []
    total = 0
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("data"), str):
            raise GatewayError(400, "invalid", "A picture is {media_type, data}")
        kind = item.get("media_type")
        if not isinstance(kind, str) or kind not in IMAGE_TYPES:
            raise GatewayError(400, "invalid", f"A picture is one of: {', '.join(sorted(IMAGE_TYPES))}")
        # Before it is decoded: a file that is too large is turned away for its length, not after it is all in memory.
        if len(item["data"]) > (limits.max_image_bytes + 2) // 3 * 4:
            raise GatewayError(413, "too_long", f"A picture is limited to {limits.max_image_bytes >> 20} MiB")
        try:
            data = base64.b64decode(item["data"], validate=True)
            picture = Image(data, kind)
        except ValueError as error:
            raise GatewayError(400, "invalid", f"A picture could not be read: {error}") from None
        if len(data) > limits.max_image_bytes:
            raise GatewayError(413, "too_long", f"A picture is limited to {limits.max_image_bytes >> 20} MiB")
        total += len(data)
        if total > limits.max_images_bytes:
            raise GatewayError(
                413,
                "too_long",
                f"The pictures of a message are limited to {limits.max_images_bytes >> 20} MiB together",
            )
        pictures.append(picture)
    return pictures


logger = logging.getLogger("zettcode.gateway")


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


#: The keys of a model entry the page may write, each with the type it must have. The token is among them but is only
#: ever written: no response carries it back.
MODEL_FIELDS: dict[str, tuple[type, ...]] = {
    "model": (str,),
    "token": (str,),
    "display_model": (str,),
    "base_url": (str,),
    "anthropic": (bool,),
    "responses_api": (bool,),
    "chat": (bool,),
    "multimodal": (bool,),
    "temperature": (int, float),
    "web_search": (bool,),
    "web_search_name": (str,),
    "context_window": (int,),
    "compact_percent": (int, float),
    "reasoning_efforts": (list,),
}


def model_fields(data: Mapping[str, Any], *, creating: bool) -> dict[str, object]:
    """Return the keys of a model entry a request names, refusing a key or a type the file does not have.

    When creating, a blank string or an unset flag is left out, so the file holds only what was chosen. When changing,
    ``None`` stays: it means remove the key, which is how a temperature goes back to the provider's own. A blank
    token is dropped in both cases, because the page never shows the stored one and an empty box means keep it.
    """
    out: dict[str, object] = {}
    for key, value in data.items():
        kinds = MODEL_FIELDS.get(key)
        if kinds is None:
            raise GatewayError(400, "invalid", f"{key} is not a setting of a model")
        if value is None:
            if key in ("model", "token"):
                continue
            if not creating:
                out[key] = None
            continue
        if isinstance(value, bool) != (bool in kinds) or not isinstance(value, kinds):
            raise GatewayError(400, "invalid", f"{key} has the wrong type")
        if isinstance(value, str):
            value = value.strip()
            if key == "token" and not value:
                continue
            if not value:
                if creating:
                    continue
                if key == "model":
                    raise GatewayError(400, "invalid", "The model id cannot be empty")
                out[key] = None
                continue
        if creating and value is False:
            continue
        if key == "reasoning_efforts":
            if not all(isinstance(level, str) for level in value):
                raise GatewayError(400, "invalid", "reasoning_efforts is a list of names")
            if creating and not value:
                continue
        out[key] = value
    if creating and not out.get("model"):
        raise GatewayError(400, "invalid", "A model needs the model id the endpoint expects")
    return out


def model_view(model: ModelInfo, index: int) -> dict[str, Any]:
    """Return one model as a page shows it. The token is never part of it: the file keeps it, the page only writes it."""
    return {
        "name": model.name,
        "model": model.model,
        "display_model": model.display_model,
        "default": index == 0,
        "context_window": model.context_window,
        "compact_percent": model.compact_percent,
        "multimodal": model.multimodal,
        "efforts": list(model.efforts),
        "api": model.api,
        "base_url": model.base_url,
        "temperature": model.temperature,
        "web_search": model.web_search,
        "web_search_name": model.web_search_name,
        "can_search": model.can_search,
    }


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
        agents: AgentManager | None = None,
    ) -> None:
        """Hold a backend; nothing is read until :meth:`start`."""
        self.backend = backend
        self.settings = settings
        self.agents = agents if agents is not None else AgentManager(settings.directory)
        self.poll = poll
        self.clock = clock
        self._probes: dict[str, tuple[float, bool]] = {}
        #: What the turn running in each session has said so far, for a page that opens in the middle of it. It reads the
        #: clock through ``self.clock`` each time, so a clock replaced after construction is the one it sees.
        self._live = LiveTurns(lambda: self.clock())
        self._finishing: set[asyncio.Task[None]] = set()
        #: What a session said when a direct turn of ours ended without an answer: shown in its chat until we write again.
        self._notes: dict[str, list[str]] = {}
        #: The pictures of the chats last read, by chat and then by name, oldest chat first.
        self._pictures: dict[str, dict[str, tuple[bytes | None, str]]] = {}
        #: The sessions we asked to see the turns of, so one that is no longer listed can be let go of.
        self._watching: set[str] = set()
        self.roots = tuple(root.expanduser().resolve() for root in settings.roots)
        self._views: dict[str, dict[str, Any]] = {}
        #: What a person made of each thread (name, picture, pin, archive). It reads the clock through ``self.clock`` each
        #: time, so a clock replaced after construction is the one its one-day expiry uses.
        self._profiles = Profiles(settings.directory, lambda: self.clock())
        self._meta: dict[str, Meta] = {}
        self._inbox: dict[str, deque[dict[str, Any]]] = {}
        #: Messages of ours in a thread's box that no session has taken yet, by identity: they are not written out.
        self._unsent: list[dict[str, Any]] = []
        self._senders: dict[str, str] = {}
        self._seen: dict[str, int] = self._load_seen()
        self._load_inbox()
        self._created: set[str] = set()
        #: Daemons a restart is starting right now, so a second press is told so rather than racing the first.
        self._restarting: set[str] = set()
        self._sent: deque[float] = deque()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        #: Serialises model edits: each is a read-modify-write of one file, so two at once would drop one of them.
        self._models_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._watcher: asyncio.Task[None] | None = None
        self._reachable: bool | None = None
        #: The task that brings back external agents that are not running (see :meth:`_keep_agents`).
        self._keeper: asyncio.Task[None] | None = None
        #: The last failed refresh, so a permanent fault does not append a
        #: traceback every poll interval.
        self._refresh_error: str | None = None

    # -- life -------------------------------------------------------------------------------------
    async def start(self, *, watch: bool = True) -> None:
        """Join the broker and begin watching; a test that wants to say when the gateway looks passes ``watch=False``."""
        await self.backend.start(self._received, self._wake_up)
        # The agents the person made before the last stop come back under their own ids, before the first read.
        await self.agents.restore()
        self.backend.on_stream(self._streamed)
        self.backend.observe(self._traffic)
        await self.refresh()
        if watch:
            self._watcher = asyncio.ensure_future(self._watch())
            self._keeper = asyncio.ensure_future(self._keep_agents())

    async def close(self) -> None:
        """Stop watching and leave the broker."""
        self.backend.observe(None)
        finishing = list(self._finishing)
        for task in finishing:
            task.cancel()
        await asyncio.gather(*finishing, return_exceptions=True)
        watcher, self._watcher = self._watcher, None
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        keeper, self._keeper = self._keeper, None
        if keeper is not None:
            keeper.cancel()
            await asyncio.gather(keeper, return_exceptions=True)
        await self.agents.close()
        await self.backend.close()

    def _wake_up(self) -> None:
        self._wake.set()

    async def _watch(self) -> None:
        while True:
            await self._poll_once()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.poll)
            self._wake.clear()
            await asyncio.sleep(0.05)

    async def _keep_agents(self) -> None:
        """Bring back, every :data:`AGENT_RETRY_SECONDS`, an agent on the roster that is not running.

        Its own task and not a step of the watcher: starting one waits for the broker, and a roster of agents that
        cannot start must not hold up every thread update. Only while the broker can be reached, so a gateway that
        started before its broker does not leave the person's agents offline until the next restart.
        """
        while True:
            await asyncio.sleep(AGENT_RETRY_SECONDS)
            if not self.backend.reachable:
                continue
            try:
                back = await self.agents.restore()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the keeper must outlive an agent that will not start
                logger.exception("agents.restore_failed")
                continue
            if back:
                self._wake_up()

    async def _poll_once(self) -> None:
        """Take one refresh step, recording only a failure transition and its recovery."""
        try:
            await self.refresh()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a look that fails is tried again, and the page keeps what it has
            try:
                reason = f"{type(error).__name__}: {error}"
            except Exception:  # noqa: BLE001 - an unprintable error still has a type
                reason = type(error).__name__
            if reason != self._refresh_error:
                logger.exception("refresh.failed")
                self._refresh_error = reason
        else:
            if self._refresh_error is not None:
                logger.info("refresh.recovered")
                self._refresh_error = None

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
            # An external agent this gateway keeps is a thread of its own even when it is not connected, so that the page
            # can say it is offline and offer to start it again instead of the agent vanishing from the list.
            order = list(dict.fromkeys([*daemons, *peers, *self._inbox, *self.agents.kept()]))
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
            expired = self._live.expire(peers)
            for gone in {*self._meta, *self._probes, *self._notes} - views.keys():
                self._meta.pop(gone, None)
                self._probes.pop(gone, None)
                self._notes.pop(gone, None)
            reachable = self.backend.reachable
            changed = views != self._views
            self._views = views
            self._profiles.forget_vanished(views.keys())
        if changed or reachable != self._reachable:
            if reachable and self._reachable is False:
                # Pieces of every turn were missed while the broker was away: a bubble resumed mid-answer would be a
                # truncated one, so what is shown live is dropped and the next ``begin`` starts it again.
                for lost, number in self._live.drop_all():
                    self._publish({"type": "stream", "id": lost, "event": {"kind": "end", "turn": number}})
            self._reachable = reachable
            self._publish({"type": "threads", "threads": self.threads(), "status": self.status()})
        for session_id in moved:
            self._publish({"type": "thread", "id": session_id})
        # After what was stored has been announced, as at the end of a turn that was heard: the page has the message
        # before the live one goes.
        for session_id, turn in expired:
            self._publish({"type": "stream", "id": session_id, "event": {"kind": "end", "turn": turn}})

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
        profiled = self._profiles.read(session_id)
        title = (
            profiled.get("name")
            or (daemon.title if daemon is not None else None)
            or (peer.title if peer is not None else "")
            # An agent this gateway keeps has the title it was given, also while it is not connected.
            or self.agents.title_of(session_id)
        )
        name = (
            profiled.get("name")
            or (daemon.name if daemon is not None else None)
            or title
            or (peer.handle if peer else "")
            or sender
        )
        stored = meta.stamp is not None
        box = () if stored else tuple(self._inbox.get(session_id, ()))
        # What a thread said to us: the conversation's own count, or the part of what the gateway kept that the session
        # said. What this page wrote is in the box too, and is not something to read.
        said = meta.spoken if stored else spoken(box)
        # A stored conversation that is new to us is read up to now (see ``_baseline``); what reached us in this run is
        # all newer than the gateway.
        unread = max(0, said - self._seen.get(session_id, said if stored else 0))
        last = preview(box) if box else ""
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
            "avatar": profiled.get("avatar") or self.agents.avatar_for(session_id),
            "agent": self.agents.kind_of(session_id),
            "pinned": profiled.get("pinned") == "1",
            "archived": profiled.get("archived") == "1",
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

    def _status(self, daemon: DaemonInfo | None, peer: Peer | None) -> str:
        """Return what a thread is doing: the roster's word when it is registered, the daemon's own otherwise.

        A daemon whose process was started moments ago has not registered with the broker yet, and its state file may
        not say ``starting`` yet either: that is starting, not "not connected".
        """
        if peer is not None:
            return "stopping" if daemon is not None and daemon.status == "stopping" else peer.status
        if daemon is None:
            return "offline"
        if daemon.status in ("starting", "stopping", "dead"):
            return daemon.status
        if daemon.started_at and 0 <= self.clock() - daemon.started_at < STARTUP_GRACE_SECONDS:
            return "starting"
        return "offline"

    # -- what a page asks -------------------------------------------------------------------------
    async def update_profile(self, session_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """Set a thread's display name, picture, and whether it is pinned or archived; an empty value removes an override."""
        if session_id not in self._views:
            await self.refresh()
        if session_id not in self._views:
            raise GatewayError(404, "not_found", "No such session is listed")
        try:
            self._profiles.change(session_id, data)
        except ProfileError as error:
            raise GatewayError(400, "invalid", str(error)) from error
        await self.refresh()
        return {"thread": self._views.get(session_id)}

    def threads(self) -> list[dict[str, Any]]:
        """Return the threads: pinned ones first, then the online ones, each run with the most recently active first.

        The page splits the list into its Pinned, Groups, Daemons and Other sections itself and keeps this order inside
        each, so the two must agree on what "first" means. Only sessions can be pinned or archived: the flags live in
        a session's profile, and a group (named ``#name``, not a listed session) has none; giving groups the flag
        means deciding its key and this sort together.
        """
        return sorted(
            self._views.values(),
            key=lambda view: (not view["pinned"], not view["online"], -float(view["updated_at"])),
        )

    def status(self) -> dict[str, Any]:
        """Return the gateway itself: who it is, whether the broker is there, and how much it may still send."""
        limits = self.backend.limits
        used = self._spent(limits.rate_window)
        return {
            "version": __version__,
            "gateway": {"id": self.backend.gateway_id, "handle": self.backend.handle},
            "external": self.backend.external,
            "broker": {"reachable": self.backend.reachable},
            "limits": {
                "max_text": limits.max_text,
                "rate_limit": limits.rate_limit,
                "rate_window": limits.rate_window,
                "max_images": limits.max_images,
                "max_image_bytes": limits.max_image_bytes,
                "max_images_bytes": limits.max_images_bytes,
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
            "models": [model_view(model, index) for index, model in enumerate(models)],
        }

    async def add_model(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Write a new model into the configuration file and return the list."""
        entry = model_fields(data, creating=True)
        return await self._edit_models(lambda: self.backend.add_model(entry))

    async def change_model(self, name: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """Change one model of the configuration file; what is not named stays, and so does the token."""
        changes = model_fields(data, creating=False)
        if not changes:
            raise GatewayError(400, "invalid", "Name at least one thing to change")
        return await self._edit_models(lambda: self.backend.update_model(name, changes))

    async def remove_model(self, name: str) -> dict[str, Any]:
        """Remove one model from the configuration file."""
        return await self._edit_models(lambda: self.backend.remove_model(name))

    async def _edit_models(self, edit: Callable[[], list[ModelInfo]]) -> dict[str, Any]:
        """Run a configuration edit off the loop and answer with the list it left.

        A daemon reads the file when it starts, so a change reaches the next one and touches no running session. A
        refusal is the file's own sentence, which names the wrong key, and the file is left as it was. Edits made
        through this gateway run one at a time; one made by a terminal's ``/config`` at the same moment is not seen.
        """
        try:
            async with self._models_lock:
                models = await asyncio.to_thread(edit)
        except ValueError as error:
            raise GatewayError(400, "invalid", str(error)) from error
        except OSError as error:
            raise GatewayError(500, "config", f"The configuration file could not be written: {error}") from error
        return {"models": [model_view(model, index) for index, model in enumerate(models)]}

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
                self._keep_pictures(session_id, messages)
            items = items_of(messages, self.backend.gateway_id, handle=self.backend.handle)
            if stored:
                meta.preview, meta.spoken = preview(items), spoken(items)
                self._baseline(session_id, meta.spoken)
        if not items:
            items = [dict(item) for item in self._inbox.get(session_id, ())]
        total = len(items)
        said = meta.spoken if stored else spoken(self._inbox.get(session_id, ()))
        unread = max(0, said - self._seen.get(session_id, said if stored else 0))
        if not everything and total > ITEM_LIMIT:
            items = items[-ITEM_LIMIT:]
        # Where the unread stretch begins, so that opening the chat scrolls to it: the end of the window when more is
        # unread than the page asked for.
        unread_from = first_unread(items, unread)
        # A turn that ended without an answer is not in the stored conversation, and the person is told here.
        notes = [{"kind": "note", "text": text} for text in self._notes.get(session_id, ())]
        items.extend(notes)
        total += len(notes)
        return {
            "thread": self._views.get(session_id, view),
            "items": items,
            "total": total,
            "truncated": total > len(items),
            "unread_from": unread_from,
            "live": self._live.view(session_id),
        }

    async def read(self, session_id: str) -> None:
        """Mark everything a thread has said as read."""
        view = self._views.get(session_id)
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        meta = self._meta.setdefault(session_id, Meta())
        stored = meta.stamp is not None
        self._seen[session_id] = meta.spoken if stored else spoken(self._inbox.get(session_id, ()))
        self._save_seen()
        await self.refresh()

    # -- sending ----------------------------------------------------------------------------------
    async def send(
        self, session_id: str, text: str, *, reply: bool | None = None, images: object = None
    ) -> dict[str, Any]:
        """Send a message to a thread and return who took it and what became of it.

        Args:
            session_id: The thread.
            text: What the person typed; it may be empty when pictures go with it.
            reply: Whether to ask the agent to answer with ``send_message``. By default a daemon is asked, since it
                has nobody to answer to otherwise, and a session with a person at it is not.
            images: Pictures to send with it, as a page sends them (``[{media_type, data}]``, base64). Only a session
                that runs the text as its own prompt and whose model reads pictures takes them.

        Raises:
            GatewayError: The message is empty or too long, the thread is not there, this gateway has used up what
                the broker allows, or the broker refused. A reason of ``timeout`` or ``lost`` means the message may
                or may not have arrived (``uncertain``), and nothing here sends it again.
        """
        view = self._views.get(session_id)
        if view is None:
            raise GatewayError(404, "not_found", "No such session is listed")
        text = text.replace("\r\n", "\n").strip()
        pictures = read_pictures(images, self.backend.limits)
        if not text and not pictures:
            raise GatewayError(400, "empty", "A message needs some text")
        if not view["online"]:
            raise GatewayError(409, "offline", f"{view['name']} is not connected, so it cannot be written to")
        # A session that runs the text as its own prompt answers by itself, and the broker brings the answer back; one that
        # does not is a colleague to be asked, and a daemon has nobody to answer to otherwise.
        direct = bool(view["direct"])
        if pictures:
            self._check_pictures(view, direct)
        asked = False if direct else (view["kind"] == "daemon" if reply is None else reply)
        body = with_reply_request(text, self.backend.gateway_id) if asked else text
        limits = self.backend.limits
        if len(body) > limits.max_text:
            room = max(0, limits.max_text - (len(body) - len(text)))
            raise GatewayError(413, "too_long", f"A message is limited to {room} characters here", limit=room)
        self._spend(limits.rate_limit, limits.rate_window)
        self._notes.pop(session_id, None)
        # A thread with no store is only what the gateway kept: what this page said is as much a part of it as what the
        # session said, or the page's own message would never settle and would stay at the end for good. It goes in
        # before the message does, so that an answer arriving at once cannot be drawn above its question. A thread with a
        # store shows what was sent once the session writes it, and the page settles its own copy from that.
        entry: dict[str, Any] | None = None
        if not view["workspace"]:
            entry = {"kind": "out", "text": text}
            box = self._inbox.pop(session_id, None) or deque(maxlen=INBOX_LIMIT)
            self._inbox[session_id] = box
            box.append(entry)
            self._unsent.append(entry)
            self._publish({"type": "thread", "id": session_id})
        try:
            delivered = await self.backend.send(session_id, body, direct=direct, images=pictures)
        except BaseException as error:  # noqa: BLE001 - whatever went wrong, the message is not in the thread
            # A refusal, a lost broker, a page that closed mid-send, the gateway shutting down: what was never delivered
            # must not be left looking sent, since the page settles its own copy by finding this one.
            if entry is not None:
                self._take_back(session_id, entry)
            if not isinstance(error, SendError):
                raise
            raise GatewayError(
                SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
                uncertain=error.reason in ("timeout", "lost"),
            ) from error
        self._wake_up()
        if entry is not None:
            self._unsent[:] = [item for item in self._unsent if item is not entry]
            self._save_inbox()
        return {"to": delivered.to, "disposition": delivered.disposition, "direct": delivered.direct}

    def _take_back(self, session_id: str, entry: dict[str, Any]) -> None:
        """Remove one item the gateway kept for a thread, by identity: two messages may say exactly the same thing."""
        self._unsent[:] = [item for item in self._unsent if item is not entry]
        box = self._inbox.get(session_id)
        if box is None:
            return
        for at, item in enumerate(box):
            if item is entry:
                del box[at]
                self._save_inbox()
                return

    def _check_pictures(self, view: Mapping[str, Any], direct: bool) -> None:
        """Refuse pictures for a session that cannot use them, in words a person can act on, before anything is sent."""
        if self.backend.external:
            raise GatewayError(400, "no_pictures", "This gateway is an external session, which cannot send pictures")
        if not direct:
            raise GatewayError(
                400,
                "no_pictures",
                f"{view['name']} cannot be sent a picture: it does not run a chat's text as its own prompt",
            )
        name = view.get("model")
        known = next((model for model in self.backend.models() if model.name == name), None)
        if known is not None and not known.multimodal:
            raise GatewayError(
                400,
                "no_pictures",
                f"{name} does not accept pictures; send the text alone or start a daemon on a model that does",
            )

    async def picture(self, session_id: str, picture_id: str) -> tuple[bytes, str]:
        """Return a picture of a thread's stored conversation by the name its chat item gave it: its bytes and type.

        Reading a conversation decodes every picture in it, so what a chat was last read with is kept — the names of its
        pictures always, and their bytes while they weigh :data:`PICTURE_BYTES` or less — and a page fetching its pictures
        one by one does not read the file once for each. A chat that has been read is the last word on what it holds: a
        name it does not hold is answered without reading anything, so asking for names that are not there costs nothing.
        """
        view = self._views.get(session_id)
        if view is None or not view["workspace"] or not PICTURE_NAME.match(picture_id):
            raise GatewayError(404, "not_found", "No such picture")
        names = self._pictures.get(session_id)
        messages: Sequence[Message] | None = None
        if names is None:
            messages = await self._history_of(session_id, view["workspace"])
            names = self._keep_pictures(session_id, messages)
        found = names.get(picture_id)
        # Whatever the file says, only a type a model takes is served, and the page never lets a browser guess another.
        if found is None or found[1] not in IMAGE_TYPES:
            raise GatewayError(404, "not_found", "No such picture")
        data, kind = found
        if data is None:  # a chat too heavy to keep in memory: its bytes are read when they are asked for
            if messages is None:
                messages = await self._history_of(session_id, view["workspace"])
            data = next(
                (
                    picture.data
                    for message in messages
                    for picture in message.pictures
                    if picture_name(picture.data) == picture_id
                ),
                None,
            )
            if data is None:  # it was in the conversation a moment ago and is not now
                raise GatewayError(404, "not_found", "No such picture")
        return data, kind

    async def _history_of(self, session_id: str, workspace: str) -> Sequence[Message]:
        try:
            return await self.backend.history(session_id, workspace)
        except (SessionNotFoundError, ZettCodeError, OSError):
            raise GatewayError(404, "not_found", "No such picture") from None

    def _keep_pictures(self, session_id: str, messages: Sequence[Message]) -> dict[str, tuple[bytes | None, str]]:
        """Remember the pictures of a conversation by name, for the last few chats, and return them.

        A chat is remembered even when it has none, so that asking it for a picture is answered at once. Its bytes are
        kept only when they come to :data:`PICTURE_BYTES` or less, so a conversation of large pictures cannot pin them.
        """
        found = {
            picture_name(picture.data): (picture.data, picture.media_type)
            for message in messages
            for picture in message.pictures
        }
        light = sum(len(data) for data, _ in found.values()) <= PICTURE_BYTES
        names: dict[str, tuple[bytes | None, str]] = {
            name: (data if light else None, kind) for name, (data, kind) in found.items()
        }
        self._pictures.pop(session_id, None)
        self._pictures[session_id] = names
        while len(self._pictures) > PICTURE_CHATS:
            self._pictures.pop(next(iter(self._pictures)))
        return names

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
        self._senders[message.sender_id] = message.sender
        meta = self._meta.get(message.sender_id)
        if meta is not None and meta.stamp is not None:
            # Its conversation is stored and is what the thread shows: a second copy here would only be written out.
            self._inbox.pop(message.sender_id, None)
        else:
            box = self._inbox.pop(message.sender_id, None) or deque(maxlen=INBOX_LIMIT)
            self._inbox[message.sender_id] = box  # last in order is the most recently active, which the cap keeps
            box.append({"kind": "in", "text": message.text, "via": message.via, "sender": message.sender})
            self._save_inbox()
        # The conversation moved, and only the page with it open can redraw: a thread with a stored conversation is
        # announced by ``refresh``, but one that is only what the gateway kept has no store to see the change in.
        self._publish({"type": "thread", "id": message.sender_id})
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

    async def stop(self, session_id: str, *, force: bool = False) -> dict[str, str]:
        """Stop a daemon; it stays listed as offline, with its conversation, and a working one needs ``force``."""
        if not SESSION_ID.match(session_id):
            raise GatewayError(400, "invalid", "A daemon is named by its session id")
        try:
            said = await self.backend.stop(session_id, force=force)
        except SessionNotFoundError as error:
            raise GatewayError(404, "not_found", str(error)) from error
        except ConfigurationError as error:
            raise GatewayError(409, "busy", str(error)) from error
        await self.refresh()
        return {"result": said}

    async def restart(self, session_id: str) -> dict[str, Any]:
        """Start a stopped daemon again, on its own conversation, as it was: its folder, model, level and label.

        This is what the page's one-click Restart does. Changing any of those is the New form's job (it can be filled in
        from the daemon). A model that has since been removed from the configuration is replaced by the default one,
        and the answer says so in ``note``, rather than refusing to start an agent the person only wants back.
        """
        if not SESSION_ID.match(session_id):
            raise GatewayError(400, "invalid", "A daemon is named by its session id")
        daemon = next((item for item in self.backend.daemons() if item.session_id == session_id), None)
        if daemon is None:
            raise GatewayError(
                404, "not_found", "There is no record of this daemon on the machine; start one from New instead"
            )
        if daemon.status != "dead":
            raise GatewayError(409, "running", "This daemon is not stopped")
        if not daemon.workspace:
            raise GatewayError(409, "no_workspace", "This daemon never recorded its folder; start it again from New")
        try:
            await self.backend.history(session_id, daemon.workspace)
        except SessionNotFoundError:
            # A session is stored when its first message is, so a daemon that was stopped before anyone wrote to it has
            # nothing to continue. Starting one fresh would be a different session under the same name; say so instead.
            raise GatewayError(
                409,
                "nothing_to_resume",
                "It was stopped before it had a conversation, so there is nothing to continue. Delete it and start a "
                "new one from New",
            ) from None
        except (ZettCodeError, OSError):
            pass  # an unreadable store is reported by the start itself, with what the daemon said
        form: dict[str, Any] = {
            "workspace": daemon.workspace,
            "permission": daemon.permission,
            "name": daemon.name,
            "resume": session_id,
        }
        known = {item.name: item for item in self.backend.models()}
        note = ""
        if daemon.model and daemon.model in known:
            form["model"] = daemon.model
            if daemon.effort and daemon.effort in known[daemon.model].efforts:
                form["effort"] = daemon.effort
            elif daemon.effort:
                note = (
                    f"{daemon.model} no longer has the reasoning level {daemon.effort!r}, "
                    "so it started at that model's own level"
                )
        elif daemon.model:
            note = f"The model {daemon.model!r} is no longer configured, so it started on the default one"
        if session_id in self._restarting:
            raise GatewayError(409, "starting", "This daemon is already being started")
        self._restarting.add(session_id)
        try:
            answer = await self.spawn(form)
        finally:
            self._restarting.discard(session_id)
        if note:
            answer["note"] = note
        return answer

    async def delete(self, session_id: str) -> dict[str, str]:
        """Remove a stopped daemon for good: its record and its conversation."""
        if not SESSION_ID.match(session_id):
            raise GatewayError(400, "invalid", "A daemon is named by its session id")
        try:
            said = await self.backend.delete(session_id)
        except SessionNotFoundError as error:
            raise GatewayError(404, "not_found", str(error)) from error
        except ConfigurationError as error:
            raise GatewayError(409, "busy", str(error)) from error
        self._forget(session_id)
        await self.refresh()
        return {"result": said}

    def _forget(self, session_id: str) -> None:
        """Drop what the gateway holds about a session that was deleted, so it is not listed again."""
        if self._inbox.pop(session_id, None):
            self._save_inbox()
        self._senders.pop(session_id, None)
        self._pictures.pop(session_id, None)
        self._notes.pop(session_id, None)
        self._live.drop(session_id)
        if self._seen.pop(session_id, None) is not None:
            self._save_seen()

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
        if event.kind == "end":
            self._finish_later(session_id, self._live.number_of(session_id))
            return
        wire = self._live.hear(event)
        if wire is not None:
            self._publish({"type": "stream", "id": session_id, "event": wire})

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
        if self._live.finish(session_id, turn):
            self._publish({"type": "stream", "id": session_id, "event": {"kind": "end", "turn": turn}})
        self._publish({"type": "thread", "id": session_id})

    # -- the graph --------------------------------------------------------------------------------
    def _traffic(self, line: dict[str, Any]) -> None:
        """Tell the pages what the broker saw: a message that passed, or that who is here (or the groups) changed."""
        if line.get("kind") == "message" and isinstance(line.get("message"), dict):
            self._publish({"type": "traffic", "message": line["message"]})
        elif line.get("kind") == "graph":
            self._publish({"type": "graph"})

    async def graph(self) -> dict[str, Any]:
        """Return who is connected, the groups, how much each pair has said and the latest messages."""
        try:
            return await self.backend.graph()
        except SendError as error:
            raise GatewayError(503, error.reason, str(error)) from error

    async def usage(self) -> dict[str, Any]:
        """Return what every listed session and every group has spent: replies, tokens and the cached share of the input.

        The rows are the sessions this gateway lists that work in a folder (a daemon, or a terminal session); an external
        agent is the program's own and has no ledger. A group is the sum of its members that were measured, and says
        how many that is, because a member that is gone from the list cannot be looked up. The numbers are read back from
        the stored conversations, so they also cover what a session spent before it was last started.
        """
        views = dict(self._views)
        wanted: dict[str, list[str]] = {}
        for session_id, view in views.items():
            if view["kind"] in ("daemon", "session") and view["workspace"] and not view["agent"]:
                wanted.setdefault(view["workspace"], []).append(session_id)
        groups_known = True
        try:
            graph = await self.backend.graph()
        except SendError:
            graph, groups_known = {}, False  # the broker is away: say the groups are unknown, not that there are none
        # A member that is not listed (a daemon that was deleted leaves its conversation behind) has no folder to look in,
        # so the store is searched for it: a group's total is what its members spent, listed or not.
        unplaced = sorted(
            {
                str(item)
                for group in graph.get("groups") or []
                for item in group.get("members") or []
                if item not in views and item != self.backend.gateway_id
            }
        )
        found = await asyncio.to_thread(self.backend.session_totals, wanted, unplaced)
        daemons = {item.session_id: item for item in await asyncio.to_thread(self.backend.daemons)}
        rows: dict[str, dict[str, Any]] = {}
        # Every listed session is a row, also one with no stored conversation yet (a daemon started and not used): it spent
        # nothing, and is where its Restart button is.
        for session_id in [item for ids in wanted.values() for item in ids]:
            stats = found.get(session_id) or SessionStatsInfo(session_id)
            view, daemon = views[session_id], daemons.get(session_id)
            rows[session_id] = {
                "id": session_id,
                "name": view["name"],
                "kind": view["kind"],
                "status": view["status"],
                "online": view["online"],
                "workspace": view["workspace"],
                "model": view["model"],
                "context_tokens": daemon.context_tokens if daemon is not None else None,
                "context_window": daemon.context_window if daemon is not None else None,
                **_totals_of(stats),
            }
        groups: list[dict[str, Any]] = []
        for group in graph.get("groups") or []:
            if not group.get("name"):
                continue  # a group with no name is the broker's mistake; a card for it could not be opened
            # The person at this gateway is in a group they write to, and spends nothing a ledger holds: not counted.
            members = [str(item) for item in group.get("members") or [] if item != self.backend.gateway_id]
            measured = [found[item] for item in members if item in found]
            groups.append(
                {
                    "name": str(group.get("name", "")),
                    "members": len(members),
                    "measured": len(measured),
                    "offline_ids": [
                        item for item in members if item in views and views[item]["status"] in ("dead", "offline")
                    ],
                    **_sum_totals(measured),
                }
            )
        ordered = sorted(rows.values(), key=lambda row: (-row["input_tokens"] - row["output_tokens"], row["name"]))
        # Everything that was read, listed or not: a group is a part of it, so no group's number exceeds the total.
        return {
            "sessions": ordered,
            "groups": groups,
            "groups_known": groups_known,
            "total": _sum_totals(list(found.values())),
        }

    async def older(self, before: object, limit: object, group: object = None) -> dict[str, Any]:
        """Return the stored messages before id ``before``, oldest first: what a feed loads as it is scrolled back.

        With ``group`` they are that group's own messages (what its chat window shows), and ``before`` may be empty or
        ``0`` for its newest.
        """
        try:
            first = int(before) if before not in (None, "") else 0  # type: ignore[call-overload]
            count = int(limit) if limit not in (None, "") else 50  # type: ignore[call-overload]
        except (TypeError, ValueError):
            raise GatewayError(400, "invalid", "before is a message id, limit a number") from None
        name = _group_name(group) if group else ""
        if first < 1 and not name:
            raise GatewayError(400, "invalid", "before is a message id")
        try:
            return await self.backend.older(max(first, 0), max(1, min(count, 200)), name)
        except SendError as error:
            raise GatewayError(404 if error.reason == "unknown" else 503, error.reason, str(error)) from error

    # -- external agents --------------------------------------------------------------------------
    def agent_types(self) -> list[dict[str, Any]]:
        """Return the external agent types an installed plugin offers."""
        return [item.to_dict() for item in self.agents.available()]

    async def create_agent(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Start one plugin-provided external agent and return its thread."""
        kind = data.get("kind")
        title = data.get("title", "")
        session_id = data.get("session_id", "")
        group = data.get("group", "")
        if not isinstance(kind, str) or not kind:
            raise GatewayError(400, "invalid", "kind names an external agent type")
        if not isinstance(title, str) or not isinstance(session_id, str) or not isinstance(group, str):
            raise GatewayError(400, "invalid", "title, session_id and group are strings")
        if _group_name(group):
            raise GatewayError(400, "external_in_group", EXTERNAL_IN_GROUP)
        try:
            session = await self.agents.create(kind, title, session_id)
        except AgentError as error:
            raise GatewayError(400, "agent", str(error)) from error
        avatar = self.agents.avatar(kind)
        # Only for an agent the person has not yet made anything of: a name, picture, pin or archive they set is theirs,
        # and starting an agent again (a revive) must not put the type's logo over all of it.
        if avatar and session.session_id not in self._profiles:
            try:
                self._profiles.set_default_avatar(session.session_id, avatar)
            except OSError:
                # The agent is already running; losing its default picture must not say otherwise.
                logger.exception("profile.save_failed", extra={"session": session.session_id})
        await self.refresh()
        return {
            "agent": {"session_id": session.session_id, "kind": session.kind, "handle": session.handle},
            "thread": self._views.get(session.session_id),
        }

    async def remove_agent(self, session_id: str) -> dict[str, bool]:
        """Stop one plugin-provided external agent."""
        if not await self.agents.remove(session_id):
            raise GatewayError(404, "not_found", "No such external agent is running")
        await self.refresh()
        return {"ok": True}

    async def join_group(self, name: str) -> dict[str, Any]:
        """Join a group as the gateway's external session, without writing to it."""
        name = _group_name(name)
        try:
            await self.backend.join_group(name)
        except SendError as error:
            raise GatewayError(
                404 if error.reason == "unknown" else SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
            ) from error
        await self.refresh()
        return {"group": name}

    def _is_external(self, session_id: str) -> bool:
        """Whether a listed session is an external agent: a program that registered as one, or one this gateway runs."""
        view = self._views.get(session_id)
        return (view is not None and view.get("kind") == "external") or bool(self.agents.kind_of(session_id))

    async def invite_group(self, name: str, session_id: str) -> dict[str, Any]:
        """Add a session to a group as the broker owner."""
        name, session_id = _group_name(name), session_id.strip()
        if not session_id:
            raise GatewayError(400, "invalid", "a member is required")
        if session_id not in self._views:
            await self.refresh()
        if session_id not in self._views:
            raise GatewayError(404, "not_found", "No such session is listed")
        if self._is_external(session_id):
            raise GatewayError(400, "external_in_group", EXTERNAL_IN_GROUP)
        try:
            await self.backend.add_group_member(name, session_id)
        except SendError as error:
            raise GatewayError(
                404 if error.reason == "unknown" else SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
            ) from error
        await self.refresh()
        return {"group": name, "member": session_id}

    async def create_group(self, name: str, members: object) -> dict[str, Any]:
        """Create a group as the broker owner, with the person at the gateway in it so they can write to it.

        Raises:
            GatewayError: The name is not one a group can have, is taken, or a member is not a listed session.
        """
        name = _group_name(name)
        if not name:
            raise GatewayError(400, "invalid", "a group needs a name")
        if members is None:
            members = []
        if not isinstance(members, list) or not all(isinstance(item, str) for item in members):
            raise GatewayError(400, "invalid", "members is a list of sessions")
        if any(item not in self._views for item in members):
            await self.refresh()
        for item in members:
            if item not in self._views:
                raise GatewayError(404, "not_found", "No such session is listed")
            if self._is_external(item):
                raise GatewayError(400, "external_in_group", EXTERNAL_IN_GROUP)
        mine = self.backend.gateway_id
        everyone = [mine, *dict.fromkeys(item for item in members if item != mine)]
        await self._group_call(lambda: self.backend.create_group(name, everyone))
        await self.refresh()
        return {"group": name, "members": everyone}

    async def delete_group(self, name: str) -> dict[str, Any]:
        """Delete a group, with the messages stored for it."""
        name = _group_name(name)
        await self._group_call(lambda: self.backend.delete_group(name))
        await self.refresh()
        return {"group": name}

    async def _group_call(self, call: Callable[[], Awaitable[None]]) -> None:
        """Run a backend call that changes a group, and say a refusal as a GatewayError with its status."""
        try:
            await call()
        except SendError as error:
            raise GatewayError(
                404 if error.reason == "unknown" else SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
            ) from error

    async def remove_group_member(self, name: str, session_id: str) -> dict[str, Any]:
        """Take a session out of a group as the broker owner; the gateway's own id is how the person leaves it."""
        name, session_id = _group_name(name), session_id.strip()
        if not session_id:
            raise GatewayError(400, "invalid", "a member is required")
        try:
            await self.backend.remove_group_member(name, session_id)
        except SendError as error:
            raise GatewayError(
                404 if error.reason == "unknown" else SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
            ) from error
        await self.refresh()
        return {"group": name, "member": session_id}

    async def leave_group(self, name: str) -> dict[str, Any]:
        """Leave a group as the person at the gateway. What was said stays readable; writing needs joining again."""
        return await self.remove_group_member(name, self.backend.gateway_id)

    async def send_group(self, name: str, text: str) -> dict[str, Any]:
        """Write to a group chat as the person at the gateway, joining the group first when this gateway is not in it.

        Raises:
            GatewayError: The text is empty or too long, the group is not there, nobody else in it is connected, this
                gateway has used up what the broker allows, or the broker refused.
        """
        name = _group_name(name)
        text = text.replace("\r\n", "\n").strip()
        if not text:
            raise GatewayError(400, "empty", "A message needs some text")
        limits = self.backend.limits
        if len(text) > limits.max_text:
            raise GatewayError(
                413, "too_long", f"A message is limited to {limits.max_text} characters", limit=limits.max_text
            )
        self._spend(limits.rate_limit, limits.rate_window)
        try:
            try:
                delivered = await self.backend.send_group(name, text)
            except SendError as error:
                if error.reason != "denied":
                    raise
                # Not a member: the person at the gateway is writing in this group, so they are put in it.
                await self.backend.join_group(name)
                delivered = await self.backend.send_group(name, text)
        except SendError as error:
            raise GatewayError(
                404 if error.reason == "unknown" else SEND_STATUS.get(error.reason, 400),
                error.reason,
                str(error),
                uncertain=error.reason in ("timeout", "lost"),
            ) from error
        self._wake_up()
        return {"delivered": [{"to": item.to, "disposition": item.disposition} for item in delivered]}

    async def timeline(self, since: object, until: object, limit: object) -> dict[str, Any]:
        """Return the stored messages between two times, for the page to replay. Nothing is sent again.

        Args:
            since: Epoch seconds the stretch starts at; an hour before ``until`` when it is not given.
            until: Epoch seconds it ends at; now when it is not given.
            limit: The most messages to return (the newest of the stretch), at most 20000. The answer says ``truncated``
                when the stretch held more, which a replay must say rather than draw a flow that is missing its start.
        """
        try:
            end = float(until) if until not in (None, "") else float(self.clock())  # type: ignore[arg-type]
            start = float(since) if since not in (None, "") else end - 3600  # type: ignore[arg-type]
            count = int(limit) if limit not in (None, "") else 500  # type: ignore[call-overload]
        except (TypeError, ValueError):
            raise GatewayError(400, "invalid", "since and until are epoch seconds, limit a number") from None
        if start > end:
            raise GatewayError(400, "invalid", "since is after until")
        try:
            return await self.backend.timeline(start, end, max(1, min(count, 20_000)))
        except SendError as error:
            raise GatewayError(503, error.reason, str(error)) from error

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

    def _inbox_path(self) -> Path:
        return self.settings.directory / "inbox.json"

    def _load_inbox(self) -> None:
        """Take back what was kept for threads with no stored conversation, so a restart does not empty them."""
        data = read_json(self._inbox_path())
        threads = data.get("threads") if isinstance(data, dict) else None
        if not isinstance(threads, dict):
            return
        for key, thread in threads.items():
            items = thread.get("items") if isinstance(thread, dict) else None
            if not isinstance(key, str) or not isinstance(items, list):
                continue
            kept = [
                dict(item)
                for item in items
                if isinstance(item, dict) and item.get("kind") in ("in", "out") and isinstance(item.get("text"), str)
            ]
            if not kept:
                continue
            self._inbox[key] = deque(kept, maxlen=INBOX_LIMIT)
            sender = thread.get("sender")
            if isinstance(sender, str):
                self._senders[key] = sender

    def _save_inbox(self) -> None:
        """Write what the gateway kept for those threads; a failure only costs the history, so it is not raised.

        At most ``INBOX_THREADS`` x ``INBOX_LIMIT`` items (about a megabyte of JSON at the worst), written in full on the
        event loop each time a message arrives or is sent: small in practice, and the number to look at if it is not.
        """
        path = self._inbox_path()
        # Only what is kept for a thread nobody stores, and only what was delivered: a message still on its way (or
        # lost on the way) must not come back after a restart as if the session had taken it. The newest threads win.
        threads = {
            key: {
                "sender": self._senders.get(key, ""),
                "items": [item for item in box if not any(item is waiting for waiting in self._unsent)],
            }
            for key, box in list(self._inbox.items())[-INBOX_THREADS:]
            if box
        }
        # 0600: this is the one file the gateway keeps that holds what people said.
        with contextlib.suppress(OSError):
            write_json(path, {"threads": threads}, private=True, ensure_ascii=False)

    def _load_seen(self) -> dict[str, int]:
        data = read_json(self._seen_path())
        seen = data.get("seen") if isinstance(data, dict) else None
        if not isinstance(seen, dict):
            return {}
        return {key: value for key, value in seen.items() if isinstance(key, str) and isinstance(value, int)}

    def _save_seen(self) -> None:
        """Write which messages have been read; a failure only costs the marks, so it is not raised."""
        with contextlib.suppress(OSError):
            write_json(self._seen_path(), {"seen": self._seen})


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
