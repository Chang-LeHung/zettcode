"""``/hub``: who is here, what the daemons are doing, and who talked to whom, on one page with three tabs.

The gateway's page shows this in a browser; this is the same picture where the work happens. What it reads is the
broker's roster through the SDK, and the daemons' records through :mod:`zettcode.sdk.daemons`, so nothing new is
listened to and nothing is stored here.

The page is full-screen. The first tab is the picture (:mod:`~zettcode.commands.hub_graph`): sessions as boxes coloured
by state, messages as lines, a legend under it. The other two tabs are lists, :class:`~zettcode.tui.ListPage`
underneath: ``Tab`` and ``Shift-Tab`` (or the arrows alone)
move between the three, ``Up``/``Down`` through the rows, ``s`` stops the daemon under the mark, ``Enter`` starts one
whose process is gone, and ``r`` reads everything again. A daemon whose process is gone is listed as ``dead`` or
``unknown``; a session stored on this machine that is not registered is listed offline, which is what the broker cannot
say by itself.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from zettcode.commands import hub_graph
from zettcode.commands.hub_graph import Link, Node
from zettcode.plugin_api.commands import CommandContext, CommandHost, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import SEPARATOR, Canvas, ListItem, ListPage, event_key

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext
    from zettcode.tui.render import Style
__all__ = ["HubCommand", "HubData", "HubPage"]

#: The three tabs, in the order Tab walks them; the first is the picture, the other two are lists.
TABS = ("Graph", "Sessions", "Daemons")

#: The tab that lists the sessions, where Enter resumes an offline one.
SESSIONS = 1

#: The tab that lists daemons, where keys act on a row.
DAEMONS = 2


@dataclass(frozen=True, slots=True)
class Peer:
    """One session the broker knows about."""

    handle: str
    title: str
    status: str
    workspace: str
    kind: str = "session"
    session_id: str = ""


@dataclass(frozen=True, slots=True)
class Stored:
    """One session kept on disk for this workspace that no process has registered: Enter resumes it."""

    session_id: str
    title: str


@dataclass(frozen=True, slots=True)
class Daemon:
    """One daemon recorded on this machine, running or not."""

    session_id: str
    label: str
    status: str
    model: str = ""
    workspace: str = ""


@dataclass(frozen=True, slots=True)
class HubData:
    """Everything the three tabs show, read once per refresh."""

    peers: tuple[Peer, ...] = ()
    daemons: tuple[Daemon, ...] = ()
    offline: tuple[Stored, ...] = ()
    note: str = ""
    nodes: tuple[Node, ...] = ()
    links: tuple[Link, ...] = ()


def _described(state: str, rest: str) -> tuple[str, Callable[[Any], list[tuple[str, str | None]]]]:
    """Return a row's description and the same text in colours: the state's dot and word in its own colour."""
    head = f"{hub_graph.glyph(state)} {state}"

    def parts(theme: Any) -> list[tuple[str, str | None]]:
        return [(head, hub_graph.colours(theme)[0][state]), (rest, None)]

    return head + rest, parts


def _session_rows(data: HubData) -> list[ListItem]:
    rows = []
    for peer in data.peers:
        text, parts = _described(
            hub_graph.state_of(peer.status, peer.kind),
            f" {SEPARATOR} {peer.title or 'untitled'} {SEPARATOR} {peer.kind} {SEPARATOR} {peer.workspace}",
        )
        rows.append(ListItem(peer.handle, peer.handle, text, parts=parts))
    for stored in data.offline:
        text, parts = _described("offline", f" {SEPARATOR} on disk {SEPARATOR} enter resumes it")
        rows.append(ListItem(stored.session_id, stored.title, text, parts=parts))
    return rows


def _daemon_rows(data: HubData) -> list[ListItem]:
    rows = []
    for daemon in data.daemons:
        state = "stopped" if daemon.status in ("dead", "unknown") else hub_graph.state_of(daemon.status, "")
        text, parts = _described(
            state,
            f" {SEPARATOR} {daemon.status} {SEPARATOR} {daemon.model or 'no model'} {SEPARATOR} {daemon.workspace}",
        )
        rows.append(ListItem(daemon.session_id, daemon.label or daemon.session_id, text, parts=parts))
    return rows


#: What each tab shows, in the order :data:`TABS` names them.
_ROWS: tuple[Callable[[HubData], list[ListItem]], ...] = (lambda data: [], _session_rows, _daemon_rows)


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
        if self.tab == DAEMONS:
            return f"enter start a stopped one {SEPARATOR} s stop {SEPARATOR} {common}"
        if self.tab == SESSIONS:
            return f"enter resume an offline one {SEPARATOR} {common}"
        return common

    def render(self, canvas: Canvas) -> None:
        """Fill the page, then the tabs (the open one in the accent colour), the list, and the keys."""
        if self.rect.empty:
            return
        from zettcode.tui.render import Style

        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface_alt))
        heading = Style(foreground=theme.text, background=theme.surface_alt, bold=True)
        open_tab = Style(foreground=theme.surface_alt, background=theme.accent, bold=True)
        hint = Style(foreground=theme.muted, background=theme.surface_alt)
        x, y = self.rect.x + 2, self.rect.y + 1
        room = max(0, self.rect.width - 4)
        # Three columns of air between the name and the tabs, and between the tabs themselves; the open one carries a
        # column of its own inside the accent band so the band never touches its neighbour.
        gap = 3
        canvas.draw_text(x, y, "Hub", heading, max_width=room)
        x += len("Hub") + gap
        for index, name in enumerate(TABS):
            drawn = f" {name} " if index == self.tab else name
            style = open_tab if index == self.tab else heading
            canvas.draw_text(x, y, drawn, style, max_width=max(0, room - (x - self.rect.x)))
            x += len(drawn) + gap
        if self.subtitle is not None:
            canvas.draw_text(self.rect.x + 2, self.rect.y + 2, self.subtitle, hint, max_width=room)
        if self.tab == 0:
            self._draw_graph(canvas, hint, room)
        else:
            self.list.render(canvas)
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def _draw_graph(self, canvas: Canvas, hint: Style, room: int) -> None:
        """Draw the picture between the tab line and the legend, or say that there is nothing to draw."""
        theme = self.theme
        top = self.rect.y + 4
        height = self.rect.bottom - 3 - top
        if self.subtitle is None and self.data.nodes:
            nodes, working = self.data.nodes, sum(1 for node in self.data.nodes if node.state == "working")
            cut = max(0, len(nodes) - hub_graph.MAX_NODES)
            summary = (
                f"{len(nodes)} nodes {SEPARATOR} {working} working {SEPARATOR} "
                f"{sum(link.count for link in self.data.links)} messages"
                + (f" {SEPARATOR} {cut} not drawn" if cut else "")
            )
            canvas.draw_text(self.rect.x + 2, self.rect.y + 2, summary, hint, max_width=room)
        if not self.data.nodes:
            message = "no session has talked to another yet"
            canvas.draw_text(
                self.rect.x + max(2, (self.rect.width - len(message)) // 2), top + height // 2, message, hint
            )
        elif height >= 5 and room >= 20:
            hub_graph.draw(canvas, theme, self.rect.x + 2, top, room, height, self.data.nodes, self.data.links)
        x = self.rect.x + 2
        for text, style in hub_graph.legend(theme):
            if x + len(text) > self.rect.x + 2 + room:
                break
            canvas.draw_text(x, self.rect.bottom - 2, text, style)
            x += len(text)

    def set_data(self, data: HubData) -> None:
        """Take a fresh reading, and keep the mark where it was on the tab in front."""
        self.marks[self.tab] = max(0, self.list.selected)
        self.data = data
        self.subtitle = self.data.note or None
        self._show(self.tab)

    def note(self, text: str) -> None:
        """Say one line under the tabs — what a key just did, or why it could not."""
        self.data = dataclasses.replace(self.data, note=text)
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
        if self.tab in (SESSIONS, DAEMONS) and key == "enter":
            self._chosen()
            return True
        if self.tab == DAEMONS and key == "s" and self.on_stop is not None:
            chosen = self._daemon()
            if chosen is not None:
                self.on_stop(chosen.session_id)
            return True
        return super().capture_event(event, host)

    def _daemon(self) -> Daemon | None:
        """Return the daemon under the mark, by the id the row carries: a refresh may have reordered the list."""
        items = self.list.items
        if not (0 <= self.list.selected < len(items)):
            return None
        chosen = items[self.list.selected].value
        return next((daemon for daemon in self.data.daemons if daemon.session_id == chosen), None)

    def _chosen(self) -> None:
        """Enter starts what is under the mark: a daemon whose process is gone, or a stored session no one runs."""
        if self.on_start is None:
            return None
        if self.tab == DAEMONS:
            chosen = self._daemon()
            if chosen is not None and chosen.status in ("dead", "unknown"):
                self.on_start(chosen.session_id)
        elif self.tab == SESSIONS and 0 <= self.list.selected < len(self.list.items):
            wanted = self.list.items[self.list.selected].value
            if any(stored.session_id == wanted for stored in self.data.offline):
                self.on_start(str(wanted))
        return None


class HubCommand(TuiPlugin):
    """``/hub``: the sessions, the daemons and the graph, and the two actions a daemon row takes."""

    name = "hub-command"
    description = "who is here, the daemons, and who talked to whom"

    #: The page in front, so a failed action can say so on it; ``None`` when no page is open.
    _page: HubPage | None = None
    #: The actions started from the page, kept so their failures are read rather than logged at the interpreter.
    _actions: set[asyncio.Future[None]]

    def __init__(self) -> None:
        """Start with no page and no action running."""
        self._page = None
        self._actions = set()

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/hub``; it only reads, so it opens over a running request rather than turning the reader away."""
        if ctx.tui is None:
            return
        ctx.tui.register_command(
            "hub",
            "who is here, the daemons and who talked to whom",
            self.hub,
            when_busy="now",
        )

    async def hub(self, context: CommandContext) -> CommandResult:
        """Open the page, and wire its keys to the SDK's daemon actions."""
        host = context.require_host()
        client = host.client
        data = await self._read(client)
        page = HubPage(
            data,
            on_close=self._closer(host),
            on_refresh=lambda: self._start(self._refresh(page, client)),
            on_stop=lambda session_id: self._start(self._stop(page, client, session_id)),
            on_start=lambda session_id: self._start(self._resume(page, client, session_id)),
        )
        self._page = page
        return CommandResult(widget=page)

    def _closer(self, host: CommandHost) -> Callable[[], None]:
        """Return what closing the page runs: forget it here, then let the shell close it.

        A late failure then has nothing to write on, and the page it would have written on is gone.
        """

        def close() -> None:
            self._page = None
            host.close_page()

        return close

    def _start(self, task: Awaitable[None]) -> None:
        """Run one action on the loop the page was opened on, and keep it so a failure is not lost."""
        running = asyncio.ensure_future(task)
        self._actions.add(running)
        running.add_done_callback(self._done)

    def _done(self, finished: asyncio.Future[None]) -> None:
        """Forget an action, and say what it failed with, on the page."""
        self._actions.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None and self._page is not None:
            self._page.note(str(error))

    async def _refresh(self, page: HubPage, client: object) -> None:
        """Read everything again, and show it."""
        page.set_data(await self._read(client))

    async def _stop(self, page: HubPage, client: object, session_id: str) -> None:
        """Stop one daemon, then show what that changed."""
        from zettcode.sdk.daemons import stop_daemon

        said = await stop_daemon(session_id, keep=True)
        await self._refresh(page, client)
        page.note(said)

    async def _resume(self, page: HubPage, client: object, session_id: str) -> None:
        """Start a background agent on a session that is not running: a daemon's record, or a stored session.

        A daemon resumes on the workspace and model it had. A stored session is one of this workspace's (the store is
        listed per workspace), so it resumes here, on the first configured model.
        """
        from zettcode.sdk.daemons import spawn_daemon

        chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
        if chosen is None and not any(stored.session_id == session_id for stored in page.data.offline):
            return
        workspace = (chosen.workspace if chosen else "") or "."
        model = (chosen.model if chosen else "") or None
        try:
            started = await spawn_daemon(workspace, model=model, resume=session_id)
        except Exception as error:  # noqa: BLE001 - the page says what happened, whatever it was
            note = str(error)
        else:
            note = f"started {started.session_id[:8]}"
        await self._refresh(page, client)
        page.note(note)

    async def _read(self, client: object) -> HubData:
        """Read the three tabs: the broker's roster and graph, and the daemons' records."""
        from zettcode.sdk.daemons import list_daemons

        peers = tuple(
            Peer(
                handle=peer.handle,
                title=peer.title,
                status=peer.status,
                workspace=peer.workspace,
                kind=peer.kind,
                session_id=peer.session_id,
            )
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
        offline: tuple[Stored, ...] = ()
        try:
            # The fifty newest of this workspace; a longer store is cut there rather than paged.
            listed = await client.sessions.list(limit=50)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - a store that cannot be read costs only the offline list
            note = note or f"the stored sessions cannot be read: {error}"
            listed = ()
        # Registered by id, and never the reader's own: `peers()` leaves self out and the store keeps it.
        registered = {peer.session_id for peer in peers} | {client.session.id}  # type: ignore[attr-defined]
        offline = tuple(Stored(info.id, info.title or info.id[:8]) for info in listed if info.id not in registered)
        try:
            graph = await client.traffic_graph()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - without a broker the picture is empty, the lists still work
            graph = {}
            note = note or f"the message graph cannot be read: {error}"
        titles = {info.id: info.title or info.id[:8] for info in listed}
        titles.update({daemon.session_id: daemon.label for daemon in daemons})
        stopped = [daemon.session_id for daemon in daemons if daemon.status in ("dead", "unknown")]
        nodes, links = hub_graph.build(graph, me=client.session.id, titles=titles, stopped=stopped)  # type: ignore[attr-defined]
        return HubData(peers=peers, daemons=daemons, offline=offline, note=note, nodes=nodes, links=links)
