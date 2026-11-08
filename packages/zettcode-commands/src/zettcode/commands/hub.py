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
  only stored: a daemon is what can be started on them. Whatever has no process is ``offline`` — a daemon that was
  stopped keeps its record and stays listed until it is deleted, and a stored session has none. ``s`` stops the one
  under the mark and keeps its record; ``Enter`` starts an offline one, resuming its session.

``/`` searches the table in front (Sessions or Daemons): what is typed after it keeps the rows whose name, title or id
contain every word of it, ignoring case. ``Enter`` stops typing and keeps the filter (``s`` and ``r`` act again),
``Esc`` clears it and only then closes the page. Each tab has its own search.

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
from typing import TYPE_CHECKING, Any

from zettcode.commands import hub_graph
from zettcode.commands.hub_graph import Link, Node, Picture
from zettcode.plugin_api.commands import CommandContext, CommandHost, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import SEPARATOR, Canvas, ListItem, ListPage, PasteEvent, Rect, TextEvent, Theme, event_key
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
    """One daemon recorded on this machine, running or not, or a stored session no daemon has (status ``offline``).

    ``label`` is what the row is called; ``name`` and ``title`` are the two things it may be called after, kept apart
    because a search finds either. ``effort`` and ``permission`` are what the record says the daemon ran at, so that
    starting it again does not change them: a daemon that was denied a shell is not given one by pressing Enter.
    """

    session_id: str
    label: str
    status: str
    model: str = ""
    workspace: str = ""
    name: str = ""
    title: str = ""
    effort: str = ""
    permission: str = ""


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
    #: The reader's own session: the name the other sessions call it by and its title, either of which may be empty.
    #: The page writes them at the top left, cut to :data:`ME_NAME_WIDTH` and :data:`ME_TITLE_WIDTH` columns.
    me_name: str = ""
    me_title: str = ""
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
    """What a list tab shows: its rows, the title of each column, and how wide each column after the name is.

    ``finds`` is what each row can be found by, in the order of the rows (the name, the title and the id, lower-cased);
    a row without one, like the line that says older sessions were left out, is not a match for any search.
    """

    items: list[ListItem]
    titles: tuple[str, ...] = ()
    widths: tuple[int, ...] = ()
    finds: tuple[str, ...] = ()

    def filtered(self, query: str) -> Table:
        """Return the rows that contain every word of ``query``, ignoring case; the columns keep their widths.

        A blank query is every row. The widths stay those of the whole table, so the columns do not move as the
        reader types. A row with no ``find`` (the line that says older sessions were left out) matches no word, so
        a search leaves it out, deliberately: it describes the whole table and not the rows that are left.
        """
        words = query.lower().split()
        if not words:
            return self
        kept = [
            (item, find) for item, find in zip(self.items, self.finds, strict=True) if all(w in find for w in words)
        ]
        return Table([item for item, _ in kept], self.titles, self.widths, tuple(find for _, find in kept))


#: The space between two columns of a table.
COLUMN_GAP = 2

#: The most columns a table's TITLE cell takes, so a long title cannot push the model and workspace off a narrow page.
TABLE_TITLE_WIDTH = 32

#: The most columns the reader's own name and title take at the top left, so a long title never crowds the page.
ME_NAME_WIDTH = 20
ME_TITLE_WIDTH = 40

#: The steps of a reading, in the order :meth:`HubCommand._read` takes them. A new step is added here, which is a
#: decision to make where it can be seen: ``lap`` refuses a name that is not in it, and the letters below go with it.
#: ``build`` is the picture's title dictionary only; routing the lines needs the page's size, so it runs in the first
#: frame drawn after a reading (``_picture_for``) and is not a step of the reading.
STEPS = ("peers", "daemons", "sessions", "graph", "build")

#: The letters a narrow page writes the steps of a reading with:
#: ``p0 d3 s1 g19 b0`` is peers 0 ms, daemons 3, sessions 1, graph 19 and the build 0.
STEP_LETTERS = dict(zip(STEPS, ("p", "d", "s", "g", "b"), strict=True))


