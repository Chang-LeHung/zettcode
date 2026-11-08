"""``/hub``: who is here, what the daemons are doing, and who talked to whom, on one full-screen page with three tabs.

The gateway's page shows this in a browser; this is the same picture where the work happens. What it reads is the
broker's roster and message graph through the SDK, the sessions stored for this workspace, and the daemons' records
through :mod:`zettcode.sdk.daemons`, so nothing new is listened to and nothing is stored here.

* **Graph**: the busiest sessions as boxes, coloured by state, and a line between two that exchanged messages, with
  the number beside the end it is drawn from (:mod:`~zettcode.commands.hub_graph` says how). Every box has a place, so
  an arrow key selects the nearest box that way, which keeps its lines and dims the rest; ``Esc`` deselects.
* **Sessions**: the sessions that are running, as the broker's roster has them, and nothing else. Only looked at here:
  it is a daemon that can be started.
* **Daemons**: every daemon recorded on this machine, running or not, then the sessions of this workspace that are
  only stored (``offline``): a daemon is what can be started on them. A daemon whose process is gone stays listed
  (``stopped``) until it is deleted. ``s`` stops the one under the mark and keeps its record; ``Enter`` starts a stopped
  or offline one, resuming its session.

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

#: The status of a row that is no daemon at all yet: a session stored in this workspace that nothing is running. It is
#: on the Daemons tab because a daemon is what can be started on it, and ``Enter`` does that, resuming the session.
OFFLINE = "offline"

#: What ``Enter`` can start: a daemon whose process is gone, and a stored session with no daemon.
STARTABLE = (*GONE, OFFLINE)

#: How many of the newest stored sessions are looked at. The store reads every session's file to answer however many
#: are asked for, so the cost is the same at any limit; the limit only bounds how long the table is.
OFFLINE_LIMIT = 200

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
    note: str = ""
    nodes: tuple[Node, ...] = ()
    links: tuple[Link, ...] = ()
    #: Whether the message graph could be read; an empty picture says which of the two it is.
    graph_ok: bool = True
    #: Whether stored sessions older than the :data:`OFFLINE_LIMIT` newest were left out, which the table says.
    offline_cut: bool = False
    #: When the reading began (``12:34:56``), how long it took in milliseconds, and each step's share of that: elapsed
    #: time on the event loop, so a step is also slow when the loop was busy with something else meanwhile. The page
    #: composes the fullest line of it that fits (:meth:`HubPage._stamp`): the steps need about 85 columns, by their
    #: initials, and about 110 by name, so a narrow window shows only the total and widening it shows where it went.
    began: str = ""
    took: int = 0
    steps: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class Table:
    """What a list tab shows: its rows, the title of each column, and how wide each column after the name is."""

    items: list[ListItem]
    titles: tuple[str, ...] = ()
    widths: tuple[int, ...] = ()


#: The space between two columns of a table.
COLUMN_GAP = 2

#: The letters a narrow page writes the steps of a reading with, in the order :meth:`HubCommand._read` takes them:
#: ``p0 d3 s1 g19 pic0`` is peers 0 ms, daemons 3, sessions 1, graph 19 and the picture 0.
STEP_LETTERS = {"peers": "p", "daemons": "d", "sessions": "s", "graph": "g", "picture": "pic"}


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
    return _table(("NAME", "STATE", "TITLE", "WORKSPACE"), rows)


def _daemon_table(data: HubData) -> Table:
    rows = []
    for daemon in data.daemons:
        if daemon.status == OFFLINE:
            state = OFFLINE
        else:
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
    table = _table(("NAME", "STATE", "MODEL", "WORKSPACE"), rows)
    if data.offline_cut:
        # A row of words, not a session: it cannot be marked, so no key acts on it.
        table.items.append(
            ListItem(None, "\u2026", f"only the {OFFLINE_LIMIT} newest stored sessions are listed", disabled=True)
        )
    return table


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
        #: Set when the page is closed: a task that finishes after that writes on a page nobody sees, and wakes nothing.
        self.closed = False
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
            return f"enter start a stopped or offline one {SEPARATOR} s stop {SEPARATOR} {common}"
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
        stamp = self._stamp(room - (x - self.rect.x))
        if stamp:
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

    def _stamp(self, room: int) -> str:
        """Return the fullest account of the last reading that fits in ``room`` columns, or nothing.

        The page is the only side that knows the room, so the data carries the parts and the page picks, longest
        first: the clock, the total and each step by name; without the clock; with the steps shortened to the
        letters of :data:`STEP_LETTERS` (``p0 d3 s1 g19 pic0``); the same without the clock; the clock and the total;
        the total alone. The steps are the point of it, so they come before the clock in the narrower forms. Two
        columns are kept clear of the last tab.
        """
        data = self.data
        if not data.took and not data.began:
            return ""
        total = f"read {data.took} ms"
        # A reading with no clock has no form that names one.
        clock = f"read {data.began} \u00b7 {data.took} ms" if data.began else total
        forms = [clock, total]
        if data.steps:
            named = ", ".join(f"{name} {ms}" for name, ms in data.steps)
            short = " ".join(f"{STEP_LETTERS.get(name, name[:3])}{ms}" for name, ms in data.steps)
            forms[:0] = [f"{clock} ({named} ms)", f"{total} ({named} ms)", f"{clock} ({short})", f"{total} ({short})"]
        for text in forms:
            if display_width(text) + 2 <= room:
                return text
        return ""

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
        """Take a fresh reading, and keep the mark where it was on the tab in front.

        It is called from a task, not from an input event, so it asks for a frame itself (:meth:`_repaint`).
        """
        self.marks[self.tab] = max(0, self.list.selected)
        self.data = data
        self.subtitle = self.data.note or None
        self._show(self.tab)
        self._repaint()

    def note(self, text: str) -> None:
        """Say one line under the tabs — what a key just did, or why it could not.

        A task writes notes too (``started …``, an error), so it asks for a frame itself (:meth:`_repaint`).
        """
        self.data = dataclasses.replace(self.data, note=text)
        self.subtitle = text
        self._repaint()

    def _repaint(self) -> None:
        """Wake the loop for a frame: a change made by a task is not an input event, and without this the old screen
        stays until the next key (``refreshing…`` stayed up for as long as the reader did not press anything).

        Only the app's own calls are heard: a widget's ``invalidate`` and ``request_layout`` set flags nothing in the
        framework reads. ``invalidate`` is enough here because the page's geometry is constants; a note that took a
        row of its own would need ``self.app.request_layout()``. A page that was never mounted has no app to ask, and
        a closed one has nothing on screen to bring up to date.
        """
        if self.app is not None and not self.closed:
            self.app.invalidate()

    def _show(self, tab: int) -> None:
        """Put one tab in front, with the mark it had."""
        self.tab = tab
        self.table = _TABLES[tab](self.data)
        rows = self.table.items
        self.list.set_items(rows)
        # The mark the tab had, kept off a row nothing can act on: the one that says older sessions were left out can
        # take its index when a refresh leaves fewer rows, so the nearest row before it that can be marked is used.
        if not rows:
            self.list.selected = -1
        else:
            wanted = min(self.marks[tab], len(rows) - 1)
            while wanted > 0 and rows[wanted].disabled:
                wanted -= 1
            self.list.selected = wanted
        self.footer = self._footer()
        self._repaint()

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
            self._repaint()
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
            self._repaint()

    def _daemon(self) -> Daemon | None:
        """Return the daemon under the mark, by the id the row carries: a refresh may have reordered the list."""
        items = self.list.items
        if not (0 <= self.list.selected < len(items)):
            return None
        chosen = items[self.list.selected].value
        return next((daemon for daemon in self.data.daemons if daemon.session_id == chosen), None)

    def _chosen(self) -> None:
        """Enter on the daemons tab starts what is under the mark when nothing is running it: a daemon whose process
        is gone, or an offline session.

        It says so on the page either way: that it is starting, or why nothing was started.
        """
        if self.on_start is None or self.tab != DAEMONS:
            return None
        chosen = self._daemon()
        if chosen is None:
            self.note("no daemon under the mark")
        elif chosen.status in STARTABLE:
            self.note("starting\u2026")
            self.on_start(chosen.session_id)
        else:
            self.note(f"{chosen.label or chosen.session_id[:8]} is running; enter starts a stopped or offline one")
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
            on_refresh=lambda: self._start(self._reload(page, client), page),
            on_stop=lambda session_id: self._start(self._stop(page, client, session_id), page),
            on_start=lambda session_id: self._start(self._resume(page, client, session_id), page),
        )
        self._page = page
        return CommandResult(widget=page)

    def _closer(self, host: CommandHost) -> Callable[[], None]:
        """Return what closing the page runs: mark it closed, forget it here, then let the shell close it.

        A late failure then has nothing to write on, and a task that finishes after the page was closed neither wakes
        the app nor lands on the page that was opened in its place.
        """

        def close() -> None:
            if self._page is not None:
                self._page.closed = True
            self._page = None
            host.close_page()

        return close

    def _start(self, task: Awaitable[None], page: HubPage) -> None:
        """Run one action on the loop the page was opened on, and keep it so a failure is not lost.

        The action belongs to ``page``: a failure is written there, and only while it is the page in front.
        """
        running = asyncio.ensure_future(task)
        self._actions.add(running)
        running.add_done_callback(lambda finished: self._done(finished, page))

    def _done(self, finished: asyncio.Future[None], page: HubPage) -> None:
        """Forget an action, and say what it failed with, on the page it was started from."""
        self._actions.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None and page is self._page:
            page.note(str(error))

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
        """Start a daemon on a session nothing is running, resuming it: a daemon whose process is gone, or a session
        that is only stored.

        A stopped daemon starts on the workspace and model its record names; an offline session has no record, so it
        starts in the reader's own workspace (the store is read for that workspace) on the first configured model.
        A record with no workspace falls back to the reader's own, and one with no model to the first configured.
        One start per row at a time, until the page shows it running: a second ``Enter`` while the first is starting
        or the page is being read again is told so, since two processes would share one record and one session lock.
        A running daemon is not started again.
        """
        from zettcode.sdk.daemons import spawn_daemon

        chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
        if chosen is None:
            return
        if chosen.status not in STARTABLE:
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
                text = str(error)
                # The store has no such session: a daemon that never held a conversation leaves none (an empty one is
                # removed when it closes), and a record whose workspace no longer holds it reads the same. The words
                # are the engine's, reached through the daemon's log, so this is a match on a message, not a type.
                note = (
                    "nothing to resume: its session is not stored in that workspace"
                    if "Unknown session" in text
                    else text
                )
            else:
                note = f"started {started.session_id[:8]}"
            await self._refresh(page, client)
        finally:
            self._starting.discard(session_id)
        page.note(note)

    async def _read(self, client: object) -> HubData:
        """Read the three tabs: the broker's roster and graph, and the daemons' records, running or not.

        The stored sessions of this workspace are read only for their titles, to name a session the graph has a line
        to that is no longer in the roster; the Sessions tab lists what is running and nothing else.
        """
        from zettcode.sdk.daemons import list_daemons

        clock = time.strftime("%H:%M:%S")
        began = last = time.perf_counter()
        steps: list[tuple[str, int]] = []

        def lap(name: str) -> None:
            nonlocal last
            now = time.perf_counter()
            steps.append((name, round((now - last) * 1000)))
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
        lap("peers")
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
            # One more than is shown, so the table can say when older sessions were left out.
            listed = await client.sessions.list(limit=OFFLINE_LIMIT + 1)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a store that cannot be read costs only the names of sessions that are gone
            listed = ()
        cut = len(listed) > OFFLINE_LIMIT
        listed = listed[:OFFLINE_LIMIT]
        lap("sessions")
        graph_ok = True
        try:
            graph = await client.traffic_graph()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - without a broker the picture is empty, the lists still work
            graph, graph_ok = {}, False
            note = note or f"the message graph cannot be read: {error}"
        lap("graph")
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
        # Offline: the stored sessions of this workspace that nothing accounts for — not the reader's own, not in the
        # roster, and not the session of any daemon record (which has its row already, running or stopped). They follow
        # the daemons, newest first, and are what a daemon can be started on. Who is in the roster is the live graph's
        # word; the client's cached peers stand in only when the graph could not be read, because a peer that has just
        # disconnected lingers in that cache and would hide its session's row until the broker says it left.
        roster = (
            {str(entry.get("session_id", "")) for entry in graph.get("sessions", ())}
            if graph_ok
            else {peer.session_id for peer in peers}
        )
        accounted = {me, *roster, *(daemon.session_id for daemon in daemons)}
        offline = tuple(
            Daemon(session_id=info.id, label=info.title or info.id[:8], status=OFFLINE, workspace=str(here))
            for info in listed
            if info.id not in accounted
        )
        lap("picture")
        return HubData(
            peers=peers,
            daemons=(*daemons, *offline),
            note=note,
            nodes=nodes,
            links=links,
            graph_ok=graph_ok,
            offline_cut=cut,
            began=clock,
            took=round((time.perf_counter() - began) * 1000),
            steps=tuple(steps),
        )


def _is_in(workspace: str, here: Path) -> bool:
    """Return whether a daemon's workspace is the reader's."""
    try:
        return bool(workspace) and Path(workspace).expanduser().resolve() == here
    except (OSError, RuntimeError):
        return False
