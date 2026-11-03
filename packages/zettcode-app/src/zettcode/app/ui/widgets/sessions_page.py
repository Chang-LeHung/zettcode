"""The bottom-panel list of recent sessions opened by ``/resume``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from zettcode.sdk.types import SessionInfo, SessionStatsInfo
from zettcode.tui import (
    ELLIPSIS,
    SEPARATOR,
    AnyEvent,
    Canvas,
    Host,
    KeyEvent,
    ListItem,
    ListPage,
    PasteEvent,
    Rect,
    Style,
    TextEvent,
    Theme,
    Widget,
)
from zettcode.tui.render import blend, display_width
from zettcode.tui.render.text import truncate
from zettcode.tui.widgets.list import Part, draw_parts
from zettcode.wording import UNTITLED_SESSION

from .usage_charts import compact

#: Columns the marker takes at the left of a row, and the gap between the title and the figures, as the list lays them.
MARKER = 2
GAP = 2

#: The shortest a title is cut to before a column of figures is given up for it.
MIN_TITLE = 18

#: What a figure reads as when the session has none: a subagent's, or one the totals could not be read for.
NONE = "\u2014"

#: How much of its column's colour a heading takes, over the muted text colour.
HEADING_SHARE = 0.6

#: How much of the cached column's colour a share of nothing keeps; a share of everything keeps all of it.
CACHE_FLOOR = 0.4

#: The width the panel is built for before it has been laid out, so a page painted without a layout is complete.
DEFAULT_WIDTH = 120

#: The corners and rules of the search box, the rounded shape a form's fields are drawn in.
BOX_TOP_LEFT, BOX_TOP_RIGHT = "\u256d", "\u256e"
BOX_BOTTOM_LEFT, BOX_BOTTOM_RIGHT = "\u2570", "\u256f"
BOX_HORIZONTAL, BOX_VERTICAL = "\u2500", "\u2502"

#: The label on the box's top border, and the three rows the box spends: that border, the query, its foot.
SEARCH_LABEL = "Search"
BOX_ROWS = 3

#: Rows the page spends above the first session: the top margin, the title, the box, and the heading.
HEADER_ROWS = 2 + BOX_ROWS + 1

#: What the search box says before anything is typed into it.
SEARCH_HINT = "search by title or id"

#: Where typing lands in the box: "\u2588", a full block — the solid cursor vim leaves on the cell at the end of
#: a line, rather than a thin bar that is easy to miss in a terminal.
CARET = "\u2588"

#: The keys line while nothing is typed; once a search narrows the list, Escape has a job before it can close.
KEYS = f"type to search {SEPARATOR} enter open {SEPARATOR} esc back"
SEARCHING_KEYS = f"enter open {SEPARATOR} esc clear"


def format_ago(moment: datetime, *, now: datetime | None = None) -> str:
    """Return how long ago ``moment`` was, in the coarsest unit that fits.

    Args:
        moment: When the session last changed; stored times are UTC.
        now: Current time, injected by tests; defaults to the real clock.
    """
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def _plain(theme: Theme) -> str:
    """Return the colour of a column with nothing to say about itself: the readable secondary text."""
    return theme.subtle


def _muted(theme: Theme) -> Style:
    """Return the style of a quiet line on the panel's own surface: the box's label, and what it says while empty."""
    return Style(foreground=theme.muted, background=theme.surface_alt)


class _Column(NamedTuple):
    """One column of figures: its heading, its cells, which side they line up on, and what colour they are.

    ``hue`` is the colour the column is known by, the one the same figure has on the ``/usage`` page; ``strength``
    is how much of it each cell takes, from ``0`` (the plain secondary colour) to ``1`` (all of it), or ``None``
    when every cell takes all of it. A cell with no figure is always the muted colour.
    """

    heading: str
    cells: tuple[str, ...]
    right: bool
    hue: Callable[[Theme], str] = _plain
    strength: tuple[float, ...] | None = None

    def colour(self, theme: Theme, index: int) -> str:
        """Return the colour of one cell."""
        if self.cells[index] == NONE:
            return theme.muted
        amount = 1.0 if self.strength is None else self.strength[index]
        return blend(theme.subtle, self.hue(theme), amount)

    def head_colour(self, theme: Theme) -> str:
        """Return the colour of the heading: the column's own, turned down so the figures stay the loudest."""
        return blend(theme.muted, self.hue(theme), HEADING_SHARE)

    @property
    def width(self) -> int:
        """Return the columns it takes: the widest of its heading and its cells."""
        return max(display_width(self.heading), *(display_width(cell) for cell in self.cells), 0)

    def cell(self, index: int) -> str:
        """Return one cell padded to the column's width."""
        text = self.cells[index]
        pad = " " * (self.width - display_width(text))
        return pad + text if self.right else text + pad

    def head(self) -> str:
        """Return the heading padded to the column's width."""
        pad = " " * (self.width - display_width(self.heading))
        return pad + self.heading if self.right else self.heading + pad


