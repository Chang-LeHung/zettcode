"""A gateway that is an external broker session, not a ZettCode session.

The page still lists sessions, reads what they said and sends messages. It no longer owns a model-backed session:
it registers as ``kind="external"`` under an id remembered in ``host.json``, receives replies on its own inbox, and
uses the broker's owner token for the reads an external session is not allowed to make (global history, graph,
timeline). Daemons and models are still the SDK's local services; only the page's own identity changed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from zettcode.broker.external import ExternalConflict, ExternalSession
from zettcode.broker.files import broker_dir, read_note
from zettcode.broker.models import Incoming as BrokerIncoming
from zettcode.broker.models import Receipt as BrokerReceipt
from zettcode.broker.protocol import KIND_EXTERNAL
from zettcode.engine.storage.store import SessionStore
from zettcode.modes import MODE_FOLLOWUP
from zettcode.sdk import daemons as sdk_daemons
from zettcode.sdk.errors import SendError, SessionNotFoundError
from zettcode.sdk.models import add_model, list_models, remove_model, update_model
from zettcode.sdk.session import messages_of
from zettcode.sdk.types import (
    DaemonInfo,
    Delivered,
    Image,
    IncomingMessage,
    Message,
    ModelInfo,
    Peer,
    Receipt,
    Relay,
    SendLimits,
    StreamEvent,
)

from .backend import HOST_FILE, TITLE, Backend, GatewayStartError

#: The agent types a gateway offers with no plugin installed. The page can still browse and write.
DEFAULT_TITLE = TITLE

logger = logging.getLogger("zettcode.gateway")


class ExternalBackend(Backend):
    """The gateway as an external broker session, with owner-token reads for the page."""

    def __init__(self, directory: Path, sessions_root: Path | None = None) -> None:
        self.directory = directory
        self.sessions_root = sessions_root.expanduser().resolve() if sessions_root is not None else None
        self._session: ExternalSession | None = None
        self._owner: httpx.AsyncClient | None = None
        self._on_message: Callable[[IncomingMessage], Receipt] | None = None
        self._stores: dict[Path, SessionStore] = {}

    async def start(self, on_message: Callable[[IncomingMessage], Receipt], on_change: Callable[[], None]) -> None:
        """Register as an external session and open the owner client used for reads."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self._on_message = on_message
        session_id = self._remembered() or f"web-{secrets.token_hex(6)}"
        session = ExternalSession(
            session_id,
            DEFAULT_TITLE,
            directory=broker_dir(),
            kind=KIND_EXTERNAL,
            on_message=self._deliver,
            on_roster=lambda _roster: on_change(),
            connect_timeout=5.0,
        )
        try:
            await session.connect()
        except ExternalConflict as error:
            await session.close()
            raise GatewayStartError("another gateway is already running for this user") from error
        except Exception as error:  # noqa: BLE001 - the external client's failures become one gateway sentence
            await session.close()
            raise GatewayStartError(str(error)) from error
        self._session = session
        self._remember(session_id)
        note = read_note(broker_dir())
        if note is None:
            await session.close()
            raise GatewayStartError("the broker note disappeared while the gateway was starting")
        try:
            self._owner = httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{note.port}",
                headers={"Authorization": f"Bearer {note.token}"},
                trust_env=False,
                timeout=10.0,
            )
        except Exception as error:  # noqa: BLE001 - a failed HTTP client leaves no session behind
            self._session = None
            await session.close()
            raise GatewayStartError(f"the gateway's HTTP client could not be made: {error}") from error

    async def close(self) -> None:
        owner, self._owner = self._owner, None
        if owner is not None:
            await owner.aclose()
        session, self._session = self._session, None
        if session is not None:
            await session.close()

    # -- the page's identity ----------------------------------------------------------------------
    @property
    def session(self) -> ExternalSession:
        if self._session is None:
            raise GatewayStartError("the gateway has not started")
        return self._session

    @property
    def external(self) -> bool:
        return True

    @property
    def gateway_id(self) -> str:
        return self.session.session_id

    @property
    def handle(self) -> str:
        return self.session.handle

    @property
    def reachable(self) -> bool:
        return self._session is not None and self._session.connected

    @property
    def limits(self) -> SendLimits:
        limits = self.session.limits
        return SendLimits(
            max_text=limits.max_text,
            rate_limit=limits.rate_limit,
            rate_window=limits.rate_window,
            max_hops=limits.max_hops,
        )

    def peers(self) -> tuple[Peer, ...]:
        return tuple(
            Peer(
                entry.session_id,
                entry.handle,
                entry.title,
                entry.workspace,
                entry.status,
                entry.kind,
                entry.direct,
            )
            for entry in self.session.roster
            if entry.session_id != self.gateway_id
        )

    def watch(self, session_id: str) -> None:
        self.session.watch(session_id)

    def unwatch(self, session_id: str) -> None:
        self.session.unwatch(session_id)

    def on_stream(self, callback: Callable[[StreamEvent], None]) -> None:
        self.session.on_stream(
            lambda session_id, event: callback(
                StreamEvent(
                    session_id=session_id,
                    kind=str(event.get("kind", "")),
                    text=str(event.get("text", "")),
                    call_id=str(event.get("call_id", "")),
                    name=str(event.get("name", "")),
                    brief=str(event.get("brief", "")),
                    ok=event.get("ok") if isinstance(event.get("ok"), bool) else None,
                )
            )
        )

    def observe(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self.session.observe(callback)

    # -- what the page says -----------------------------------------------------------------------
    async def send(self, to: str, text: str, *, direct: bool = False, images: Sequence[Image] = ()) -> Delivered:
        if direct or images:
            raise SendError(
                "invalid", "the web gateway is an external session; pictures and direct prompts need a session"
            )
        sent = await self.session.send(to, text, mode=MODE_FOLLOWUP)
        return Delivered(sent.to.handle, sent.disposition, sent.direct)

    async def send_group(self, group: str, text: str) -> list[Delivered]:
        sent = await self.session.send_group(group, text, mode=MODE_FOLLOWUP)
        return [Delivered(peer.handle, disposition, False) for peer, disposition in sent.delivered]

    async def join_group(self, group: str) -> None:
        await self.session.join_group(group)

    async def add_group_member(self, group: str, session_id: str) -> None:
        await self._owner_post("/groups", {"action": "add", "name": group, "members": [session_id]})

    async def remove_group_member(self, group: str, session_id: str) -> None:
        await self._owner_post("/groups", {"action": "remove", "name": group, "members": [session_id]})

    async def create_group(self, group: str, members: list[str]) -> None:
        await self._owner_post("/groups", {"action": "create", "name": group, "members": members})

    async def delete_group(self, group: str) -> None:
        await self._owner_post("/groups", {"action": "delete", "name": group})

    # -- reads the owner may make -----------------------------------------------------------------
    async def _owner_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        owner = self._owner
        if owner is None:
            raise _gateway_error(503, "broker", "the gateway is not connected to the broker")
        try:
            response = await owner.post(path, json=data)
        except httpx.HTTPError as error:
            raise _gateway_error(503, "broker", f"the broker did not answer: {type(error).__name__}") from error
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200:
            refusal = body.get("error") if isinstance(body, dict) else None
            reason = refusal.get("reason") if isinstance(refusal, dict) else "broker"
            message = refusal.get("message") if isinstance(refusal, dict) else "the broker refused the change"
            raise _gateway_error(
                503 if response.status_code >= 500 else response.status_code, str(reason), str(message)
            )
        return body if isinstance(body, dict) else {}

    async def _owner_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        owner = self._owner
        if owner is None:
            raise _gateway_error(503, "broker", "the gateway is not connected to the broker")
        try:
            response = await owner.get(path, params=params)
        except httpx.HTTPError as error:
            raise _gateway_error(503, "broker", f"the broker did not answer: {type(error).__name__}") from error
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200:
            refusal = body.get("error") if isinstance(body, dict) else None
            reason = refusal.get("reason") if isinstance(refusal, dict) else "broker"
            message = refusal.get("message") if isinstance(refusal, dict) else "the broker refused the read"
            raise _gateway_error(
                503 if response.status_code >= 500 else response.status_code, str(reason), str(message)
            )
        return body if isinstance(body, dict) else {}

    async def graph(self) -> dict[str, Any]:
        return await self._owner_get("/graph", {})

    async def older(self, before: int, limit: int, group: str = "") -> dict[str, Any]:
        return await self._owner_get(
            "/older", {"before": before, "limit": limit, **({"group": group} if group else {})}
        )

    async def timeline(self, since: float, until: float, limit: int) -> dict[str, Any]:
        return await self._owner_get("/timeline", {"since": since, "until": until, "limit": limit})

    async def history(self, session_id: str, workspace: str) -> list[Message]:
        """Return a stored conversation, or the relay between an external session and this gateway.

        A ZettCode session and a daemon keep their conversation in the store. An external agent has no store, and
        the only record of what it said is the broker's history between it and the page, so that is the fallback.
        """
        if not workspace.strip():
            # A peer without a workspace is an external session: it has no store, and opening one for the gateway's
            # cwd would touch a folder that is not the peer's.
            return await self._pair_history(session_id)
        store = self._store(workspace)
        try:
            stored = await asyncio.to_thread(store.read, session_id)
        except (ValueError, OSError) as error:
            # A missing file reads as an empty session; this is a damaged or unreadable one, and a shorter broker
            # relay would be the wrong conversation for it.
            logger.warning("history.read_failed", extra={"session": session_id}, exc_info=error)
            raise SessionNotFoundError(f"Cannot read session {session_id}: {error}") from error
        if stored.header is None:
            return await self._pair_history(session_id)
        return messages_of(stored, full=True)

    async def _pair_history(self, session_id: str) -> list[Message]:
        """Return what this gateway and one session exchanged through the broker."""
        body = await self._owner_get("/history", {"a": self.gateway_id, "b": session_id, "limit": 500})
        messages = body.get("messages")
        if not isinstance(messages, list):
            return []
        found: list[Message] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            sender = item.get("from")
            sender_id = sender.get("session_id") if isinstance(sender, dict) else ""
            handle = sender.get("handle") if isinstance(sender, dict) else ""
            text = item.get("text")
            via = item.get("via")
            hops = item.get("hops")
            if not isinstance(text, str) or not isinstance(sender_id, str) or not isinstance(handle, str):
                continue
            found.append(
                Message(
                    role="user",
                    text=text,
                    relay=Relay(
                        sender_id,
                        handle,
                        via if isinstance(via, str) else "external",
                        hops if isinstance(hops, int) else 1,
                    ),
                )
            )
        return found

    def _store(self, workspace: str) -> SessionStore:
        """Return the store of a workspace, opened once and reused so a conversation is parsed only when it moved."""
        target = Path(workspace).expanduser().resolve()
        store = self._stores.get(target)
        if store is None:
            store = self._stores[target] = SessionStore(self.sessions_root, workspace=target)
        return store

    def locked(self, session_id: str, workspace: str) -> bool:
        del session_id, workspace
        return False

    def stamp(self, session_id: str, workspace: str) -> tuple[int, int] | None:
        if not workspace.strip():
            return None
        try:
            seen = self._store(workspace).session_path(session_id).stat()
        except (OSError, ValueError):
            return None
        return (seen.st_mtime_ns, seen.st_size)

    # -- daemons and models -----------------------------------------------------------------------
    def models(self) -> list[ModelInfo]:
        return list(list_models())

    def add_model(self, entry: dict[str, object]) -> list[ModelInfo]:
        return list(add_model(entry))

    def update_model(self, name: str, changes: dict[str, object]) -> list[ModelInfo]:
        return list(update_model(name, changes))

    def remove_model(self, name: str) -> list[ModelInfo]:
        return list(remove_model(name))

    def daemons(self) -> list[DaemonInfo]:
        return sdk_daemons.list_daemons()

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
        return await sdk_daemons.spawn_daemon(
            workspace, model=model, effort=effort, resume=resume, name=name, permission=permission
        )

    async def stop(self, session_id: str, *, force: bool) -> str:
        return await sdk_daemons.stop_daemon(session_id, force=force)

    async def delete(self, session_id: str) -> str:
        return await sdk_daemons.delete_daemon(session_id)

    def log(self, session_id: str, lines: int) -> str:
        return sdk_daemons.daemon_log(session_id, lines=lines)

    # -- broker messages --------------------------------------------------------------------------
    def _deliver(self, message: BrokerIncoming) -> BrokerReceipt:
        if self._on_message is None:
            return BrokerReceipt(False, "the gateway is not ready")
        receipt = self._on_message(
            IncomingMessage(
                sender_id=message.sender.session_id,
                sender=message.sender.handle,
                text=message.text,
                via=message.via,
                hops=message.hops,
                direct=message.direct,
                mode=message.mode,
                group=message.group,
                images=tuple(Image(image.data, image.media_type) for image in message.images),
            )
        )
        return BrokerReceipt(receipt.accepted, receipt.reason, receipt.disposition, receipt.busy)

    def _remembered(self) -> str | None:
        try:
            data = json.loads((self.directory / HOST_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        session = data.get("session") if isinstance(data, dict) else None
        return session if isinstance(session, str) and session else None

    def _remember(self, session_id: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / f".{HOST_FILE}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps({"session": session_id}), encoding="utf-8")
        os.replace(temporary, self.directory / HOST_FILE)


def _gateway_error(status: int, code: str, message: str) -> Any:
    """Build a GatewayError without importing the service at module import time (it imports this backend)."""
    from .service import GatewayError

    return GatewayError(status, code, message)


__all__ = ["ExternalBackend"]
