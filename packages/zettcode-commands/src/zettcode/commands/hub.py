"""``/hub``: who is here, what the daemons are doing, and who talked to whom, on one page with three tabs.

The gateway's page shows this in a browser; this is the same picture where the work happens. What it reads is the
broker's own view — the roster, the message graph — through the SDK, and the daemons' records through
:mod:`zettcode.sdk.daemons`, so nothing new is listened to and nothing is stored here.

The page is a list per tab, :class:`~zettcode.tui.ListPage` underneath: ``Tab`` and ``Shift-Tab`` (or the arrows alone)
move between the three, ``Up``/``Down`` through the rows, ``s`` stops and ``S`` starts the daemon under the mark, and
``r`` reads everything again. A daemon whose process is gone is listed as ``dead``; a session on disk that is not
registered is listed offline, which is what the broker cannot say by itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.panels import bottom_panel
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import SEPARATOR, ListItem, ListPage, event_key

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext

__all__ = ["HUB_ROWS", "HubCommand", "HubData", "HubPage"]

#: Rows the page asks for when it is anchored to the bottom edge: the tab line, a blank, the list, and the keys.
HUB_ROWS = 18

#: The three tabs, in the order Tab walks them.
TABS = ("Sessions", "Daemons", "Graph")


@dataclass(frozen=True, slots=True)
class Peer:
    """One session the broker knows about."""

    handle: str
    title: str
    status: str
    workspace: str
    kind: str = "session"


@dataclass(frozen=True, slots=True)
class Daemon:
    """One daemon recorded on this machine, running or not."""

    session_id: str
    label: str
    status: str
    model: str = ""
    workspace: str = ""


@dataclass(frozen=True, slots=True)
class Edge:
    """One pair that exchanged messages."""

    source: str
    target: str
    count: int


@dataclass(frozen=True, slots=True)
class HubData:
    """Everything the three tabs show, read once per refresh."""

    peers: tuple[Peer, ...] = ()
    daemons: tuple[Daemon, ...] = ()
    offline: tuple[str, ...] = ()
    edges: tuple[Edge, ...] = ()
    recent: tuple[str, ...] = ()
    note: str = ""


def _session_rows(data: HubData) -> list[ListItem]:
    rows = [
        ListItem(
            peer.handle,
            peer.handle,
            f"{peer.status} {SEPARATOR} {peer.title or 'untitled'} {SEPARATOR} "
            f"{peer.kind} {SEPARATOR} {peer.workspace}",
        )
        for peer in data.peers
    ]
    rows += [ListItem(name, name, f"offline {SEPARATOR} on disk, not registered") for name in data.offline]
    return rows


def _daemon_rows(data: HubData) -> list[ListItem]:
    return [
        ListItem(
            daemon.session_id,
            daemon.label or daemon.session_id,
            f"{daemon.status} {SEPARATOR} {daemon.model or 'no model'} {SEPARATOR} {daemon.workspace}",
        )
        for daemon in data.daemons
    ]


def _graph_rows(data: HubData) -> list[ListItem]:
    rows = [
        ListItem(
            f"{edge.source}->{edge.target}",
            f"{edge.source} \u2500\u2500{edge.count}\u2500\u2500\u25b6 {edge.target}",
            "",
        )
        for edge in data.edges
    ]
    rows += [ListItem(f"recent-{index}", line, "") for index, line in enumerate(data.recent)]
    return rows


#: What each tab shows, in the order :data:`TABS` names them.
_ROWS: tuple[Callable[[HubData], list[ListItem]], ...] = (_session_rows, _daemon_rows, _graph_rows)


class HubPage(ListPage):
    """The three tabs, with the mark kept per tab and the daemon keys acting on the row under it."""

    def __init__(
        self,
        data: HubData,
        *,
        on_close: Callable[[], None],
        on_stop: Callable[[str], None] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        """Start on the sessions tab, with the first row marked."""
        self.data = data
        self.tab = 0
        self.marks = [0, 0, 0]
        self.on_stop = on_stop
        self.on_start = on_start
        self.on_refresh = on_refresh
        super().__init__(
            _ROWS[0](data),
            title=self._title(),
            subtitle=data.note or None,
            footer=self._footer(),
            on_select=lambda item: self._chosen(),
            on_cancel=on_close,
            visible_rows=None,
        )

    # -- what the reader sees ---------------------------------------------------------------------------
    def _title(self) -> str:
        """Return the tab line, the open tab in brackets."""
        return "Hub  " + "  ".join(f"[{name}]" if index == self.tab else name for index, name in enumerate(TABS))

    def _footer(self) -> str:
        """Return the keys this tab takes."""
        common = f"tab next {SEPARATOR} shift-tab back {SEPARATOR} r refresh {SEPARATOR} esc close"
        if self.tab == 1:
            return f"enter start a stopped one {SEPARATOR} s stop {SEPARATOR} {common}"
        return common

    def set_data(self, data: HubData) -> None:
        """Take a fresh reading, and keep the mark where it was on the tab in front."""
        self.marks[self.tab] = max(0, self.list.selected)
        self.data = data
        self.subtitle = data.note or None
        self._show(self.tab)

    def note(self, text: str) -> None:
        """Say one line under the tabs — what a key just did, or why it could not."""
        self.data = HubData(
            peers=self.data.peers,
            daemons=self.data.daemons,
            offline=self.data.offline,
            edges=self.data.edges,
            recent=self.data.recent,
            note=text,
        )
        self.subtitle = text
        self.request_layout()

    def _show(self, tab: int) -> None:
        """Put one tab in front, with the mark it had."""
        self.tab = tab
        rows = _ROWS[tab](self.data)
        self.list.set_items(rows)
        self.list.selected = min(self.marks[tab], len(rows) - 1)
        self.title = self._title()
        self.footer = self._footer()
        self.request_layout()

    # -- the keys ---------------------------------------------------------------------------------------
    def capture_event(self, event, host) -> bool:
        """Take Tab, Shift-Tab and the daemon keys before the list does."""
        key = event_key(event)
        if key in ("tab", "right"):
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab + 1) % len(TABS))
            return True
        if key in ("backtab", "left"):
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab - 1) % len(TABS))
            return True
        if key == "r" and self.on_refresh is not None:
            self.on_refresh()
            return True
        if self.tab == 1 and key == "enter":
            self._chosen()
            return True
        if self.tab == 1 and key == "s" and self.on_stop is not None:
            chosen = self._daemon()
            if chosen is not None:
                self.on_stop(chosen.session_id)
            return True
        return super().capture_event(event, host)

    def _daemon(self) -> Daemon | None:
        """Return the daemon under the mark."""
        index = self.list.selected
        return self.data.daemons[index] if 0 <= index < len(self.data.daemons) else None

    def _chosen(self) -> None:
        """Enter on the daemons tab starts the daemon under the mark when it is not running."""
        if self.tab != 1 or self.on_start is None:
            return None
        chosen = self._daemon()
        if chosen is not None and chosen.status != "running":
            self.on_start(chosen.session_id)
        return None


class HubCommand(TuiPlugin):
    """``/hub``: the sessions, the daemons and the graph, and the two actions a daemon row takes."""

    name = "hub-command"
    description = "who is here, the daemons, and who talked to whom"

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/hub``; it reads, so it waits for a request to end rather than opening over one."""
        if ctx.tui is None:
            return
        ctx.tui.register_command(
            "hub",
            "who is here, the daemons and who talked to whom",
            self.hub,
            when_busy="refuse",
        )

    async def hub(self, context: CommandContext) -> CommandResult:
        """Open the page, and wire its keys to the SDK's daemon actions."""
        host = context.require_host()
        client = host.client
        data = await self._read(client)
        page = HubPage(
            data,
            on_close=host.close_page,
            on_refresh=lambda: self._start(self._refresh(page, client)),
            on_stop=lambda session_id: self._start(self._stop(page, client, session_id)),
            on_start=lambda session_id: self._start(self._resume(page, client, session_id)),
        )
        return CommandResult(widget=bottom_panel(page, rows=HUB_ROWS))

    @staticmethod
    def _start(task: Awaitable[None]) -> None:
        """Run one action on the loop the page was opened on."""
        asyncio.ensure_future(task)

    async def _refresh(self, page: HubPage, client: object) -> None:
        """Read everything again, and show it."""
        page.set_data(await self._read(client))

    async def _stop(self, page: HubPage, client: object, session_id: str) -> None:
        """Stop one daemon, then show what that changed."""
        from zettcode.sdk.daemons import stop_daemon

        said = await stop_daemon(session_id, keep=True)
        page.note(said)
        await self._refresh(page, client)

    async def _resume(self, page: HubPage, client: object, session_id: str) -> None:
        """Start a daemon whose record is still there, on the workspace and model it had."""
        from zettcode.sdk.daemons import spawn_daemon

        chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
        if chosen is None:
            return
        try:
            started = await spawn_daemon(chosen.workspace or ".", model=chosen.model or None, resume=session_id)
        except Exception as error:  # noqa: BLE001 - the page says what happened, whatever it was
            page.note(str(error))
        else:
            page.note(f"started {started.session_id[:8]}")
        await self._refresh(page, client)

    async def _read(self, client: object) -> HubData:
        """Read the three tabs: the broker's roster and graph, and the daemons' records."""
        from zettcode.sdk.daemons import list_daemons
        from zettcode.sdk.errors import ConfigurationError, SendError

        peers = tuple(
            Peer(handle=peer.handle, title=peer.title, status=peer.status, workspace=peer.workspace, kind=peer.kind)
            for peer in client.peers()  # type: ignore[attr-defined]
        )
        daemons = tuple(
            Daemon(
                session_id=info.session_id,
                label=info.name or info.title or info.session_id[:8],
                status=info.status,
                model=info.model or "",
                workspace=str(info.workspace or ""),
            )
            for info in await asyncio.to_thread(list_daemons)
        )
        note = ""
        edges: tuple[Edge, ...] = ()
        recent: tuple[str, ...] = ()
        try:
            graph = await client.traffic_graph()  # type: ignore[attr-defined]
        except (ConfigurationError, SendError) as error:
            note = f"the broker cannot be read: {error}"
        else:
            edges = tuple(
                Edge(source=str(edge.get("from", "")), target=str(edge.get("to", "")), count=int(edge.get("count", 0)))
                for edge in graph.get("edges", ())
            )
            edges = tuple(sorted(edges, key=lambda edge: -edge.count))[:12]
            recent = tuple(
                f"{message.get('from', '?')} \u2192 {message.get('to', '?')}: {str(message.get('text', ''))[:60]}"
                for message in graph.get("recent", ())[:5]
            )
        return HubData(peers=peers, daemons=daemons, edges=edges, recent=recent, note=note)
