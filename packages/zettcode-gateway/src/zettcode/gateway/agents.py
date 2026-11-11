"""Gateway-managed external agents: a plugin registers a factory, the page starts one.

A plugin is a class under the ``zettcode.gateway.external`` entry-point group. It returns an
:class:`~zettcode.broker.external.ExternalSession`; the gateway starts it, and the broker lists it like any other
session. The plugin runs in the gateway process, so only installed, trusted code is loaded.

The agent is expected to register as ``kind="zettcode"`` when it needs group chats and history; an ordinary outside
program uses ``kind="external"`` and keeps the broker's narrower permissions.
"""

from __future__ import annotations

import base64
import logging
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from zettcode.broker.external import ExternalSession
from zettcode.broker.protocol import sniff_image

logger = logging.getLogger("zettcode.gateway")

#: The entry-point group a gateway agent plugin registers under.
ENTRY_POINT = "zettcode.gateway.external"

#: How many agents one gateway may keep running. A page cannot grow the roster without bound.
MAX_AGENTS = 64

#: The largest avatar a plugin may contribute, encoded as a data URL.
MAX_AVATAR = 300_000

#: The suffix to media type for an image file whose first bytes do not identify it.
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def avatar_data(value: str) -> str:
    """Return an avatar as a data URL from a data URL, a local file path, or a base64 image.

    A plugin may name a file beside its code, pass a data URL, or pass ``base64:<data>``. A missing or unreadable
    file, an image that is too large, and a string that is none of these become an empty avatar; a broken optional
    picture must not stop the plugin from being listed.
    """
    value = value.strip()
    if not value:
        return ""
    if value.startswith("data:image/"):
        return value if len(value) <= MAX_AVATAR else ""
    raw: bytes | None = None
    mime = ""
    if value.startswith("base64:"):
        raw = _decode(value[7:])
    else:
        path = Path(value).expanduser()
        try:
            if path.is_file():
                raw = path.read_bytes()
                mime = _IMAGE_TYPES.get(path.suffix.lower(), "")
        except OSError:
            raw = None
    if raw is None or not raw or len(raw) > MAX_AVATAR:
        return ""
    mime = sniff_image(raw) or mime
    if not mime:
        return ""
    encoded = base64.b64encode(raw).decode("ascii")
    result = f"data:{mime};base64,{encoded}"
    return result if len(result) <= MAX_AVATAR else ""


def _decode(value: str) -> bytes | None:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        return None


class AgentError(Exception):
    """The gateway cannot offer or start an external agent, with a sentence a person can read."""


@dataclass(frozen=True, slots=True)
class AgentType:
    """One kind of external agent a plugin offers."""

    name: str
    title: str
    description: str = ""
    avatar: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "avatar": avatar_data(self.avatar),
        }


class AgentPlugin(ABC):
    """The contract an installed gateway plugin implements.

    ``name`` is the stable type id the page sends back; ``title`` is what a list shows. :meth:`create` returns an
    unconnected :class:`ExternalSession`; the manager calls ``connect`` and owns its lifetime.
    """

    name: str = ""
    title: str = ""
    description: str = ""
    #: A data URL shown for the agent when the page has no profile picture of its own.
    avatar: str = ""

    @abstractmethod
    def create(self, session_id: str, title: str) -> ExternalSession:
        """Return the agent's external session, not yet connected."""


class AgentManager:
    """The plugins this gateway found, and the agents it has started.

    Args:
        directory: The gateway's own folder. It is passed to each :class:`ExternalSession`; the broker's own
            directory remains the broker's default.
        plugins: The plugins to offer; the installed entry points when omitted.
    """

    def __init__(self, directory: Path, plugins: list[AgentPlugin] | None = None) -> None:
        self.directory = directory
        self._plugins = {plugin.name: plugin for plugin in (plugins if plugins is not None else load_plugins())}
        self._running: dict[str, ExternalSession] = {}

    def available(self) -> list[AgentType]:
        """Return the agent types a page may create."""
        return [
            AgentType(plugin.name, plugin.title or plugin.name, plugin.description, avatar_data(plugin.avatar))
            for plugin in self._plugins.values()
        ]

    def avatar(self, kind: str) -> str:
        """Return the default picture a type offers, or an empty string."""
        plugin = self._plugins.get(kind)
        return avatar_data(plugin.avatar) if plugin is not None else ""

    def running(self) -> dict[str, ExternalSession]:
        """Return the agents this gateway started, by session id."""
        return dict(self._running)

    async def create(self, kind: str, title: str = "", session_id: str = "", group: str = "") -> ExternalSession:
        """Start one agent and return its session.

        Raises:
            AgentError: The type is unknown, the id is taken or malformed, or the broker refused the registration.
        """
        plugin = self._plugins.get(kind)
        if plugin is None:
            raise AgentError(f"there is no external agent type {kind!r}")
        session_id = session_id or f"web-{secrets.token_hex(6)}"
        if session_id in self._running:
            raise AgentError(f"the external agent {session_id!r} is already running")
        if len(self._running) >= MAX_AGENTS:
            raise AgentError(f"a gateway may run at most {MAX_AGENTS} external agents")
        session: ExternalSession | None = None
        try:
            session = plugin.create(session_id, title or plugin.title or kind)
            await session.connect()
            if group:
                await session.join_group(group)
        except Exception as error:  # noqa: BLE001 - every failure becomes a GatewayError sentence at the API edge
            if session is not None:
                await session.close()
            raise AgentError(str(error)) from error
        self._running[session_id] = session
        return session

    async def remove(self, session_id: str) -> bool:
        """Stop one agent; return whether it was running."""
        session = self._running.pop(session_id, None)
        if session is None:
            return False
        await session.close()
        return True

    async def close(self) -> None:
        """Stop every agent this manager started."""
        running, self._running = list(self._running.values()), {}
        for session in running:
            await session.close()


def load_plugins() -> list[AgentPlugin]:
    """Load the installed ``zettcode.gateway.external`` entry points, skipping one that does not fit the contract."""
    found: list[AgentPlugin] = []
    names: set[str] = set()
    for point in entry_points(group=ENTRY_POINT):
        try:
            value: Any = point.load()
            plugin = value() if isinstance(value, type) else value
        except Exception:  # noqa: BLE001 - a broken installed plugin must not stop the gateway
            logger.exception("external_agent.load_failed", extra={"entry_point": point.name})
            continue
        if not isinstance(plugin, AgentPlugin) or not plugin.name:
            logger.warning("external_agent.invalid", extra={"entry_point": point.name})
            continue
        if plugin.name in names:
            logger.warning("external_agent.duplicate", extra={"entry_point": point.name, "name": plugin.name})
            continue
        names.add(plugin.name)
        found.append(plugin)
    return found
