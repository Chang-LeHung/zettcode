"""The bottom-panel list of recent sessions opened by ``/resume``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from zettcode.engine.agent.sessions import UNTITLED_SESSION
from zettcode.engine.storage import SessionInfo, SessionStats
from zettcode.tui import ELLIPSIS, SEPARATOR, ListItem, ListPage, Rect, Theme
from zettcode.tui.render import blend, display_width
from zettcode.tui.render.text import truncate
from zettcode.tui.widgets.list import Part

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


def _share(stats: SessionStats) -> str:
    """Return the cached share of a session's input as a percent to two places, or a dash before any input."""
    share = stats.cache_share
    return NONE if share is None else f"{share * 100:.2f}%"


class SessionsPage(ListPage):
    """Recent sessions as a selectable :class:`ListPage`, each with how big it is and what it cost.

    Shape::

        Sessions
                                             Updated  Entries   Input  Output  Cached  ID
          \u25b8 1. Fix the parser crash          3m ago       41   12.3K    1.2K     87%  1a2b3c4d
            2. New session                    17h ago        3    3.9K       2     0%  9f8e7d6c   <- still unnamed
        enter open \u00b7 esc back

    Entries are the message records the session's file holds; input and output are the tokens its model replies
    were charged for, the input counting what came from the provider's cache, and the cached share is that part
    of the input. A fork is not charged for the replies it copied, so it shows only what it spent after the fork
    (see :mod:`zettcode.engine.storage.ledger`). The heading over the figures is the page's subtitle, aligned
    with the column the list itself lays the figures in.

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
        stats: Mapping[str, SessionStats] | None = None,
        on_select: Callable[[str], None],
        on_cancel: Callable[[], None],
        now: datetime | None = None,
    ) -> None:
        """Make the rows for a wide panel; they are made again when the page learns its width."""
        self._sessions = tuple(sessions)
        self._stats = None if stats is None else dict(stats)
        self._now = now
        self._built_for = DEFAULT_WIDTH
        self._head: tuple[int, Sequence[_Column]] = (0, ())
        items, heading = self.arrange(DEFAULT_WIDTH)
        super().__init__(
            items,
            title="Sessions",
            subtitle=heading,
            subtitle_parts=self._heading_parts,
            footer=f"enter open {SEPARATOR} esc back",
            on_select=lambda item: on_select(str(item.value)),
            on_cancel=on_cancel,
        )

    def columns(self) -> list[_Column]:
        """Return the columns of figures, most wanted first."""
        sessions = self._sessions
        ages = tuple(format_ago(session.updated_at, now=self._now) for session in sessions)
        ids = tuple(session.session_id[:8] for session in sessions)
        age = _Column("Updated", ages, True)
        short = _Column("ID", ids, False, lambda theme: theme.muted)
        stats = self._stats
        if stats is None:
            return [age, short]
        rows = [stats.get(session.session_id) for session in sessions]

        def cells(pick: Callable[[SessionStats], str]) -> tuple[str, ...]:
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

    def arrange(self, width: int) -> tuple[list[ListItem], str]:
        """Return the rows and the heading over their figures for a list ``width`` columns wide."""
        sessions = self._sessions
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
                session.session_id,
                title,
                (" " * GAP).join(figures.cell(index) for figures in shown),
                parts=self._figures(shown, index),
            )
            for index, (session, title) in enumerate(zip(sessions, titles, strict=True))
        ]
        heading = " " * (MARKER + column + GAP) + (" " * GAP).join(figures.head() for figures in shown)
        self._head = (MARKER + column + GAP, shown)
        return items, heading

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
        """Make the rows again when the width has changed since they were made, keeping the highlighted one."""
        width = max(0, rect.width - 4)
        if width != self._built_for:
            self._built_for = width
            items, heading = self.arrange(width)
            selected = max(0, self.list.selected)
            self.list.set_items(items)
            self.list.select(selected, notify=False)
            self.subtitle = heading
        super().layout(rect)
