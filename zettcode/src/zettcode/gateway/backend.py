"""What the gateway needs from the agent, as an interface, and the implementation that gets it from the SDK.

The gateway's logic (:mod:`.service`) is written against :class:`Backend`, so it can be tested with a backend that
answers from memory. :class:`SdkBackend` is the real one and the only module of the gateway that touches
``zettcode.sdk.Client``: it is a session of its own, registered with the broker like a terminal's, which has a person
at it and runs no model.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from zettcode.modes import MODE_FOLLOWUP
from zettcode.sdk import daemons as sdk_daemons
from zettcode.sdk.client import Client
from zettcode.sdk.errors import ConfigurationError, SessionLockedError, SessionNotFoundError, ZettCodeError
from zettcode.sdk.models import list_models
from zettcode.sdk.types import (
    DaemonInfo,
    Delivered,
    IncomingMessage,
    Message,
    ModelInfo,
    Peer,
    Receipt,
    SendLimits,
    StreamEvent,
)

#: What the gateway's own session is called, so the sessions it writes to can tell who is speaking.
TITLE = "Web gateway"

#: The file in the gateway's folder that remembers the id of its session, so a restart is the same session to the
#: daemons that were told where to answer.
HOST_FILE = "host.json"


class GatewayStartError(ZettCodeError):
    """The gateway could not become a session: no model is configured, or another gateway is running."""


class Backend(ABC):
    """The agent as the gateway sees it: who is there, what they said, and how to speak to them."""

    @property
    @abstractmethod
    def gateway_id(self) -> str:
        """Return the id the gateway is registered under: what a daemon replies to."""

    @property
    @abstractmethod
    def handle(self) -> str:
        """Return the name the others call the gateway by, or an empty string before it is registered."""

    @property
    @abstractmethod
    def reachable(self) -> bool:
        """Return whether the broker is connected: without it nobody can be written to."""

    @property
    @abstractmethod
    def limits(self) -> SendLimits:
        """Return what the broker accepts from a sender."""

    @abstractmethod
    async def start(self, on_message: Callable[[IncomingMessage], Receipt], on_change: Callable[[], None]) -> None:
        """Become reachable. ``on_message`` is told of each message another session sends; ``on_change`` of any
        change in who is there or whether the broker is."""

    @abstractmethod
    async def close(self) -> None:
        """Leave the broker and release the session. Safe to call twice."""

    @abstractmethod
    def peers(self) -> tuple[Peer, ...]:
        """Return the other registered sessions, from memory."""

    def watch(self, session_id: str) -> None:  # noqa: B027 - a backend with no streams watches nothing
        """Ask to be told what a session's turns say as they happen. Asking twice is the same as once."""

    def unwatch(self, session_id: str) -> None:  # noqa: B027
        """Stop being told what a session's turns say."""

    def on_stream(self, callback: Callable[[StreamEvent], None]) -> None:  # noqa: B027
        """Call ``callback`` on the event loop with every event of a watched session's turn."""

    @abstractmethod
    async def send(self, to: str, text: str, *, direct: bool = False) -> Delivered:
        """Send a message as the person at the gateway and return once the session has taken it.

        A backend sends it as the person at the gateway and never steers a turn the page does not show: a message
        waits for the session's current request to end (see the implementation for the mode it uses).

        With ``direct``, a session that can (``Peer.direct``) runs it as its reader's own prompt and sends its final
        answer back here; for any other the flag is ignored.

        Raises:
            zettcode.sdk.errors.SendError: Nobody was reached, and why.
        """

    def locked(self, session_id: str, workspace: str) -> bool:  # noqa: ARG002
        """Return whether another process has this stored session open (its lock is held)."""
        return False

    @abstractmethod
    async def history(self, session_id: str, workspace: str) -> list[Message]:
        """Return a stored conversation of any session, or raise ``SessionNotFoundError``."""

    @abstractmethod
    def stamp(self, session_id: str, workspace: str) -> tuple[int, int] | None:
        """Return a value that changes when the stored conversation does, or ``None`` when there is none."""

    @abstractmethod
    def models(self) -> list[ModelInfo]:
        """Return the models a daemon can run on, the first being the default."""

    @abstractmethod
    def daemons(self) -> list[DaemonInfo]:
        """Return every daemon on this machine, newest first."""

    @abstractmethod
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
        """Start a daemon and return it once it can be messaged."""

    @abstractmethod
    async def stop(self, session_id: str) -> str:
        """Stop a daemon, remove its record, and say what happened."""

    @abstractmethod
    def log(self, session_id: str, lines: int) -> str:
        """Return the end of a daemon's own log."""


