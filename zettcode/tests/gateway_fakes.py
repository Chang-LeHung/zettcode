"""A gateway backend that answers from memory, for the tests and for ``docs/scripts/gateway_demo.py``.

It stands in for the SDK and the broker and nothing else: the gateway's own logic, its web application and its page
run for real on top of it. With ``simulate`` set it also plays the part of the daemons -- a message sent to one makes
it work for a moment, run a tool or two and answer -- which is what makes the page worth looking at.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zettcode.gateway.backend import Backend
from zettcode.gateway.chat import strip_reply_request
from zettcode.sdk.errors import SendError, SessionNotFoundError
from zettcode.sdk.types import (
    DaemonInfo,
    Delivered,
    IncomingMessage,
    Message,
    ModelInfo,
    Peer,
    Receipt,
    Relay,
    SendLimits,
    StreamEvent,
    ToolCallInfo,
)

GATEWAY_ID = "01gateway-0000-0000-0000-000000000000"


def model(name: str, *efforts: str, window: int = 200_000, multimodal: bool = False) -> ModelInfo:
    """Return a configured model the way the SDK lists one."""
    return ModelInfo(
        name=name, model=name, context_window=window, multimodal=multimodal, efforts=tuple(efforts), api="chat"
    )


class FakeBackend(Backend):
    """Everything the gateway asks of the agent, kept in dictionaries a test can read and change."""

    def __init__(self, *, simulate: bool = False, workspace: Path | None = None) -> None:
        self.simulate = simulate
        self.workspace = workspace
        self._id = GATEWAY_ID
        self._handle = "web-gateway"
        self._reachable = True
        self._limits = SendLimits()
        self.model_list = [model("fast", "low", "high"), model("deep", "low", "medium", "high", multimodal=True)]
        self.daemon_list: dict[str, DaemonInfo] = {}
        self.peer_list: dict[str, Peer] = {}
        self.histories: dict[str, list[Message]] = {}
        self.stamps: dict[str, int] = {}
        self.sent: list[tuple[str, str]] = []
        #: For each send, whether it was run as the session's own prompt (the flag was set and the session can).
        self.direct_sent: list[bool] = []
        #: The sessions whose turns the gateway asked to see, and who it told.
        self.watched: set[str] = set()
        self.stream_listener: Callable[[StreamEvent], None] | None = None
        self.traffic_listener: Callable[[dict[str, Any]], None] | None = None
        self.graph_data: dict[str, Any] = {"sessions": [], "groups": [], "edges": [], "recent": []}
        self.timeline_asked: list[tuple[float, float, int]] = []
        #: Sessions another process is taken to have open.
        self.locked_ids: set[str] = set()
        self.spawned: list[dict[str, object]] = []
        self.stopped: list[str] = []
        self.logs: dict[str, str] = {}
        self.fail: SendError | None = None
        self.fail_spawn: Exception | None = None
        self.on_message: Callable[[IncomingMessage], Receipt] | None = None
        self.on_change: Callable[[], None] | None = None
        self.started = False
        self.closed = False
        self._numbers = itertools.count(1)
        self._tasks: set[asyncio.Task[None]] = set()

    # -- the session ------------------------------------------------------------------------------
    @property
    def gateway_id(self) -> str:
        return self._id

    @property
    def handle(self) -> str:
        return self._handle

    @property
    def reachable(self) -> bool:
        return self._reachable

    @property
    def limits(self) -> SendLimits:
        return self._limits

    async def start(self, on_message: Callable[[IncomingMessage], Receipt], on_change: Callable[[], None]) -> None:
        self.on_message, self.on_change, self.started = on_message, on_change, True

    async def close(self) -> None:
        self.closed = True
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def watch(self, session_id: str) -> None:
        self.watched.add(session_id)

    def unwatch(self, session_id: str) -> None:
        self.watched.discard(session_id)

    def on_stream(self, callback: Callable[[StreamEvent], None]) -> None:
        self.stream_listener = callback

    def stream(self, session_id: str, kind: str, **fields: Any) -> None:
        """Say what a turn running in a session just did, as the broker would have told the gateway."""
        assert self.stream_listener is not None
        self.stream_listener(StreamEvent(session_id, kind, **fields))

    def observe(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self.traffic_listener = callback

    def traffic(self, line: dict[str, Any]) -> None:
        """Say what the broker saw pass, as an observer is told."""
        assert self.traffic_listener is not None
        self.traffic_listener(line)

    async def graph(self) -> dict[str, Any]:
        return self.graph_data

    async def older(self, before: int, limit: int) -> dict[str, Any]:
        found = [m for m in self.graph_data["recent"] if m["id"] < before][-limit:]
        return {"messages": found, "more": bool(found) and found[0]["id"] > 1}

    async def timeline(self, since: float, until: float, limit: int) -> dict[str, Any]:
        self.timeline_asked.append((since, until, limit))
        return {
            "messages": [m for m in self.graph_data["recent"] if since <= m["ts"] <= until],
            "span": None,
            "now": until,
        }

    def changed(self) -> None:
        """Tell the gateway something moved, as the broker client would."""
        if self.on_change is not None:
            self.on_change()

    def set_reachable(self, value: bool) -> None:
        self._reachable = value
        self.changed()

    def set_limits(self, limits: SendLimits) -> None:
        self._limits = limits

    # -- who is there -----------------------------------------------------------------------------
    def peers(self) -> tuple[Peer, ...]:
        return tuple(self.peer_list.values())

    def add_peer(
        self,
        session_id: str,
        handle: str,
        *,
        workspace: str = "",
        title: str = "",
        kind: str = "zettcode",
        status: str = "idle",
        direct: bool = False,
    ) -> Peer:
        peer = Peer(session_id, handle, title, workspace, status, kind, direct)
        self.peer_list[session_id] = peer
        self.changed()
        return peer

    def set_status(self, session_id: str, status: str) -> None:
        peer = self.peer_list[session_id]
        self.peer_list[session_id] = Peer(
            peer.session_id, peer.handle, peer.title, peer.workspace, status, peer.kind, peer.direct
        )
        self.changed()

    def add_daemon(
        self,
        session_id: str,
        workspace: str,
        *,
        name: str | None = None,
        status: str = "idle",
        model_name: str = "fast",
        permission: str = "safe",
        online: bool = True,
        started_at: float | None = None,
        title: str | None = None,
        direct: bool = False,
    ) -> DaemonInfo:
        info = DaemonInfo(
            session_id=session_id,
            workspace=workspace,
            status=status,
            name=name,
            title=title,
            model=model_name,
            effort=None,
            permission=permission,
            pid=4000 + next(self._numbers),
            started_at=started_at if started_at is not None else time.time(),
        )
        self.daemon_list[session_id] = info
        if online and status != "dead":
            handle = (name or title or session_id[:8]).lower().replace(" ", "-")
            self.peer_list[session_id] = Peer(session_id, handle, title or "", workspace, "idle", "zettcode", direct)
        self.changed()
        return info

    def say(self, session_id: str, *messages: Message) -> None:
        """Append to a stored conversation and move its stamp, as a daemon writing a turn would."""
        self.histories.setdefault(session_id, []).extend(messages)
        self.stamps[session_id] = self.stamps.get(session_id, 0) + 1
        self.changed()

    # -- sending ----------------------------------------------------------------------------------
    def locked(self, session_id: str, workspace: str) -> bool:
        return session_id in self.locked_ids

    async def send(self, to: str, text: str, *, direct: bool = False) -> Delivered:
        if self.fail is not None:
            raise self.fail
        peer = self.peer_list.get(to)
        if peer is None:
            raise SendError("unknown", f"no active session is called '{to}'")
        self.sent.append((to, text))
        directly = direct and peer.direct
        self.direct_sent.append(directly)
        # What a session that runs it as its own prompt stores is the text alone; any other keeps who sent it.
        relay = None if directly else Relay(self._id, self._handle, "user", 1)
        busy = peer.status == "working"
        if to in self.daemon_list and not busy:
            self.say(to, Message("user", text, relay=relay))
        if self.simulate and to in self.daemon_list:
            self._spawn_task(self._work(to, text))
        return Delivered(peer.handle, "queued" if busy else "started", directly)

    def _spawn_task(self, coroutine: object) -> None:
        task = asyncio.ensure_future(coroutine)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _work(self, session_id: str, text: str) -> None:
        """Play a daemon: work for a moment, run two tools, and answer in words and with ``send_message``."""
        await asyncio.sleep(0.2)
        self.set_status(session_id, "working")
        await asyncio.sleep(1.0)
        asked = strip_reply_request(text)
        call = ToolCallInfo("c1", "grep", {"pattern": "TODO", "path": "src"})
        self.say(session_id, Message("assistant", "", tool_calls=(call,)))
        await asyncio.sleep(0.6)
        self.say(session_id, Message("tool", "src/api.py:42: TODO handle timeout", tool_call_id="c1", tool_name="grep"))
        await asyncio.sleep(0.6)
        note = (
            f'I looked into "{asked[:60]}".\n\nFound one open item in `src/api.py`:\n\n'
            "```python\ndef fetch(url):\n    # TODO handle timeout\n    return get(url)\n```\n"
        )
        reply = ToolCallInfo("c2", "send_message", {"to": self._id, "message": note})
        self.say(session_id, Message("assistant", "Done - reported back.", tool_calls=(reply,)))
        self.set_status(session_id, "idle")
        if self.on_message is not None:
            peer = self.peer_list[session_id]
            self.on_message(IncomingMessage(session_id, peer.handle, note, via="agent", hops=2))

    def inbound(self, session_id: str, handle: str, text: str, *, via: str = "agent") -> Receipt:
        """Deliver a message to the gateway, as the broker would."""
        assert self.on_message is not None
        return self.on_message(IncomingMessage(session_id, handle, text, via=via))

    # -- stored conversations ---------------------------------------------------------------------
    async def history(self, session_id: str, workspace: str) -> list[Message]:
        if session_id not in self.histories:
            raise SessionNotFoundError(f"Session {session_id} has no messages yet")
        return list(self.histories[session_id])

    def stamp(self, session_id: str, workspace: str) -> tuple[int, int] | None:
        if session_id not in self.stamps:
            return None
        return ((1_800_000_000 + self.stamps[session_id]) * 1_000_000_000, self.stamps[session_id])

    # -- daemons ----------------------------------------------------------------------------------
    def models(self) -> list[ModelInfo]:
        return list(self.model_list)

    def daemons(self) -> list[DaemonInfo]:
        return sorted(self.daemon_list.values(), key=lambda item: -item.started_at)

    async def spawn(
        self,
        workspace: Path,
        *,
        model: str | None,
        effort: str | None,
        resume: str | None,
        name: str | None,
        permission: str,
    ) -> DaemonInfo:
        if self.fail_spawn is not None:
            raise self.fail_spawn
        self.spawned.append(
            {
                "workspace": str(workspace),
                "model": model,
                "effort": effort,
                "resume": resume,
                "name": name,
                "permission": permission,
            }
        )
        session_id = resume or f"01spawned-{next(self._numbers):04d}-0000-0000-000000000000"
        info = self.add_daemon(
            session_id, str(workspace), name=name, model_name=model or self.model_list[0].name, permission=permission
        )
        return info

    async def stop(self, session_id: str) -> str:
        if session_id not in self.daemon_list:
            raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
        self.stopped.append(session_id)
        del self.daemon_list[session_id]
        self.peer_list.pop(session_id, None)
        self.changed()
        return "stopped"

    def log(self, session_id: str, lines: int) -> str:
        if session_id not in self.daemon_list:
            raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
        return self.logs.get(session_id, "")
