"""``/hub``: who is here, what the daemons are doing, and who talked to whom, on one full-screen page with three tabs.

The gateway's page shows this in a browser; this is the same picture where the work happens. What it reads is the
broker's roster and message graph through the SDK, the sessions stored for this workspace, and the daemons' records
through :mod:`zettcode.sdk.daemons`, so nothing new is listened to and nothing is stored here.

* **Graph**: the busiest sessions as boxes, coloured by state, and a line between two that exchanged messages, with
  the number beside the end it is drawn from (:mod:`~zettcode.commands.hub_graph` says how). Every box has a place, so
  an arrow key selects the nearest box that way, which keeps its lines and dims the rest; ``Esc`` deselects.
* **Sessions**: the broker's roster, then the sessions stored on this machine that no process has registered, which
  are listed offline. Sessions are only looked at here: it is a daemon that can be started.
* **Daemons**: every daemon on the machine. ``s`` stops the one under the mark and ``Enter`` starts one whose process
  is gone, resuming the session it had.

``Tab`` and ``Shift-Tab`` are the only keys that change tab, ``r`` reads everything again, and the top right of the
page says when the last reading was and how long it took. The page shows what that reading found; it does not follow
the broker by itself.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.commands import hub_graph
from zettcode.commands.hub_graph import Link, Node, Picture
from zettcode.plugin_api.commands import CommandContext, CommandHost, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import SEPARATOR, Canvas, ListItem, ListPage, Rect, Theme, event_key
from zettcode.tui.render import Style, display_width, truncate

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext

__all__ = ["HubCommand", "HubData", "HubPage"]

#: The three tabs, in the order Tab walks them, and the position of each.
TABS = ("Graph", "Sessions", "Daemons")
GRAPH, SESSIONS, DAEMONS = range(len(TABS))

#: What a daemon's status says when its process is gone, or when nothing says it is running.
GONE = ("dead", "unknown")

#: The smallest area the picture is drawn in: room for two rows of boxes and a number between them, and for a box and
#: its neighbour side by side. Below it the page says so rather than draw a chain of two boxes.
MIN_GRAPH_WIDTH = 40
MIN_GRAPH_HEIGHT = 10

#: The largest rectangle lines are routed in; on a bigger screen the picture is centred in it.
MAX_ROUTED_WIDTH = 150
MAX_ROUTED_HEIGHT = 44

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
    """One session kept on disk for this workspace that no process has registered. Listed, not started."""

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
    #: When this reading was made and how long it took, step by step; drawn quietly at the top right of the page.
    read: str = ""


@dataclass(frozen=True, slots=True)
class Table:
    """What a list tab shows: its rows, the title of each column, and how wide each column after the name is."""

    items: list[ListItem]
    titles: tuple[str, ...] = ()
    widths: tuple[int, ...] = ()


#: The space between two columns of a table.
COLUMN_GAP = 2


def _table(titles: tuple[str, ...], rows: Sequence[tuple[str, str, str, tuple[str, ...]]]) -> Table:
    """Build a table whose first column is each row's name and whose second is its state.

    Args:
        titles: The title of every column, the name's first.
        rows: ``(value, name, state, cells)`` for each row: the cells are the columns after the state, and the state
            column is written as the state's dot and word, in the state's colour.
    """
    cells = [(f"{hub_graph.glyph(state)} {text}", *rest) for _, _, state, (text, *rest) in rows]
    widths = tuple(
        max([display_width(titles[index + 1])] + [display_width(row[index]) for row in cells])
        for index in range(len(titles) - 1)
    )
    items = []
    for (value, name, state, _), row in zip(rows, cells, strict=True):
        padded = [
            cell + " " * (width - display_width(cell) + COLUMN_GAP) for cell, width in zip(row, widths, strict=True)
        ]
        padded[-1] = row[-1]

        def parts(theme: Theme, state: str = state, padded: list[str] = padded) -> list[tuple[str, str | None]]:
            return [(padded[0], hub_graph.colours(theme)[state]), *((text, theme.muted) for text in padded[1:])]

        items.append(ListItem(value, name, "".join(padded), parts=parts))
    return Table(items, titles, widths)


def _session_table(data: HubData) -> Table:
    rows = [
        (
            peer.handle,
            peer.handle,
            hub_graph.state_of(peer.status, peer.kind),
            (hub_graph.state_of(peer.status, peer.kind), peer.title or "untitled", peer.workspace),
        )
        for peer in data.peers
    ]
    rows += [
        (stored.session_id, stored.title, "offline", ("offline", "on disk, no process", "")) for stored in data.offline
    ]
    return _table(("NAME", "STATE", "TITLE", "WORKSPACE"), rows)


def _daemon_table(data: HubData) -> Table:
    rows = []
    for daemon in data.daemons:
        state = "stopped" if daemon.status in GONE else hub_graph.state_of(daemon.status, "")
        # The state word already says working or idle; the daemon's own word follows only when it says more.
        said = state if daemon.status == state else f"{state} ({daemon.status})"
        rows.append(
            (
                daemon.session_id,
                daemon.label or daemon.session_id,
                state,
                (said, daemon.model or "no model", daemon.workspace),
            )
        )
    return _table(("NAME", "STATE", "MODEL", "WORKSPACE"), rows)


def _no_table(data: HubData) -> Table:
    """The picture has no rows: it is drawn by the page."""
    return Table([])


#: What each tab lists, in the order :data:`TABS` names them.
_TABLES: tuple[Callable[[HubData], Table], ...] = (_no_table, _session_table, _daemon_table)


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
        #: The table of the tab in front: its titles are drawn over the list, its widths line them up with the cells.
        self.table = _TABLES[GRAPH](data)
        super().__init__(
            self.table.items,
            title="Hub",
            subtitle=data.note or None,
            footer=self._footer(),
            on_cancel=on_close,
            visible_rows=None,
        )

    # -- what the reader sees ---------------------------------------------------------------------------
    def _footer(self) -> str:
        """Return the keys this tab takes."""
        leave = "esc deselect" if self.tab == GRAPH and self.selected is not None else "esc close"
        common = f"tab next tab {SEPARATOR} shift-tab back {SEPARATOR} r refresh {SEPARATOR} {leave}"
        if self.tab == GRAPH:
            return f"arrows move to the nearest node {SEPARATOR} {common}"
        if self.tab == DAEMONS:
            return f"enter start a stopped one {SEPARATOR} s stop {SEPARATOR} {common}"
        return common

    def layout(self, rect: Rect) -> None:
        """Lay the list one row lower than a plain list page does, to make room for the titles of its columns."""
        super().layout(rect)
        self.list.layout(Rect(rect.x + 2, rect.y + 4, max(0, rect.width - 4), max(0, rect.height - 5)))

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
        # When the page was read and how long it took, at the right end of the tab line and only where it fits.
        stamp = self.data.read
        if stamp and display_width(stamp) <= room - (x - self.rect.x):
            canvas.draw_text(self.rect.right - 2 - display_width(stamp), y, stamp, hint)
        if self.tab == GRAPH:
            self._draw_graph(canvas, hint, room)
        else:
            if self.subtitle is not None:
                notice = Style(foreground=theme.accent_bright, background=theme.surface_alt, bold=True)
                canvas.draw_text(self.rect.x + 2, self.rect.y + 2, self.subtitle, notice, max_width=room)
            self._draw_titles(canvas, theme)
            self.list.render(canvas)
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def _draw_titles(self, canvas: Canvas, theme: Theme) -> None:
        """Draw the title of each column over the list, lined up with the cells under it.

        The list puts its marker in two columns and the name after it, then every cell after the widest name; the
        titles follow that, and are left out where the list itself gives up on columns for want of room.
        """
        table, items = self.table, self.list.items
        if not table.titles or not items:
            return
        style = Style(foreground=theme.subtle, background=theme.surface_alt, bold=True)
        x, y = self.list.rect.x, self.rect.y + 3
        name = max(display_width(item.label) for item in items)
        marker, gap = self.list.MARKER_WIDTH, self.list.COLUMN_GAP
        canvas.draw_text(x + marker, y, truncate(table.titles[0], name + gap - 1), style, max_width=name + gap - 1)
        start = marker + name + gap
        room = self.list.rect.width - start
        if room <= 3:
            return
        cells = [
            title + " " * (width - display_width(title) + COLUMN_GAP)
            for title, width in zip(table.titles[1:], table.widths, strict=True)
        ]
        cells[-1] = cells[-1].rstrip()
        canvas.draw_text(x + start, y, truncate("".join(cells), room), style, max_width=room)

    def _picture_for(self, width: int, height: int) -> Picture:
        """Return the laid-out graph for this size, laid out again only when the data or the size changed."""
        key = (self.data.nodes, self.data.links, width, height)
        if key != self._picture_key:
            self._picture = hub_graph.layout(self.data.nodes, self.data.links, width, height)
            self._picture_key = key
            if self.selected is not None and all(node.key != self.selected for node in self._picture.nodes):
                self.selected = None
        return self._picture

    def _forget_picture(self) -> None:
        """Drop the picture and the selection when nothing is drawn, so no key moves a node that is not there.

        The footer is made again with them: it says ``esc deselect`` only while something is selected, and Escape
        closes the page when nothing is.
        """
        self._picture, self._picture_key, self.selected = Picture(), None, None
        self.footer = self._footer()

    def _draw_graph(self, canvas: Canvas, hint: Style, room: int) -> None:
        """Draw the summary, the note, the picture and the legend, or say why there is no picture."""
        theme = self.theme
        left = self.rect.x + 2
        top = self.rect.y + TOP_ROWS
        height = self.rect.bottom - BOTTOM_ROWS - top
        data = self.data
        if data.note:
            notice = Style(foreground=theme.accent_bright, background=theme.surface_alt, bold=True)
            canvas.draw_text(left, self.rect.y + 3, data.note, notice, max_width=room)
        picture = Picture()
        offset = (0, 0)
        if not data.nodes:
            said = "no session has talked to another yet" if data.graph_ok else "the message graph cannot be read"
        elif height < MIN_GRAPH_HEIGHT or room < MIN_GRAPH_WIDTH:
            said = "too small for the graph"
        else:
            said = ""
            # Routing costs more the bigger the area and stops improving past a point, so a big screen is routed in
            # a bounded rectangle and that is drawn in the middle of it.
            wide, high = min(room, MAX_ROUTED_WIDTH), min(height, MAX_ROUTED_HEIGHT)
            picture = self._picture_for(wide, high)
            offset = ((room - wide) // 2, (height - high) // 2)
        if not picture.nodes:
            self._forget_picture()
        if data.nodes:
            line = hub_graph.summary(data.nodes, data.links, picture, self.selected)
            canvas.draw_text(left, self.rect.y + 2, truncate(line, room), hint, max_width=room)
        if said:
            if height > 0:
                column = self.rect.x + max(2, (self.rect.width - display_width(said)) // 2)
                canvas.draw_text(column, top + height // 2, said, hint, max_width=room)
        else:
            hub_graph.paint(canvas, theme, left + offset[0], top + offset[1], picture, self.selected)
        if self.rect.height >= LEGEND_FROM and picture.nodes:
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
        self.table = _TABLES[tab](self.data)
        rows = self.table.items
        self.list.set_items(rows)
        self.list.selected = min(self.marks[tab], len(rows) - 1)
        self.footer = self._footer()
        self.request_layout()

    # -- the keys ---------------------------------------------------------------------------------------
    def capture_event(self, event, host) -> bool:
        """Take Tab and Shift-Tab (the only keys that change tab), the node selection and the daemon keys."""
        key = event_key(event)
        if key == "tab":
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab + 1) % len(TABS))
            return True
        if key == "backtab":
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab - 1) % len(TABS))
            return True
        if key == "r" and self.on_refresh is not None:
            self.note("refreshing\u2026")
            self.on_refresh()
            return True
        if self.tab == GRAPH and key in ("up", "down", "left", "right"):
            self._move(key)
            return True
        if self.tab == GRAPH and key == "escape" and self.selected is not None:
            self.selected = None
            self.footer = self._footer()
            self.request_layout()
            return True
        if self.tab == DAEMONS and key == "enter":
            self._chosen()
            return True
        if self.tab == DAEMONS and key == "s" and self.on_stop is not None:
            chosen = self._daemon()
            if chosen is None:
                self.note("no daemon under the mark")
            else:
                self.note("stopping\u2026")
                self.on_stop(chosen.session_id)
            return True
        return super().capture_event(event, host)

    def _move(self, key: str) -> None:
        """Select the node nearest in the direction of an arrow key; the first arrow selects the reader's own."""
        target = hub_graph.nearest(self._picture, self.selected, key)
        if target is not None:
            self.selected = target
            self.footer = self._footer()
            self.request_layout()

    def _daemon(self) -> Daemon | None:
        """Return the daemon under the mark, by the id the row carries: a refresh may have reordered the list."""
        items = self.list.items
        if not (0 <= self.list.selected < len(items)):
            return None
        chosen = items[self.list.selected].value
        return next((daemon for daemon in self.data.daemons if daemon.session_id == chosen), None)

    def _chosen(self) -> None:
        """Enter on the daemons tab starts the daemon under the mark when its process is gone.

        It says so on the page either way: that it is starting, or why nothing was started.
        """
        if self.on_start is None or self.tab != DAEMONS:
            return None
        chosen = self._daemon()
        if chosen is None:
            self.note("no daemon under the mark")
        elif chosen.status in GONE:
            self.note("starting\u2026")
            self.on_start(chosen.session_id)
        else:
            self.note(f"{chosen.label or chosen.session_id[:8]} is running; enter starts a stopped one")
        return None