class SdkBackend(Backend):
    """The backend that is a real session: an SDK client that joined the broker, and the SDK's daemon calls."""

    def __init__(self, workspace: Path, directory: Path) -> None:
        """Remember where the gateway's session works and where it keeps its id; nothing starts until :meth:`start`."""
        self.workspace = workspace
        self.directory = directory
        self._client: Client | None = None

    # -- the session ------------------------------------------------------------------------------
    async def start(self, on_message: Callable[[IncomingMessage], Receipt], on_change: Callable[[], None]) -> None:
        """Make the client, take its old id back when it has one, join the broker and watch who is there.

        Raises:
            GatewayStartError: No model is configured (the session needs one to exist, though it never calls it), or
                another gateway holds the session.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        client = self._build(self._remembered())
        try:
            if client.session.locked:
                raise GatewayStartError("another gateway is already running for this user")
            if client.session.title is None:
                await client.session.rename(TITLE)
            self._remember(client.session.id)
            if not await client.join_sessions(on_message):
                raise GatewayStartError("sessions are switched off in the configuration, so nothing can be reached")
        except BaseException:
            await client.aclose()
            raise
        client.watch_peers(on_change)
        self._client = client

    def _build(self, resume: str | None) -> Client:
        """Return the client; a session that was remembered and has since gone is replaced by a new one."""
        settings = {
            "sessions_enabled": True,
            "update_enabled": False,
            "plugins_enabled": False,
            "mcp_enabled": False,
            "skills_enabled": False,
            "agents_md_enabled": False,
            "ask_user_enabled": False,
            "subagent_enabled": False,
            "permission": "deny",
        }
        try:
            return Client(self.workspace, resume=resume, **settings)  # type: ignore[arg-type]
        except SessionNotFoundError:
            return Client(self.workspace, **settings)  # type: ignore[arg-type]
        except ConfigurationError as error:
            raise GatewayStartError(f"{error}. Add a model with `zettcode` (/config) or in the config file.") from error
        except SessionLockedError as error:
            raise GatewayStartError("another gateway is already running for this user") from error

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

    @property
    def client(self) -> Client:
        """Return the client; asking before :meth:`start` is a bug of the caller's."""
        if self._client is None:
            raise GatewayStartError("the gateway has not started")
        return self._client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.watch_peers(None)
            await client.aclose()

    # -- who is there and what was said -----------------------------------------------------------
    @property
    def gateway_id(self) -> str:
        return self.client.session.id

    @property
    def handle(self) -> str:
        return self.client.handle

    @property
    def reachable(self) -> bool:
        return self._client is not None and self._client.reachable

    @property
    def limits(self) -> SendLimits:
        return self.client.send_limits

    def peers(self) -> tuple[Peer, ...]:
        return self.client.peers()

    def watch(self, session_id: str) -> None:
        self.client.watch(session_id)

    def unwatch(self, session_id: str) -> None:
        self.client.unwatch(session_id)

    def on_stream(self, callback: Callable[[StreamEvent], None]) -> None:
        self.client.watch_streams(callback)

    async def send(self, to: str, text: str, *, direct: bool = False) -> Delivered:
        # A page keeps a conversation instead of watching the session's live turn, so its message never steers one:
        # a person typing here cannot see what they would be interrupting.
        return await self.client.send(to, text, direct=direct, mode=MODE_FOLLOWUP)

    def locked(self, session_id: str, workspace: str) -> bool:
        return self.client.sessions.open_elsewhere(session_id, workspace=workspace or None)

    async def history(self, session_id: str, workspace: str) -> list[Message]:
        return await self.client.sessions.history_of(session_id, workspace=workspace or None, full=True)

    def stamp(self, session_id: str, workspace: str) -> tuple[int, int] | None:
        return self.client.sessions.stamp(session_id, workspace=workspace or None)

    # -- daemons ----------------------------------------------------------------------------------
    def models(self) -> list[ModelInfo]:
        return list(list_models())

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

    async def stop(self, session_id: str) -> str:
        return await sdk_daemons.stop_daemon(session_id)

    def log(self, session_id: str, lines: int) -> str:
        return sdk_daemons.daemon_log(session_id, lines=lines)
