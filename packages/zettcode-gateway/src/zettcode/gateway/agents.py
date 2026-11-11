"""Gateway-managed external agents: a plugin registers a factory, the page starts one.

A plugin is a class under the ``zettcode.gateway.external`` entry-point group. It returns an
:class:`~zettcode.broker.external.ExternalSession`; the gateway starts it, and the broker lists it like any other
session. The plugin runs in the gateway process, so only installed, trusted code is loaded.

The agent is expected to register as ``kind="zettcode"`` when it needs group chats and history; an ordinary outside
program uses ``kind="external"`` and keeps the broker's narrower permissions.
"""

from __future__ import annotations

import logging
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from zettcode.broker.external import ExternalSession

logger = logging.getLogger("zettcode.gateway")

#: The entry-point group a gateway agent plugin registers under.
ENTRY_POINT = "zettcode.gateway.external"


class AgentError(Exception):
    """The gateway cannot offer or start an external agent, with a sentence a person can read."""


@dataclass(frozen=True, slots=True)
class AgentType:
    """One kind of external agent a plugin offers."""

    name: str
    title: str
    description: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "title": self.title, "description": self.description}


class AgentPlugin(ABC):
    """The contract an installed gateway plugin implements.

    ``name`` is the stable type id the page sends back; ``title`` is what a list shows. :meth:`create` returns an
    unconnected :class:`ExternalSession`; the manager calls ``connect`` and owns its lifetime.
    """

    name: str = ""
    title: str = ""
    description: str = ""

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
            AgentType(plugin.name, plugin.title or plugin.name, plugin.description) for plugin in self._plugins.values()
        ]

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
        session = plugin.create(session_id, title or plugin.title or kind)
        try:
            await session.connect()
            if group:
                await session.join_group(group)
        except Exception as error:  # noqa: BLE001 - every failure becomes a GatewayError sentence at the API edge
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