class HubCommand(TuiPlugin):
    """``/hub``: the graph, the sessions and the daemons, and the two actions a daemon row takes: stop and start."""

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
            on_refresh=lambda: self._start(self._reload(page, client)),
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

    async def _reload(self, page: HubPage, client: object) -> None:
        """``r``: read everything again. The page said "refreshing" when the key was pressed; the new reading's own
        time and duration, at the top right, say it is done, and differ from the last one's if it was pressed twice."""
        await self._refresh(page, client)

    async def _stop(self, page: HubPage, client: object, session_id: str) -> None:
        """Stop one daemon, then show what that changed."""
        from zettcode.sdk.daemons import stop_daemon

        page.note("stopping\u2026")
        said = await stop_daemon(session_id, keep=True)
        await self._refresh(page, client)
        page.note(said)

    async def _resume(self, page: HubPage, client: object, session_id: str) -> None:
        """Start a daemon whose process is gone, resuming the session it had.

        It starts on the workspace and model its record names; a record with no workspace falls back to the reader's
        own, and one with no model to the first configured. One start per daemon at a time, until the page shows the
        daemon running: a second ``Enter`` while the first is starting or the page is being read again is told so,
        since two processes would share one record and one session lock. A running daemon is not started again.
        """
        from zettcode.sdk.daemons import spawn_daemon

        chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
        if chosen is None:
            return
        if chosen.status not in GONE:
            page.note(f"{chosen.label or session_id[:8]} is running")
            return
        if session_id in self._starting:
            page.note("already starting that one")
            return
        self._starting.add(session_id)
        page.note("starting\u2026")
        try:
            try:
                workspace = chosen.workspace or str(client.workspace)  # type: ignore[attr-defined]
                started = await spawn_daemon(workspace, model=chosen.model or None, resume=session_id)
            except Exception as error:  # noqa: BLE001 - the page says what happened, whatever it was
                note = str(error)
            else:
                note = f"started {started.session_id[:8]}"
            await self._refresh(page, client)
        finally:
            self._starting.discard(session_id)
        page.note(note)

    async def _read(self, client: object) -> HubData:
        """Read the three tabs: the broker's roster and graph, the stored sessions, and the daemons' records.

        One reading decides who is present: the graph's own roster, the cached peers and the daemons that are
        running all count, so a session is offered as offline only when none of them has it.
        """
        from zettcode.sdk.daemons import list_daemons

        began = last = time.perf_counter()
        steps: list[str] = []

        def lap(name: str) -> None:
            nonlocal last
            now = time.perf_counter()
            steps.append(f"{name} {(now - last) * 1000:.0f}")
            last = now

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
        lap("daemons")
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
        lap("sessions")
        graph_ok = True
        try:
            graph = await client.traffic_graph()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - without a broker the picture is empty, the lists still work
            graph, graph_ok = {}, False
            note = note or f"the message graph cannot be read: {error}"
        lap("graph")
        present = {peer.session_id for peer in peers} | {me}
        present |= {str(entry.get("session_id", "")) for entry in graph.get("sessions", ())}
        present |= {daemon.session_id for daemon in daemons if daemon.status not in GONE}
        offline = tuple(StoredSession(info.id, info.title or info.id[:8]) for info in listed if info.id not in present)
        # The picture is of this workspace: another project's dead daemons are on the Daemons tab, not in it, and a
        # session's own title wins over its daemon's name.
        try:
            here = Path(client.workspace).resolve()  # type: ignore[attr-defined]
        except (AttributeError, OSError, RuntimeError):  # a client with no workspace still has a roster to show
            here = Path.cwd()
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
        total = (time.perf_counter() - began) * 1000
        read = f"read {time.strftime('%H:%M:%S')} \u00b7 {total:.0f} ms ({', '.join(steps)})"
        return HubData(
            peers=peers,
            daemons=daemons,
            offline=offline,
            note=note,
            nodes=nodes,
            links=links,
            graph_ok=graph_ok,
            read=read,
        )


def _is_in(workspace: str, here: Path) -> bool:
    """Return whether a daemon's workspace is the reader's."""
    try:
        return bool(workspace) and Path(workspace).expanduser().resolve() == here
    except (OSError, RuntimeError):
        return False