def _table(titles: tuple[str, ...], rows: Sequence[tuple[str, str, str, tuple[str, ...], str]]) -> Table:
    """Build a table whose first column is each row's name and whose second is its state.

    Args:
        titles: The title of every column, the name's first.
        rows: ``(value, name, state, cells, find)`` for each row: the cells are the columns after the state, and the
            state column is written as the state's dot and word, in the state's colour; ``find`` is what the row can be
            searched by (its name, title and id), and is kept lower-cased.
    """
    cells = [(f"{hub_graph.glyph(state)} {text}", *rest) for _, _, state, (text, *rest), _ in rows]
    widths = tuple(
        max([display_width(titles[index + 1])] + [display_width(row[index]) for row in cells])
        for index in range(len(titles) - 1)
    )
    items = []
    for (value, name, state, _, _), row in zip(rows, cells, strict=True):
        padded = [
            cell + " " * (width - display_width(cell) + COLUMN_GAP) for cell, width in zip(row, widths, strict=True)
        ]
        padded[-1] = row[-1]

        def parts(theme: Theme, state: str = state, padded: list[str] = padded) -> list[tuple[str, str | None]]:
            return [(padded[0], hub_graph.colours(theme)[state]), *((text, theme.muted) for text in padded[1:])]

        items.append(ListItem(value, name, "".join(padded), parts=parts))
    return Table(items, titles, widths, tuple(find.lower() for *_, find in rows))


def _session_table(data: HubData) -> Table:
    rows = [
        (
            peer.handle,
            peer.handle,
            hub_graph.state_of(peer.status, peer.kind),
            (
                hub_graph.state_of(peer.status, peer.kind),
                truncate(peer.title or "untitled", TABLE_TITLE_WIDTH),
                peer.workspace,
            ),
            f"{peer.handle} {peer.title} {peer.session_id}",
        )
        for peer in data.peers
    ]
    return _table(("NAME", "STATE", "TITLE", "WORKSPACE"), rows)