def _share(stats: SessionStatsInfo) -> str:
    """Return the cached share of a session's input as a percent to two places, or a dash before any input."""
    share = stats.cache_share
    return NONE if share is None else f"{share * 100:.2f}%"


class SessionsPage(ListPage):
    """Recent sessions as a selectable :class:`ListPage`, each with how big it is and what it cost.

    Shape::

        Sessions
        \u256d\u2500 Search \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e
        \u2502 search by title or id                  \u2502
        \u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f
                                             Updated  Entries   Input  Output  Cached  ID
          \u25b8 1. Fix the parser crash          3m ago       41   12.3K    1.2K     87%  1a2b3c4d
            2. New session                    17h ago        3    3.9K       2     0%  9f8e7d6c   <- still unnamed
        type to search \u00b7 enter open \u00b7 esc back

    Entries are the message records the session's file holds; input and output are the tokens its model replies
    were charged for, the input counting what came from the provider's cache, and the cached share is that part
    of the input. A fork is not charged for the replies it copied, so it shows only what it spent after the fork
    (see :mod:`zettcode.engine.storage.ledger`). The heading over the figures is the page's subtitle, aligned
    with the column the list itself lays the figures in.

    Typing narrows the list as it goes: every character goes into the search box, Backspace takes one out, and a
    session stays only while the query appears in its title or its id, case folded, so a short id from this very
    panel finds the session again. The order is the store's, newest first, filtered rather than sorted; an empty
    box is the whole list in that order. The box and the list are one ring for the arrow keys: Up on the first row
    puts the caret in the box, Up in the box wraps to the last row, and Down in the box goes back to the first, so
    the box is reachable without a mouse. Typing fills the box from either stop, but the caret is drawn only in the
    box's own stop — the list keeps the keyboard until the reader asks for the box. Enter opens the highlighted row
    from either stop. Escape gives the list back to the page before it gives the page up: with something in the box
    it clears it, and a second press closes the panel.

    The rows are made for the width the page is given: when the panel is narrower than the title and every
    column need, the columns on the right are given up one at a time, last first, until the longest title has
    :data:`MIN_TITLE` columns (or all of it, when it is shorter), and only then is the title cut with an
    ellipsis. The ``Updated`` column is never given up. A session without a title reads as ``New session``, the
    same name the status line shows; the short id is what tells two of them apart. Rows commit the session id,
    which the shell turns into ``use_session``.

    Args:
        sessions: Metadata rows to show, newest first, as returned by the store.
        stats: Each session's totals by session id. A session without an entry shows dashes. ``None`` shows no
            figures at all, only the age and the id: what a store that could not be read gets.
        on_select: Receives the chosen session id.
        on_cancel: Called when the user presses Escape.
        now: Current time for the age column; tests inject it, everything else reads the clock so a long-open
            panel keeps counting.
    """

    def __init__(
        self,
        sessions: Sequence[SessionInfo],
        *,
        stats: Mapping[str, SessionStatsInfo] | None = None,
        on_select: Callable[[str], None],
        on_cancel: Callable[[], None],
        now: datetime | None = None,
    ) -> None:
        """Make the rows for a wide panel; they are made again when the page learns its width."""
        self._sessions = tuple(sessions)
        self._visible = self._sessions
        self._query = ""
        self._stats = None if stats is None else dict(stats)
        self._now = now
        self._built_for = DEFAULT_WIDTH
        self._head: tuple[int, Sequence[_Column]] = (0, ())
        items = self.arrange(DEFAULT_WIDTH)
        super().__init__(
            items,
            title="Sessions",
            footer=KEYS,
            on_select=lambda item: on_select(str(item.value)),
            on_cancel=on_cancel,
        )

    @property
    def query(self) -> str:
        """Return what is in the search box."""
        return self._query

    @property
    def heading(self) -> str:
        """Return the heading over the figures as one plain row: the columns' names at the widths they are drawn."""
        indent, shown = self._head
        return " " * indent + (" " * GAP).join(figures.head() for figures in shown)

    def matching(self, query: str) -> tuple[SessionInfo, ...]:
        """Return the sessions a query keeps, in the store's order: newest first, never sorted again.

        A query is read case folded, trimmed, and matched anywhere in the name a row shows or in the session id,
        so ``fix`` finds a title and ``1a2b`` finds the id printed on the row. A blank query keeps everything,
        which is the list the panel opened with.
        """
        wanted = query.strip().casefold()
        if not wanted:
            return self._sessions
        return tuple(
            session
            for session in self._sessions
            if wanted in (session.title or UNTITLED_SESSION).casefold() or wanted in session.id.casefold()
        )

    def search(self, text: str) -> None:
        """Add what was typed to the search box and make the rows again."""
        self._set_query(self._query + text)

    def _set_query(self, query: str) -> None:
        """Put a query in the box, narrow the list to it, and reset the highlight to the first match.

        A query of nothing but spaces is no query at all: the list shows everything and Escape closes the panel
        as it does from an empty box, rather than clearing an invisible character first. Spaces inside the box are
        kept as typed — ``fix parser`` has to be typable — and trimmed when the rows are matched.
        """
        if not query.strip():
            query = ""
        if query == self._query:
            return
        self._query = query
        self._visible = self.matching(query)
        items = self.arrange(self._built_for)
        self.list.set_items(items)
        self.footer = SEARCHING_KEYS if query else KEYS
        self.invalidate()

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take typing as a search before the list can see it, and make the box and the list one up/down cycle.

        Every character is a search term here, whichever of the two stops has the keyboard. The box is the stop
        above the list: Up on the first row puts the cursor in the box, Up in the box wraps to the last row, and
        Down in the box goes back to the first — so the search is reachable with the arrows and left the same way,
        without a click. Escape still clears the box before it gives the panel up.
        """
        if isinstance(event, TextEvent) and not (event.alt or event.control or event.meta):
            self.search(event.text)
            return True
        if isinstance(event, PasteEvent) and not (event.alt or event.control or event.meta):
            self.search(" ".join(event.text.split()))
            return True
        if isinstance(event, KeyEvent) and not (event.alt or event.control or event.meta):
            if event.key == "backspace":
                self._set_query(self._query[:-1])
                return True
            if event.key == "escape" and self._query:
                self._set_query("")
                return True
            if self.focused:
                if event.key == "up":
                    self._leave_box(host, len(self.list.items) - 1)
                    return True
                if event.key == "down":
                    self._leave_box(host, 0)
                    return True
                if event.key == "enter":
                    # With no match there is no row to open, but the key still belongs to the panel: it must not
                    # fall through to the shell from a box that said it was taking Enter.
                    self.list.activate()
                    return True
            elif self.list.focused and self.list.items:
                if event.key == "up" and self.list.selected == 0:
                    self._enter_box(host)
                    return True
                if event.key == "down" and self.list.selected == len(self.list.items) - 1:
                    self._enter_box(host)
                    return True
        return super().capture_event(event, host)

    def _enter_box(self, host: Host | None) -> None:
        """Put the keyboard in the search box, keeping the row the list had highlighted."""
        if host is None:
            return
        host.focus(self)
        self.invalidate()

    def _leave_box(self, host: Host | None, index: int) -> None:
        """Hand the keyboard back to the list on one row, unless there is no host or no row to go to."""
        if host is None or not self.list.items:
            return
        self.list.select(index, notify=False)
        host.focus(self.list)
        self.invalidate()

    def columns(self) -> list[_Column]:
        """Return the columns of figures, most wanted first."""
        sessions = self._visible
        ages = tuple(format_ago(session.updated_at, now=self._now) for session in sessions)
        ids = tuple(session.id[:8] for session in sessions)
        age = _Column("Updated", ages, True)
        short = _Column("ID", ids, False, lambda theme: theme.muted)
        stats = self._stats
        if stats is None:
            return [age, short]
        rows = [stats.get(session.id) for session in sessions]

        def cells(pick: Callable[[SessionStatsInfo], str]) -> tuple[str, ...]:
            return tuple(NONE if row is None else pick(row) for row in rows)

        shares = tuple(0.0 if row is None else row.cache_share or 0.0 for row in rows)
        # A cache that did little is dimmer than one that did most of the work, so the column can be read down.
        weights = tuple(CACHE_FLOOR + (1 - CACHE_FLOOR) * share for share in shares)

        return [
            age,
            _Column("Entries", cells(lambda row: compact(row.entries)), True),
            _Column("Input", cells(lambda row: compact(row.input_tokens)), True, lambda theme: theme.accent),
            _Column("Output", cells(lambda row: compact(row.output_tokens)), True, lambda theme: theme.warning),
            _Column("Cached", cells(_share), True, lambda theme: theme.tools.subagent, weights),
            short,
        ]

    def arrange(self, width: int) -> list[ListItem]:
        """Return the rows for a list ``width`` columns wide and remember the heading that goes over them."""
        sessions = self._visible
        digits = len(str(len(sessions))) if sessions else 1
        titles = [
            f"{index:>{digits}}. {session.title or UNTITLED_SESSION}" for index, session in enumerate(sessions, 1)
        ]
        widest = max((display_width(title) for title in titles), default=0)
        columns = self.columns()
        # Give up the columns on the right while the title would be cut below what is readable.
        keep = len(columns)
        while keep > 1 and self._room(width, columns[:keep]) < min(MIN_TITLE, widest):
            keep -= 1
        shown = columns[:keep]
        room = max(4, self._room(width, shown))
        titles = [
            title if display_width(title) <= room else truncate(title, room, ellipsis=ELLIPSIS) for title in titles
        ]
        column = max((display_width(title) for title in titles), default=0)
        items = [
            ListItem(
                session.id,
                title,
                (" " * GAP).join(figures.cell(index) for figures in shown),
                parts=self._figures(shown, index),
            )
            for index, (session, title) in enumerate(zip(sessions, titles, strict=True))
        ]
        self._head = (MARKER + column + GAP, shown)
        return items

    @staticmethod
    def _figures(shown: Sequence[_Column], index: int) -> Callable[[Theme], list[Part]]:
        """Return a row's figures as coloured pieces, each column in its own hue and the gaps between them bare."""

        def parts(theme: Theme) -> list[Part]:
            pieces: list[Part] = []
            for position, figures in enumerate(shown):
                if position:
                    pieces.append((" " * GAP, None))
                pieces.append((figures.cell(index), figures.colour(theme, index)))
            return pieces

        return parts

    def _heading_parts(self, theme: Theme) -> list[Part]:
        """Return the heading over the figures with each heading word in the hue of the column under it."""
        indent, shown = self._head
        pieces: list[Part] = [(" " * indent, None)]
        for position, figures in enumerate(shown):
            if position:
                pieces.append((" " * GAP, None))
            pieces.append((figures.head(), figures.head_colour(theme)))
        return pieces

    @staticmethod
    def _room(width: int, columns: Sequence[_Column]) -> int:
        """Return the columns a title may take beside these columns of figures in a list ``width`` wide."""
        figures = sum(figure.width for figure in columns) + GAP * max(0, len(columns) - 1)
        return width - MARKER - GAP - figures

    def layout(self, rect: Rect) -> None:
        """Make the rows again when the width has changed since they were made, keeping the highlighted one.

        The list starts under the title, the boxed search field and the heading, which no longer fits a
        :class:`ListPage`'s three-row frame; the rows below are bounded so the keys keep the bottom row.
        """
        width = max(0, rect.width - 4)
        if width != self._built_for:
            self._built_for = width
            items = self.arrange(width)
            selected = max(0, self.list.selected)
            self.list.set_items(items)
            self.list.select(selected, notify=False)
        Widget.layout(self, rect)
        rows = max(0, rect.height - HEADER_ROWS - 2)
        self.list.layout(Rect(rect.x + 2, rect.y + HEADER_ROWS, max(0, rect.width - 4), rows))

    def render(self, canvas: Canvas) -> None:
        """Fill the page, then draw what fits of the title, box, heading, rows, and keys.

        The footer keeps the bottom row. On a page too short for the rest, the title, the box, the heading and the
        line that says nothing matched are drawn only while their own rows are above it, so none is painted over
        the keys.
        """
        if self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface_alt))
        room = max(0, self.rect.width - 4)
        x = self.rect.x + 2
        heading = Style(foreground=theme.text, background=theme.surface_alt, bold=True)
        hint = Style(foreground=theme.muted, background=theme.surface_alt)
        bottom = self.rect.bottom - 1
        if self.rect.y + 1 < bottom:
            canvas.draw_text(x, self.rect.y + 1, self.title, heading, max_width=room)
        if self.rect.y + 2 + BOX_ROWS - 1 < bottom:
            self._paint_search(canvas, x, self.rect.y + 2, room)
        heading_y = self.rect.y + 2 + BOX_ROWS
        if heading_y < bottom:
            draw_parts(canvas, x, heading_y, self._heading_parts(theme), hint, max_width=room)
        if self.list.items:
            self.list.render(canvas)
        elif self._query and heading_y + 1 < bottom:
            canvas.draw_text(x, heading_y + 1, self._no_match(), hint, max_width=room)
        canvas.draw_text(x, bottom, self.footer, hint, max_width=room)

    def _paint_search(self, canvas: Canvas, x: int, y: int, room: int) -> None:
        """Draw the rounded box, its label, and the query — or what the box is for while it is empty.

        The border and the label take the bright accent while the box is the keyboard stop, which is also when
        the caret is drawn; the box beside a focused list is quiet, since typing still reaches it either way.
        """
        if room < 2:
            return  # narrower than its own two uprights: there is no box to draw
        theme = self.theme
        active = self.focused
        frame = Style(foreground=theme.accent_bright if active else theme.subtle, background=theme.surface_alt)
        rule = BOX_HORIZONTAL * max(0, room - 2)
        canvas.draw_text(x, y, f"{BOX_TOP_LEFT}{rule}{BOX_TOP_RIGHT}", frame, max_width=room)
        canvas.draw_text(x, y + 1, BOX_VERTICAL, frame)
        canvas.draw_text(x + room - 1, y + 1, BOX_VERTICAL, frame)
        canvas.draw_text(x, y + 2, f"{BOX_BOTTOM_LEFT}{rule}{BOX_BOTTOM_RIGHT}", frame, max_width=room)
        if room > 8:
            label = Style(
                foreground=theme.accent_bright if active else theme.muted,
                background=theme.surface_alt,
                bold=active,
            )
            canvas.draw_text(x + 2, y, f" {SEARCH_LABEL} ", label, max_width=room - 4)
        # A cell of padding inside each upright, then the query itself: no prompt mark, the box already says
        # that this is where typing goes.
        field_x = x + 2
        field_room = max(0, room - 4)
        if field_room <= 0:
            return  # a box too narrow to hold a query keeps its border and says nothing inside it
        caret = Style(foreground=theme.text, background=theme.surface_alt)
        if self._query:
            shown = truncate(self._query, max(0, field_room - (1 if active else 0)), ellipsis=ELLIPSIS)
            canvas.draw_text(
                field_x, y + 1, shown, Style(foreground=theme.text, background=theme.surface_alt), max_width=field_room
            )
            if active:
                canvas.draw_text(field_x + display_width(shown), y + 1, CARET, caret, max_width=1)
        elif active:
            canvas.draw_text(field_x, y + 1, CARET + " ", caret, max_width=field_room)
            hint = truncate(SEARCH_HINT, max(0, field_room - 2), ellipsis=ELLIPSIS)
            canvas.draw_text(field_x + 2, y + 1, hint, _muted(theme), max_width=max(0, field_room - 2))
        else:
            hint = truncate(SEARCH_HINT, field_room, ellipsis=ELLIPSIS)
            canvas.draw_text(field_x, y + 1, hint, _muted(theme), max_width=field_room)

    def _no_match(self) -> str:
        """Return the line a search with no matches leaves in place of the rows."""
        return f"No session matches \u201c{self._query.strip()}\u201d"
