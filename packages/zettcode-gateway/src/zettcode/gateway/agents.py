"""Gateway-managed external agents: a plugin registers a factory, the page starts one.

A plugin is a class under the ``zettcode.gateway.external`` entry-point group. It returns an
:class:`~zettcode.broker.external.ExternalSession`; the gateway starts it, and the broker lists it like any other
session. The plugin runs in the gateway process, so only installed, trusted code is loaded.

An agent may register as ``kind="external"`` or as the trusted ``kind="zettcode"``. The gateway does not put one in a
group (two of them would answer each other), so the manager has no group to join; ``ExternalSession.join_group`` stays
on the contract for when that is lifted.
"""

from __future__ import annotations

import asyncio
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

from .jsonfile import read_json, write_json

logger = logging.getLogger("zettcode.gateway")

#: The entry-point group a gateway agent plugin registers under.
ENTRY_POINT = "zettcode.gateway.external"

#: How many agents one gateway may keep running. A page cannot grow the roster without bound.
MAX_AGENTS = 64

#: Where the gateway keeps which agents it was asked to run, in its own folder.
ROSTER_FILE = "agents.json"

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
    #: Whether this gateway can run it now, and when it cannot, the sentence that says why (see ``AgentPlugin.probe``).
    runnable: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "avatar": avatar_data(self.avatar),
            "runnable": self.runnable,
            "reason": self.reason,
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

    def probe(self) -> str:
        """Say why this agent cannot be run by this gateway right now, or return an empty string when it can.

        Called in the gateway's own process (so a program is looked for on the PATH it will be run with), before a
        session is created and each time the types are listed. It must be quick and must not start the program. An
        agent that is not runnable is never registered or put on the roster by a page; one already
        on the roster is tried again later. The check can go stale between this call and a turn: a turn still answers
        with its own failure.
        """
        return ""


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
        self._kinds: dict[str, str] = {}
        #: The roster's agents that could not be started at the last try, so that a failure is reported once.
        self._unstartable: set[str] = set()
        #: The ids being started right now (the keeper's and a page's starts share the awaits of a connect).
        self._starting: dict[str, asyncio.Event] = {}
        #: The type of each agent on the roster, as the file said when it was last read or written.
        self._kept: dict[str, dict[str, str]] = {}
        self._roster()

    # -- the roster, kept across a restart --------------------------------------------------------
    @property
    def _roster_path(self) -> Path:
        return self.directory / ROSTER_FILE

    def _roster(self) -> dict[str, dict[str, str]]:
        """Return the agents this gateway was asked to keep, by session id; an unreadable file is an empty roster."""
        data = read_json(self._roster_path)
        roster: dict[str, dict[str, str]] = {}
        if isinstance(data, dict):
            roster = {
                key: {"kind": value["kind"], "title": str(value.get("title", ""))}
                for key, value in data.items()
                if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("kind"), str)
            }
        self._kept = {key: dict(entry) for key, entry in roster.items()}
        return roster

    def _write_roster(self, roster: dict[str, dict[str, str]]) -> None:
        try:
            write_json(self._roster_path, roster, indent=1)
        except OSError:
            # The agent is running; failing to remember it must not say otherwise.
            logger.exception("agents.roster_failed")
        else:
            self._kept = {key: dict(entry) for key, entry in roster.items()}

    async def restore(self) -> list[str]:
        """Start again the agents a previous run was asked to keep, and return the ids that came back.

        A stopped gateway closes its agents but keeps the roster, so a session the person created is still there after
        a restart. One that cannot start now (a type that is no longer installed, a broker that refused) stays on the
        roster for the next start; only :meth:`remove` forgets one.
        """
        back: list[str] = []
        roster = self._roster()
        self._unstartable &= roster.keys()
        for session_id, entry in roster.items():
            if session_id in self._running or session_id in self._starting:
                continue
            try:
                await self._start(entry["kind"], entry["title"], session_id, restoring=True)
            except AgentError as error:
                # Asked again every few seconds by the gateway's watcher: say it once, not at every look.
                if session_id not in self._unstartable:
                    self._unstartable.add(session_id)
                    logger.warning("agents.restore_failed", extra={"session": session_id, "error": str(error)})
            else:
                self._unstartable.discard(session_id)
                back.append(session_id)
        return back

    def available(self) -> list[AgentType]:
        """Return the agent types a page may create, each saying whether this gateway can run it now."""
        types = []
        for plugin in self._plugins.values():
            reason = _probe(plugin)
            types.append(
                AgentType(
                    plugin.name,
                    plugin.title or plugin.name,
                    plugin.description,
                    avatar_data(plugin.avatar),
                    runnable=not reason,
                    reason=reason,
                )
            )
        return types

    def avatar(self, kind: str) -> str:
        """Return the default picture a type offers, or an empty string."""
        plugin = self._plugins.get(kind)
        return avatar_data(plugin.avatar) if plugin is not None else ""

    def avatar_for(self, session_id: str) -> str:
        """Return the default picture for an agent this gateway runs or keeps, or an empty string."""
        kind = self.kind_of(session_id)
        return self.avatar(kind) if kind else ""

    def kept(self) -> dict[str, dict[str, str]]:
        """Return the agents on the roster whose type is installed, running or not, as id to ``kind`` and ``title``.

        What a page lists as its own, so that a stopped agent stays in the list (offline, with its name) and can be
        started again. An entry whose plugin is gone is not listed: nothing here could start it.
        """
        return {key: dict(entry) for key, entry in self._kept.items() if entry["kind"] in self._plugins}

    def kind_of(self, session_id: str) -> str:
        """Return the plugin type of an agent this gateway runs or was asked to keep, or an empty string.

        An agent on the roster that is not running (its broker was away, or it was never brought back) still has a
        type, which is what lets a page offer to start it again.
        """
        return self._kinds.get(session_id) or self._kept.get(session_id, {}).get("kind", "")

    def title_of(self, session_id: str) -> str:
        """Return the title an agent on the roster was given, or an empty string."""
        return self._kept.get(session_id, {}).get("title", "")

    def running(self) -> dict[str, ExternalSession]:
        """Return the agents this gateway started, by session id."""
        return dict(self._running)

    async def create(self, kind: str, title: str = "", session_id: str = "") -> ExternalSession:
        """Start one agent and return its session.

        Raises:
            AgentError: The type is unknown, the id is taken or malformed, or the broker refused the registration.
        """
        plugin = self._plugins.get(kind)
        if plugin is None:
            raise AgentError(f"there is no external agent type {kind!r}")
        session_id = session_id or f"web-{secrets.token_hex(6)}"
        if session_id in self._starting:
            # The keeper (or another request) is bringing this one up right now: wait for that rather than refuse.
            await self._starting[session_id].wait()
        running = self._running.get(session_id)
        if running is not None:
            if self._kinds.get(session_id) != kind:
                raise AgentError(f"the external agent {session_id!r} runs as another type, not {kind!r}")
            # Starting an agent that already runs is not an error: "start it again" is what the person asked for, and
            # it is on the roster by now (a page that raced the keeper only has to hear that it is there).
            roster = self._roster()
            if session_id not in roster:
                roster[session_id] = {"kind": kind, "title": title or plugin.title or kind}
                self._write_roster(roster)
            return running
        session = await self._start(kind, title, session_id)
        roster = self._roster()
        roster[session_id] = {"kind": kind, "title": title or self._plugins[kind].title or kind}
        self._write_roster(roster)
        return session

    async def _start(self, kind: str, title: str, session_id: str, *, restoring: bool = False) -> ExternalSession:
        plugin = self._plugins.get(kind)
        if plugin is None:
            raise AgentError(f"there is no external agent type {kind!r}")
        if session_id in self._running:
            raise AgentError(f"the external agent {session_id!r} is already running")
        if session_id in self._starting:
            raise AgentError(f"the external agent {session_id!r} is still starting")
        if len(self._running) + len(self._starting) >= MAX_AGENTS:
            raise AgentError(f"a gateway may run at most {MAX_AGENTS} external agents")
        # Before anything is registered: a session that connects cannot be told from a working one by the broker, and a
        # roster entry for one that cannot run would be brought back every few seconds for nothing.
        reason = _probe(plugin)
        if reason:
            raise AgentError(reason)
        session: ExternalSession | None = None
        # Held across the awaits below: the keeper and a page may both ask for the same id, and the second must see it.
        self._starting[session_id] = asyncio.Event()
        try:
            session = plugin.create(session_id, title or plugin.title or kind)
            await session.connect()
            if restoring and session_id not in self._roster():
                # Removed while it was coming up: the page was told it is gone, so it must not come up behind it.
                raise AgentError(f"the external agent {session_id!r} was removed while it was starting")
        except Exception as error:  # noqa: BLE001 - every failure becomes a GatewayError sentence at the API edge
            if session is not None:
                await session.close()
            raise AgentError(str(error)) from error
        finally:
            self._starting.pop(session_id).set()
        self._running[session_id] = session
        self._kinds[session_id] = kind
        return session

    async def remove(self, session_id: str) -> bool:
        """Stop one agent and drop it from the roster; return whether there was one to stop or to forget.

        An agent that is being started right now (by the keeper or a page) is waited for first, so that it is the
        running one that is stopped and forgotten, and not one that comes up behind the removal.
        """
        if session_id in self._starting:
            await self._starting[session_id].wait()
        session = self._running.pop(session_id, None)
        self._kinds.pop(session_id, None)
        roster = self._roster()
        kept = roster.pop(session_id, None) is not None
        if kept:
            self._write_roster(roster)
        if session is None:
            return kept
        await session.close()
        return True

    async def close(self) -> None:
        """Stop every agent this manager started; the roster stays, so the next start brings them back."""
        running, self._running = list(self._running.values()), {}
        for session in running:
            await session.close()


def _probe(plugin: AgentPlugin) -> str:
    """Return the plugin's reason it cannot run, or an empty string; a probe that itself fails is a reason."""
    try:
        return plugin.probe().strip()
    except Exception as error:  # noqa: BLE001 - a broken probe must not hide the other types or stop the gateway
        logger.exception("external_agent.probe_failed", extra={"agent": plugin.name})
        return f"{plugin.title or plugin.name} could not be checked: {type(error).__name__}: {error}"


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
