"""``/hub``: who is here, what the daemons are doing, and who talked to whom, on one full-screen page with three tabs.

The gateway's page shows this in a browser; this is the same picture where the work happens. What it reads is the
broker's roster and message graph through the SDK, the sessions stored for this workspace, and the daemons' records
through :mod:`zettcode.sdk.daemons`, so nothing new is listened to and nothing is stored here.

* **Graph**: the busiest sessions as boxes, coloured by state, and a line between two that exchanged messages, with
  the number beside the end it is drawn from (:mod:`~zettcode.commands.hub_graph` says how). ``Up``/``Down`` select a
  node, which keeps its lines and dims the rest.
* **Sessions**: the broker's roster, then the sessions stored on this machine that no process has registered, which
  are listed offline. ``Enter`` on an offline one starts a daemon that resumes it.
* **Daemons**: every daemon on the machine. ``s`` stops the one under the mark and ``Enter`` starts one whose process
  is gone.

``Tab`` and ``Shift-Tab`` (or the arrows sideways) move between the tabs and ``r`` reads everything again. The page
shows what the last reading found; it does not follow the broker by itself.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.commands import hub_graph
from zettcode.commands.hub_graph import Link, Node, Picture
from zettcode.plugin_api.commands import CommandContext, CommandHost, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import SEPARATOR, Canvas, ListItem, ListPage, Theme, event_key
from zettcode.tui.render import Style, display_width

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext

__all__ = ["HubCommand", "HubData", "HubPage"]

#: The three tabs, in the order Tab walks them, and the position of each.
TABS = ("Graph", "Sessions", "Daemons")
GRAPH, SESSIONS, DAEMONS = range(len(TABS))

#: What a daemon's status says when its process is gone, or when nothing says it is running.
GONE = ("dead", "unknown")

#: The smallest area the picture is drawn in; below it the page says so rather than draw boxes on top of each other.
MIN_GRAPH_WIDTH = 40
MIN_GRAPH_HEIGHT = 7

#: Rows above the picture (blank, tabs, summary, note) and below it (legend, keys), and the page height from which
#: the legend is drawn at all.
TOP_ROWS = 4
BOTTOM_ROWS = 3
LEGEND_FROM = 9


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
class StoredSession:
    """One session kept on disk for this workspace that no process has registered: ``Enter`` resumes it."""

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
    offline: tuple[StoredSession, ...] = ()
    note: str = ""
    nodes: tuple[Node, ...] = ()
    links: tuple[Link, ...] = ()
    #: Whether the message graph could be read; an empty picture says which of the two it is.
    graph_ok: bool = True


def _described(state: str, rest: str) -> tuple[str, Callable[[Theme], list[tuple[str, str | None]]]]:
    """Return a row's description and the same text in colours: the state's dot and word in its own colour."""
    head = f"{hub_graph.glyph(state)} {state}"

    def parts(theme: Theme) -> list[tuple[str, str | None]]:
        return [(head, hub_graph.colours(theme)[state]), (rest, None)]

    return head + rest, parts


def _session_rows(data: HubData) -> list[ListItem]:
    rows = []
    for peer in data.peers:
        state = hub_graph.state_of(peer.status, peer.kind)
        # An outsider's state word is its kind already, so the kind is not said twice.
        kind = f" {SEPARATOR} {peer.kind}" if peer.kind != state else ""
        text, parts = _described(state, f" {SEPARATOR} {peer.title or 'untitled'}{kind} {SEPARATOR} {peer.workspace}")
        rows.append(ListItem(peer.handle, peer.handle, text, parts=parts))
    for stored in data.offline:
        text, parts = _described("offline", f" {SEPARATOR} on disk {SEPARATOR} enter resumes it")
        rows.append(ListItem(stored.session_id, stored.title, text, parts=parts))
    return rows


def _daemon_rows(data: HubData) -> list[ListItem]:
    rows = []
    for daemon in data.daemons:
        state = "stopped" if daemon.status in GONE else hub_graph.state_of(daemon.status, "")
        # The state word already says working or idle; the daemon's own word is added only when it says more.
        said = f" {SEPARATOR} {daemon.status}" if daemon.status != state else ""
        text, parts = _described(
            state, f"{said} {SEPARATOR} {daemon.model or 'no model'} {SEPARATOR} {daemon.workspace}"
        )
        rows.append(ListItem(daemon.session_id, daemon.label or daemon.session_id, text, parts=parts))
    return rows


def _no_rows(data: HubData) -> list[ListItem]:
    """The picture has no rows: it is drawn by the page."""
    return []


#: What each tab lists, in the order :data:`TABS` names them.
_ROWS: tuple[Callable[[HubData], list[ListItem]], ...] = (_no_rows, _session_rows, _daemon_rows)


class HubPage(ListPage):
    """The three tabs, with the mark kept per tab and the keys that act on the row or node under it."""

    def __init__(
        self,
        data: HubData,
        *,
        on_close: Callable[[], None],
        on_stop: Callable[[str], None] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        """Start on the graph, with the first row of each list marked and no node selected."""
        self.data = data
        self.tab = GRAPH
        self.marks = [0] * len(TABS)
        #: The node whose lines are kept bright, by key; ``None`` shows every line as it is.
        self.selected: str | None = None
        self.on_stop = on_stop
        self.on_start = on_start
        self.on_refresh = on_refresh
        self._picture = Picture()
        self._picture_key: tuple[object, ...] | None = None
        super().__init__(
            _ROWS[GRAPH](data),
            title="Hub",
            subtitle=data.note or None,
            footer=self._footer(),
            on_cancel=on_close,
            visible_rows=None,
        )

    # -- what the reader sees ---------------------------------------------------------------------------
    def _footer(self) -> str:
        """Return the keys this tab takes."""
        common = f"tab next {SEPARATOR} shift-tab back {SEPARATOR} r refresh {SEPARATOR} esc close"
        if self.tab == GRAPH:
            return f"up/down select a node {SEPARATOR} {common}"
        if self.tab == SESSIONS:
            return f"enter resume an offline one {SEPARATOR} {common}"
        return f"enter start a stopped one {SEPARATOR} s stop {SEPARATOR} {common}"

    def render(self, canvas: Canvas) -> None:
        """Fill the page, then the tabs (the open one in the accent colour), the tab's body, and the keys."""
        if self.rect.empty:
            return
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
            x += display_width(drawn) + gap
        if self.tab == GRAPH:
            self._draw_graph(canvas, hint, room)
        else:
            if self.subtitle is not None:
                canvas.draw_text(self.rect.x + 2, self.rect.y + 2, self.subtitle, hint, max_width=room)
            self.list.render(canvas)
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def _picture_for(self, width: int, height: int) -> Picture:
        """Return the laid-out graph for this size, laid out again only when the data or the size changed."""
        key = (self.data.nodes, self.data.links, width, height)
        if key != self._picture_key:
            self._picture = hub_graph.layout(self.data.nodes, self.data.links, width, height)
            self._picture_key = key
            if self.selected is not None and all(node.key != self.selected for node in self._picture.nodes):
                self.selected = None
        return self._picture

    def _draw_graph(self, canvas: Canvas, hint: Style, room: int) -> None:
        """Draw the summary, the note, the picture and the legend, or say why there is no picture."""
        theme = self.theme
        left = self.rect.x + 2
        top = self.rect.y + TOP_ROWS
        height = self.rect.bottom - BOTTOM_ROWS - top
        data = self.data
        if data.note:
            canvas.draw_text(left, self.rect.y + 3, data.note, hint, max_width=room)
        picture = Picture()
        if not data.nodes:
            said = "no session has talked to another yet" if data.graph_ok else "the message graph cannot be read"
        elif height < MIN_GRAPH_HEIGHT or room < MIN_GRAPH_WIDTH:
            said = "too small for the graph"
        else:
            said = ""
            picture = self._picture_for(room, height)
        if data.nodes:
            line = hub_graph.summary(data.nodes, data.links, picture, self.selected)
            canvas.draw_text(left, self.rect.y + 2, line, hint, max_width=room)
        if said:
            row = min(max(top + max(height, 1) // 2, top), self.rect.bottom - 2)
            column = self.rect.x + max(2, (self.rect.width - display_width(said)) // 2)
            canvas.draw_text(column, row, said, hint, max_width=room)
        else:
            hub_graph.paint(canvas, theme, left, top, picture, self.selected)
        if self.rect.height >= LEGEND_FROM:
            x = left
            for group in hub_graph.legend(theme):
                wide = sum(display_width(text) for text, _ in group)
                if x + wide > left + room:
                    break
                for text, style in group:
                    canvas.draw_text(x, self.rect.bottom - 2, text, style)
                    x += display_width(text)

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
        self.footer = self._footer()
        self.request_layout()

    # -- the keys ---------------------------------------------------------------------------------------
    def capture_event(self, event, host) -> bool:
        """Take Tab, Shift-Tab, the node selection and the daemon keys before the list does."""
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
        if self.tab == GRAPH and key in ("up", "down"):
            self._select(1 if key == "down" else -1)
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

    def _select(self, step: int) -> None:
        """Move the selection through the nodes drawn, busiest first, with "none selected" between the ends."""
        ring: list[str | None] = [None, *(node.key for node in self._picture.nodes)]
        here = ring.index(self.selected) if self.selected in ring else 0
        self.selected = ring[(here + step) % len(ring)]
        self.request_layout()

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
            if chosen is not None and chosen.status in GONE:
                self.on_start(chosen.session_id)
        elif self.tab == SESSIONS and 0 <= self.list.selected < len(self.list.items):
            wanted = self.list.items[self.list.selected].value
            if any(stored.session_id == wanted for stored in self.data.offline):
                self.on_start(str(wanted))
        return None


class HubCommand(TuiPlugin):
    """``/hub``: the graph, the sessions and the daemons, and the three actions a row takes: stop, start, resume."""

    name = "hub-command"
    description = "who is here, the daemons, and who talked to whom"

    #: The page in front, so a failed action can say so on it; ``None`` when no page is open.
    _page: HubPage | None = None
    #: The actions started from the page, kept so their failures are read rather than logged at the interpreter.
    _actions: set[asyncio.Future[None]]
    #: Session ids a daemon is being started for, so a second Enter does not start a second one.
    _starting: set[str]

    def __init__(self) -> None:
        """Start with no page and no action running."""
        self._page = None
        self._actions = set()
        self._starting = set()

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

        A daemon resumes on the workspace and model it had. A stored session is one of the reader's workspace (the
        store is listed per workspace), so it resumes there, on the first configured model and the default shell
        level (``/resume`` would continue on the session's own model). One start per session at a time: a second
        ``Enter`` while the first is waiting is told so, since two daemons would share one record and one lock.
        """
        from zettcode.sdk.daemons import spawn_daemon

        chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
        if chosen is None and not any(stored.session_id == session_id for stored in page.data.offline):
            return
        if chosen is not None and chosen.status not in GONE:
            page.note(f"{chosen.label or session_id[:8]} is running")
            return
        if session_id in self._starting:
            page.note("already starting that one")
            return
        self._starting.add(session_id)
        page.note("starting\u2026")
        try:
            workspace = (chosen.workspace if chosen else "") or str(client.workspace)  # type: ignore[attr-defined]
            started = await spawn_daemon(workspace, model=(chosen.model if chosen else "") or None, resume=session_id)
        except Exception as error:  # noqa: BLE001 - the page says what happened, whatever it was
            note = str(error)
        else:
            note = f"started {started.session_id[:8]}"
        finally:
            self._starting.discard(session_id)
        await self._refresh(page, client)
        page.note(note)

    async def _read(self, client: object) -> HubData:
        """Read the three tabs: the broker's roster and graph, the stored sessions, and the daemons' records.

        One reading decides who is present: the graph's own roster, the cached peers and the daemons that are
        running all count, so a session is offered as offline only when none of them has it.
        """
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
        try:
            me = client.session.id  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a client with no session still has a roster to show
            me = ""
        try:
            # The fifty newest of this workspace; a longer store is cut there rather than paged.
            listed = await client.sessions.list(limit=50)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - a store that cannot be read costs only the offline list
            note = f"the stored sessions cannot be read: {error}"
            listed = ()
        graph_ok = True
        try:
            graph = await client.traffic_graph()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - without a broker the picture is empty, the lists still work
            graph, graph_ok = {}, False
            note = note or f"the message graph cannot be read: {error}"
        present = {peer.session_id for peer in peers} | {me}
        present |= {str(entry.get("session_id", "")) for entry in graph.get("sessions", ())}
        present |= {daemon.session_id for daemon in daemons if daemon.status not in GONE}
        offline = tuple(StoredSession(info.id, info.title or info.id[:8]) for info in listed if info.id not in present)
        # The picture is of this workspace: another project's dead daemons are on the Daemons tab, not in it, and a
        # session's own title wins over its daemon's name.
        here = Path(client.workspace).resolve()  # type: ignore[attr-defined]
        ours = [daemon for daemon in daemons if _is_in(daemon.workspace, here)]
        titles = {info.id: info.title or info.id[:8] for info in listed}
        for daemon in ours:
            titles.setdefault(daemon.session_id, daemon.label)
        nodes, links = hub_graph.build(
            graph, me=me, titles=titles, stopped=[daemon.session_id for daemon in ours if daemon.status in GONE]
        )
        if not graph_ok:
            # Nothing to say about who talks to whom, so the picture is empty and says why, not a lone stopped box.
            nodes, links = (), ()
        return HubData(
            peers=peers, daemons=daemons, offline=offline, note=note, nodes=nodes, links=links, graph_ok=graph_ok
        )


def _is_in(workspace: str, here: Path) -> bool:
    """Return whether a daemon's workspace is the reader's."""
    try:
        return bool(workspace) and Path(workspace).expanduser().resolve() == here
    except OSError:
        return False