def _daemon_table(data: HubData) -> Table:
    rows = []
    for daemon in data.daemons:
        # No process is one word, whether it was a daemon that was stopped or a session that was only stored: the
        # reader sees the same thing and `Enter` does the same thing, which is what STARTABLE says.
        state = OFFLINE if daemon.status in STARTABLE else hub_graph.state_of(daemon.status, "")
        # The state word already says working or idle or offline; the daemon's own word follows only when it says more.
        said = state if daemon.status in (state, "dead") else f"{state} ({daemon.status})"
        rows.append(
            (
                daemon.session_id,
                daemon.label or daemon.session_id,
                state,
                (
                    said,
                    truncate(daemon.title or "untitled", TABLE_TITLE_WIDTH),
                    daemon.model or "no model",
                    daemon.workspace,
                ),
                f"{daemon.label} {daemon.name} {daemon.title} {daemon.session_id}",
            )
        )
    table = _table(("NAME", "STATE", "TITLE", "MODEL", "WORKSPACE"), rows)
    if data.offline_cut:
        # A row of words, not a session: it cannot be marked, so no key acts on it, and it has no `find`, so no search
        # keeps it. The two lists stay the same length.
        notice = ListItem(None, "\u2026", f"only the {OFFLINE_LIMIT} newest stored sessions are listed", disabled=True)
        table = Table([*table.items, notice], table.titles, table.widths, (*table.finds, ""))
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
        #: What was typed after ``/`` on each tab, and whether the reader is still typing it (on the tab in front).
        self.queries = [""] * len(TABS)
        self.searching = False
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
        #: How many rows the tab in front has before a search keeps some of them, for "3 of 59".
        self.total = 0
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
        """Return the keys this tab takes: for the graph, the arrows; for a table, what it does now (typing a search,
        a filter held, or neither)."""
        if self.tab == GRAPH:
            leave = "esc deselect" if self.selected is not None else "esc close"
            return (
                f"arrows move to the nearest node {SEPARATOR} tab next tab {SEPARATOR} shift-tab back {SEPARATOR} "
                f"r refresh {SEPARATOR} {leave}"
            )
        if self.searching:
            return f"type to search {SEPARATOR} enter keep the filter {SEPARATOR} esc clear it"
        filtered = bool(self.queries[self.tab])
        common = (
            f"tab next tab {SEPARATOR} shift-tab back {SEPARATOR} / search {SEPARATOR} r refresh {SEPARATOR} "
            f"{'esc clear the filter' if filtered else 'esc close'}"
        )
        if self.tab == DAEMONS:
            return f"enter start an offline one {SEPARATOR} s stop {SEPARATOR} {common}"
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
        who = self._who(room)
        if who:
            canvas.draw_text(x, self.rect.y, who, hint, max_width=room)
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
            self._draw_search_and_note(canvas, theme, room)
            self._draw_titles(canvas, theme)
            self.list.render(canvas)
            if self.queries[self.tab] and not self.list.items:
                canvas.draw_text(
                    self.rect.x + 4,
                    self.rect.y + 5,
                    truncate(f"nothing matches \u201c{self.queries[self.tab]}\u201d", max(0, room - 2)),
                    hint,
                )
        canvas.draw_text(self.rect.x + 2, self.rect.bottom - 1, self.footer, hint, max_width=room)

    def _draw_search_and_note(self, canvas: Canvas, theme: Theme, room: int) -> None:
        """Draw the one row under the tabs of a table: the search (what is typed, and how many rows it keeps) and the
        note of the last action after it, or the note alone when there is no search.

        The row has to hold what the reader is typing, so that comes first and is never what gets cut: a query too
        long for the row loses its head and keeps its tail and the cursor, then the count is kept, and the note gets
        what is left, with an ellipsis where it is cut.
        """
        query, x, y = self.queries[self.tab], self.rect.x + 2, self.rect.y + 2
        notice = Style(foreground=theme.accent_bright, background=theme.surface_alt, bold=True)
        quiet = Style(foreground=theme.muted, background=theme.surface_alt)
        used = 0
        if self.searching or query:
            kept = sum(1 for item in self.list.items if not item.disabled)
            count = f"  {kept} of {self.total}"
            keep_count = room - display_width(count) >= 8  # a row too narrow for both gives the query all of it
            typed = _tail(
                query + ("\u258f" if self.searching else ""), room - 2 - (display_width(count) if keep_count else 0)
            )
            prompt = f"/ {typed}"
            canvas.draw_text(x, y, prompt, notice, max_width=room)
            used = display_width(prompt)
            if keep_count:
                canvas.draw_text(x + used, y, count, quiet, max_width=room - used)
                used += display_width(count)
            used += 3  # air between the search and the note
        left = room - used
        if self.subtitle is not None and left >= 6:
            canvas.draw_text(x + used, y, truncate(self.subtitle, left), notice, max_width=left)

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
        letters of :data:`STEP_LETTERS` (``p0 d3 s1 g19 b0``); the same without the clock; the clock and the total;
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
                self.footer = self._footer()  # it says "esc deselect" only while something is selected
        return self._picture

    def _forget_picture(self) -> None:
        """Drop the picture and the selection when nothing is drawn, so no key moves a node that is not there.

        The footer is made again with them: it says ``esc deselect`` only while something is selected, and Escape
        closes the page when nothing is.
        """
        self._picture, self._picture_key, self.selected = Picture(), None, None
        self.footer = self._footer()

    def _who(self, room: int) -> str:
        """Return the reader's own name and title for the top left: ``name \u00b7 title``, each cut to its own width
        (the name 20 columns, the title 40) with an ellipsis, and the whole to the room there is. Whichever is empty
        is left out, and an empty string means there is nothing to say."""
        parts = [
            truncate(text, width)
            for text, width in ((self.data.me_name, ME_NAME_WIDTH), (self.data.me_title, ME_TITLE_WIDTH))
            if text
        ]
        return truncate(" \u00b7 ".join(parts), room) if parts else ""

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
        """Put one tab in front, with the mark it had and the search it holds.

        Leaving a tab ends the typing of its search; the filter itself is kept for when the reader comes back.
        """
        if tab != self.tab:
            self.searching = False
        self.tab = tab
        whole = _TABLES[tab](self.data)
        self.total = sum(1 for item in whole.items if not item.disabled)
        self.table = whole.filtered(self.queries[tab])
        rows = self.table.items
        self.list.set_items(rows)
        # The mark the tab had, kept off a row nothing can act on: the one that says older sessions were left out can
        # take its index when a refresh leaves fewer rows, so the nearest row before it that can be marked is used,
        # and none is marked when that row is all there is.
        wanted = min(self.marks[tab], len(rows) - 1)
        while wanted > 0 and rows[wanted].disabled:
            wanted -= 1
        self.list.selected = wanted if rows and not rows[wanted].disabled else -1
        self.footer = self._footer()
        self._repaint()

    # -- the keys ---------------------------------------------------------------------------------------
    def capture_event(self, event, host) -> bool:
        """Take Tab and Shift-Tab (the only keys that change tab), the search, the node selection and the daemon keys."""
        key = event_key(event)
        if self.searching and self.tab != GRAPH and key not in ("tab", "backtab"):
            # What is typed is the query, whatever it spells: `s` and `r` are letters here, not stop and refresh.
            return self._type(event, key) or super().capture_event(event, host)
        if key == "tab":
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab + 1) % len(TABS))
            return True
        if key == "backtab":
            self.marks[self.tab] = max(0, self.list.selected)
            self._show((self.tab - 1) % len(TABS))
            return True
        if key == "/" and self.tab != GRAPH:
            self.searching = True
            self._show(self.tab)
            return True
        if key == "escape" and self.tab != GRAPH and self.queries[self.tab]:
            self._set_query("")  # a filter is cleared before the page is closed
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
            elif chosen.status == OFFLINE:
                # A stored session no daemon ever had: there is nothing to stop, and the SDK's sentence about a daemon
                # that does not exist is not one for this page.
                self.note("no daemon to stop on this one; enter starts one")
            else:
                self.note("stopping\u2026")
                self.on_stop(chosen.session_id)
            return True
        return super().capture_event(event, host)

    def _type(self, event: object, key: str | None) -> bool:
        """Take one key while the search is being typed; return whether it was taken (``False`` leaves it to the list,
        which still moves the mark with the arrow keys and pages).
        """
        query = self.queries[self.tab]
        if key == "escape":
            self.searching = False
            self._set_query("")
            return True
        if key == "enter":
            self.searching = False
            self._show(self.tab)
            return True
        if key == "backspace":
            self._set_query(query[:-1])
            return True
        if isinstance(event, PasteEvent):
            # A pasted id is the likeliest thing to type here. A paste carries newlines and a text event does not, and
            # the search splits on any whitespace anyway, so the query takes the paste as one line of words.
            self._set_query(query + " ".join(event.text.split()))
            return True
        if isinstance(event, TextEvent):
            self._set_query(query + event.text)
            return True
        if key == "space":
            self._set_query(query + " ")
            return True
        if key is not None and len(key) == 1:  # a printable key that arrived as a key and not as text
            self._set_query(query + key)
            return True
        return False

    def _set_query(self, text: str) -> None:
        """Make ``text`` this tab's search, and show the rows that match it from the first."""
        self.queries[self.tab] = text
        self.marks[self.tab] = 0
        self._show(self.tab)

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
            self.note(f"{chosen.label or chosen.session_id[:8]} is running; enter starts an offline one")
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
    #: Daemons that were working when ``s`` was pressed and have been told so: the next ``s`` stops them anyway.
    _forced: set[str]

    def __init__(self) -> None:
        """Start with no page and no action running."""
        self._page = None
        self._actions = set()
        self._starting = set()
        self._forced = set()

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
            on_refresh=lambda: self._start(self._refresh(page, client), page),
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
        """Read everything again, and show it.

        ``r`` runs this too: the page said "refreshing" when the key was pressed, and the new reading's own time and
        duration, at the top right, say it is done (and differ from the last one's if it was pressed twice). It also
        forgets which working daemons were warned, so a second ``s`` that is meant to force a stop follows the first.
        """
        self._forced.clear()
        page.set_data(await self._read(client))

    async def _stop(self, page: HubPage, client: object, session_id: str) -> None:
        """Stop one daemon, keeping its record, then show what that changed.

        A daemon in the middle of a turn is not stopped by the first ``s``: stopping it throws that turn away. The page
        says so and remembers it; the next ``s`` on it stops it anyway. (The SDK asks for ``force`` in a flag the page
        cannot pass, and its sentence names that flag, so the page words it itself.)
        """
        from zettcode.sdk.daemons import stop_daemon
        from zettcode.sdk.errors import ConfigurationError

        page.note("stopping\u2026")
        try:
            said = await stop_daemon(session_id, keep=True, force=session_id in self._forced)
        except ConfigurationError:
            self._forced.add(session_id)
            chosen = next((daemon for daemon in page.data.daemons if daemon.session_id == session_id), None)
            label = chosen.label if chosen is not None else session_id[:8]
            page.note(f"{label} is working on a turn: press s again to stop it anyway and throw that turn away")
            return
        self._forced.discard(session_id)
        await self._refresh(page, client)
        page.note(said)

    async def _resume(self, page: HubPage, client: object, session_id: str) -> None:
        """Start a daemon on an offline session, resuming it: one whose daemon was stopped, or one that is only stored.

        A daemon that was stopped starts on the workspace, model, reasoning level and shell level its record names, and
        under the label it had: pressing Enter must not give a shell to a daemon that was denied one, or take it from
        one that had it. A stored session has no record, so it starts in the reader's own workspace (the store is read
        for that workspace) on the first configured model, with the SDK's defaults. A record with no workspace falls
        back to the reader's own, and one with no model to the first configured. A session another process has open is
        said so before anything is started: a daemon cannot write to it, and would only say so from its log after a start.
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
                if await _open_elsewhere(client, session_id, workspace):
                    raise RuntimeError(
                        "that session is open in another ZettCode process, so a daemon cannot write to it"
                    )
                # What the record says, and nothing it does not: an offline session has none of these, and the SDK's
                # own defaults are the right ones for it.
                kept = {
                    key: value
                    for key, value in (
                        ("effort", chosen.effort),
                        ("name", chosen.name),
                        ("permission", chosen.permission),
                    )
                    if value
                }
                started = await spawn_daemon(workspace, model=chosen.model or None, resume=session_id, **kept)
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
            if name not in STEPS:
                raise ValueError(f"{name!r} is not a step of a reading: add it to STEPS, with its letter")
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
                name=info.name or "",
                title=info.title or "",
                effort=info.effort or "",
                permission=info.permission or "",
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
        # The reader's own name and title, for the top left: the roster knows both once the session is registered; the
        # client's handle and the stored title stand in before that.
        mine: dict[str, Any] = (
            next((e for e in graph.get("sessions", ()) if str(e.get("session_id", "")) == me), {}) if me else {}
        )
        try:
            handle = str(client.handle)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a client with no handle still has a page to show
            handle = ""
        me_name = str(mine.get("handle", "")) or handle
        me_title = str(mine.get("title", "")) or next(
            (info.title or "" for info in listed if info.id == me), ""
        )  # The picture is of this workspace: another project's dead daemons are on the Daemons tab, not in it, and a
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
            graph, me=me, titles=titles, offline=[daemon.session_id for daemon in ours if daemon.status in GONE]
        )
        if not graph_ok:
            # Nothing to say about who talks to whom, so the picture is empty and says why, not a lone stopped box.
            nodes, links = (), ()
        # Offline: the stored sessions of this workspace that nothing accounts for — not the reader's own, not in the
        # roster, and not the session of any daemon record (which has its row already, running or stopped). They follow
        # the daemons, newest first, and are what a daemon can be started on.
        # Who is in the roster is the live graph's word, and the Sessions tab, the picture and the offline rows all take
        # it from there: a peer that has just disconnected lingers in the client's cache, and one tab would call a
        # session idle while another called it offline. The cached peers stand in only when the graph could not be read.
        if graph_ok:
            peers = tuple(
                Peer(
                    handle=str(entry.get("handle", "")),
                    title=str(entry.get("title", "")),
                    status=str(entry.get("status", "")),
                    workspace=str(entry.get("workspace", "")),
                    kind=str(entry.get("kind", "")),
                    session_id=str(entry.get("session_id", "")),
                )
                for entry in graph.get("sessions", ())
                if str(entry.get("session_id", "")) != me
            )
        roster = {peer.session_id for peer in peers}
        accounted = {me, *roster, *(daemon.session_id for daemon in daemons)}
        offline = tuple(
            Daemon(
                session_id=info.id,
                label=info.title or info.id[:8],
                status=OFFLINE,
                workspace=str(here),
                title=info.title or "",
            )
            for info in listed
            if info.id not in accounted
        )
        lap("build")
        return HubData(
            peers=peers,
            daemons=(*daemons, *offline),
            note=note,
            nodes=nodes,
            links=links,
            graph_ok=graph_ok,
            me_name=me_name,
            me_title=me_title,
            offline_cut=cut,
            began=clock,
            took=round((time.perf_counter() - began) * 1000),
            steps=tuple(steps),
        )


async def _open_elsewhere(client: object, session_id: str, workspace: str) -> bool:
    """Return whether another process has the session open, asked of the SDK on a thread (it takes a file lock for an
    instant to find out). A client that cannot be asked is not a reason to refuse a start: a daemon that cannot write
    to its session refuses by itself, and says why."""
    try:
        return bool(
            await asyncio.to_thread(client.sessions.open_elsewhere, session_id, workspace=workspace)  # type: ignore[attr-defined]
        )
    except Exception:  # noqa: BLE001 - see above
        return False


def _tail(text: str, width: int) -> str:
    """Return the last ``width`` columns of ``text``, with an ellipsis in front where the head was cut.

    Columns, not characters: a wide glyph is two. What is typed ends at the cursor, so the end is what has to stay.
    """
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    kept: list[str] = []
    used = 1  # the ellipsis
    for character in reversed(text):
        step = display_width(character)
        if used + step > width:
            break
        kept.append(character)
        used += step
    return "\u2026" + "".join(reversed(kept))


def _is_in(workspace: str, here: Path) -> bool:
    """Return whether a daemon's workspace is the reader's."""
    try:
        return bool(workspace) and Path(workspace).expanduser().resolve() == here
    except (OSError, RuntimeError):
        return False
