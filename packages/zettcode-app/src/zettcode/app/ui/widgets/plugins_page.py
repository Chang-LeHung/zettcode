"""The page ``/plugins`` opens: every plugin there is, and a switch for each one that can have one.

Which rows have a switch is not this page's decision: the engine's catalog works it out (a plugin the program
requires has none; the others do, unless a line of the configuration holds them), so the editor's panel and this one
cannot disagree. What a switch writes is a promise about
the *next* start — the file is read once, when a process starts — and this one keeps what it already loaded.

The page draws the rows it can switch first and the ones nothing here can move — a plugin the configuration file
holds, or one the program cannot run without — after them, so the list a reader can act on is the top of the list.
Every row carries its number, and typing narrows the list to the plugins whose name, distribution or description holds
what was typed, so a reader who knows roughly what a plugin adds finds it without scrolling: the number, the setting
and the switch beside it are the same as they were.

Nothing here imports the engine: a row is the few facts the page draws, and the command that opens it fills them in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic

from zettcode.plugin_api.panels import pressed
from zettcode.plugin_api.switch import SWITCH_WIDTH, Rail, draw_switch
from zettcode.tui import (
    ARROW_DOWN,
    ARROW_UP,
    SEPARATOR,
    AnyEvent,
    Canvas,
    Host,
    KeyEvent,
    MouseAction,
    MouseEvent,
    PasteEvent,
    TextEvent,
    Widget,
)
from zettcode.tui.render import Style, blend, display_width, truncate

from .search_field import BOX_ROWS, draw_search

#: Rows the page spends on something other than the list: the top margin, the title, the search box, and the two lines
#: under the list (what the marked plugin does, and the keys).
CHROME = 2 + BOX_ROWS + 2

#: The first row of the list, counted from the top of the page: under the title and the search box.
LIST_TOP = 2 + BOX_ROWS

#: What a row without a switch says in the switch column, when the configuration file holds the switch.
OFF_IN_CONFIG = "fixed"

#: Columns the plugin's name takes, the switch, and the word beside it. The name column fits the longest one the
#: program ships (``project-instructions``) with room to breathe before the switch.
NAME_WIDTH = 24
WORD_WIDTH = 8

#: What the empty search box says a query is matched against.
SEARCH_HINT = "search by name or description"

#: Columns between the plugin's number and the name it belongs to.
NUMBER_GAP = 1

#: Columns the setting (a compiled-in plugin's key) or the distribution (an installed one's) takes, so that the
#: description beside it starts in the same place on every row. It fits the longest the program ships
#: (``harness.todowrite``), and a longer one is cut rather than moving the column.
SETTING_WIDTH = 20

#: Columns between the setting column and the description.
COLUMN_GAP = 2

#: The least columns a description is worth drawing in; narrower and the line under the list says it alone. A page
#: with no room for the setting *and* a description keeps the setting, which is what this page has always shown.
MIN_DESCRIPTION = 16

#: Columns kept free at the right of the list, where the marks saying it scrolls go.
EDGE = 2


@dataclass(frozen=True, slots=True)
class PluginRow:
    """One plugin as the page draws it.

    Attributes:
        name: What the plugin calls itself.
        origin: The entry-point name it is published under, and the name a switch is written with.
        required: The program cannot run without it, so its row has no switch.
        enabled: Whether the next start does its work.
        failure: Why it could not load here, or ``""`` when it did.
        setting: The configuration key that decides the plugin, such as ``"skills.enabled"``; empty for one that
            ``[plugins] disable`` holds.
        switchable: Whether there is a switch to draw; the catalog decides it, so the editor's panel agrees.
        why: Why there is none, when there is none.
        note: What else the row has to say — a plugin that lost its name to one loaded before it, for instance.
        description: What the plugin adds, in one line: its own, or the summary its distribution declares when this
            process never loaded it. Drawn beside the setting when the page is wide enough for both columns.
    """

    name: str
    origin: str
    required: bool = False
    enabled: bool = True
    failure: str = ""
    setting: str = ""
    switchable: bool = True
    why: str = ""
    note: str = ""
    description: str = ""


class PluginsPage(Widget):
    """Choose which plugins the next start does the work of.

    Shape::

        Plugins                                                      4 of 6 on

          ╭─ Search ────────────────────────────────────────────────────────────╮
          │ search by name or description                                        │
          ╰──────────────────────────────────────────────────────────────────────╯
          ▸ 1. skills       ━━━━●  on     skills.enabled    The skills a workspace declares, as @ references
            2. mcp          ━━━━●  on     mcp.enabled       MCP servers
            3. todos        ●────  off    harness.todowrite The todo_write tool and the plan it keeps
            4. monitor      ━━━━●  on     zettcode-monitor  Every model call, exported as HTML
            5. acme         ●────  off    zettcode-acme     Search results from the acme index
            6. coding       failed                          could not load: no plugin provides the model
            7. held         fixed                          zettcode-held

          skills (skills.enabled) loads at the next start
          type to search · ↑ ↓ plugin · ← → switch · enter apply · esc cancel

    The rows a reader can switch come first, in the order the catalog gave them, and the ones nothing here can move —
    a plugin the configuration file holds, and one the program cannot run without — are after them, so the part of
    the list a reader can act on is the part at the top. Every row keeps the number it has in that order, which a
    search does not renumber: a match says where the plugin sits in the whole list.

    Up and Down move the marker, round from the last row to the first and back; Left and Right move the switch of the
    marked plugin, and a click on it does the same. Enter hands every change to the caller, which writes them down and
    closes the page. Escape clears the search box first; a second press writes nothing and closes the page.

    Typing narrows the list as it goes: every character goes into the search box, Backspace takes one out, and a
    plugin stays only while the query appears, case folded, in the name it calls itself, the distribution it comes
    from, or the one line saying what it adds. A search filters the rows the page already ordered, so the numbers keep
    their places and an empty box is the whole list again.

    After the switch a row says where it writes — the plugin's setting, or its distribution —
    and then, where the page is wide enough for both, what the plugin adds in one line. The two columns are a page
    narrower than about ninety columns too much for, and there the setting keeps the line to itself, as it always
    had; the line under the list still says what the marked plugin does.

    Every row has a switch but the ones a reader cannot move, and those say why on the line under the list: a
    plugin the program requires, one whose switch is a line in the configuration file, and a group the configuration
    turned off as a whole. A plugin that failed keeps its switch, because `[plugins] disable` is exactly what would
    leave it out.

    Args:
        rows: The plugins a list shows, in the order the catalog gave them; the page puts the fixed ones last.
        on_apply: Receives every changed plugin's origin and the state to write when Enter is pressed.
        on_cancel: Called when the reader backs out.
    """

    HINT = (
        f"type to search {SEPARATOR} {ARROW_UP} {ARROW_DOWN} plugin {SEPARATOR} \u2190 \u2192 switch "
        f"{SEPARATOR} enter apply {SEPARATOR} esc cancel"
    )

    #: The keys line while a search narrows the list: Escape has the box to clear before it can close the page.
    SEARCHING = (
        f"{ARROW_UP} {ARROW_DOWN} plugin {SEPARATOR} \u2190 \u2192 switch {SEPARATOR} enter apply {SEPARATOR} esc clear"
    )

    def __init__(
        self,
        rows: Sequence[PluginRow],
        *,
        on_apply: Callable[[dict[str, bool]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with every switch where the file has it, and the marker on the first row the page draws."""
        super().__init__()
        # Stable, so the rows a reader can switch keep the catalog's order and the fixed ones keep theirs after them.
        self.rows: tuple[PluginRow, ...] = tuple(sorted(rows, key=lambda row: not row.switchable))
        #: Columns the widest number takes, so the names line up and the switch column moves with the count.
        self.digits = max(1, len(str(len(self.rows))))
        self.start = {row.origin: row.enabled for row in self.rows if row.switchable}
        self.switches = {row.origin: Rail(("off", "on"), int(row.enabled)) for row in self.rows if row.switchable}
        self.on_apply = on_apply
        self.on_cancel = on_cancel
        #: The plugin the marker is on, as an index into :attr:`rows`.
        self.mark = 0
        #: What is in the search box; an empty box is the whole list.
        self._query = ""
        #: The first visible row of the list.
        self.top = 0
        #: Why the last press did nothing, on the line under the list; cleared by the next move.
        self.note: str | None = None
        self._token = f"plugins-panel:{id(self)}"
        #: The rows the list shows, as positions in :attr:`rows`: every one until a query narrows them.
        self._lines: list[int] = list(range(len(self.rows)))

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    def switchable(self, row: PluginRow) -> bool:
        """Return whether this plugin has a switch here: the catalog works it out, so every front end agrees."""
        return row.switchable

    @property
    def shown(self) -> dict[str, bool]:
        """Return every switchable plugin's origin and the state its switch is heading for."""
        return {name: bool(rail.selected) for name, rail in self.switches.items()}

    @property
    def changes(self) -> dict[str, bool]:
        """Return the switches that are anywhere but where `[plugins] disable` has them."""
        return {name: state for name, state in self.shown.items() if state != self.start[name]}

    @property
    def moving(self) -> bool:
        """Return whether a switch is still on its way."""
        return any(rail.moving for rail in self.switches.values())

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    @property
    def query(self) -> str:
        """Return what is in the search box."""
        return self._query

    def matching(self, query: str) -> list[int]:
        """Return the positions of the rows a query keeps, in the order the page draws them.

        A query is trimmed, case folded, and matched anywhere in the name the plugin calls itself, the entry point
        it is published under (the second column), or the one line saying what it adds. A blank query keeps every
        row, which is the list the page opened with.
        """
        wanted = query.strip().casefold()
        if not wanted:
            return list(range(len(self.rows)))
        return [
            index
            for index, row in enumerate(self.rows)
            if any(wanted in field.casefold() for field in (row.name, row.origin, row.description))
        ]

    def search(self, text: str) -> None:
        """Add what was typed to the search box and narrow the list to it."""
        self._set_query(self._query + text)

    def _set_query(self, query: str) -> None:
        """Put a query in the box, narrow the list to it, and keep the marker on a row the query leaves."""
        if not query.strip():
            query = ""
        if query == self._query:
            return
        self._query = query
        self._lines = self.matching(query)
        self.note = None
        if self.mark not in self._lines and self._lines:
            self.mark = self._lines[0]
        self.top = 0

    def set(self, origin: str, on: bool) -> None:
        """Send one plugin's switch to on or off, and say on the line below why when it cannot move."""
        marked = self.rows[self.mark] if self.rows else None
        row = (
            marked
            if marked is not None and marked.origin == origin
            else next((row for row in self.rows if row.origin == origin), None)
        )
        if row is None:
            return
        if not self.switchable(row):
            self.mark = self.rows.index(row)
            self.note = self._why_fixed(row)
            return
        self.note = None
        reduced = self.app is not None and self.app.reduced_motion
        if self.switches[origin].choose(int(on), self._now(), instant=reduced) and self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the frame loop, so a page put away mid-slide stops costing frames."""
        for rail in self.switches.values():
            rail.moving = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_tick(self) -> bool:
        """Hand the frame loop back once every switch has arrived; say whether the picture is still changing."""
        now = self._now()
        landed = False
        for rail in self.switches.values():
            landed |= rail.arrive(now)
        if not self.moving and self.app is not None:
            self.app.scheduler.animate(self._token, active=False)
        return self.moving or landed

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take typing into the search box, and Escape to clear it before the focused widget can hear it."""
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
        if pressed(event) == "escape":
            self.on_cancel()
            return True
        return False

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Move with Up and Down, flip with Left and Right, and apply with Enter.

        The space bar is not the switch here: every printable character, the space included, is a search term, which
        is what makes a description with spaces in it findable.
        """
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        if not self.rows:
            return False
        key = pressed(event)
        if key == "enter":
            self.on_apply(self.changes)
            return True
        if not self._lines:
            # Nothing matches, so there is no row to move to or switch; Enter above still writes what was already
            # switched, and Escape in the box is what takes the query back.
            return False
        name = self.rows[self.mark].origin
        match key:
            case "up" | "backtab":
                self._move(self._where() - 1)
            case "down" | "tab":
                self._move(self._where() + 1)
            case "pageup":
                self._move(self._where() - max(1, self._view() - 1))
            case "pagedown":
                self._move(self._where() + max(1, self._view() - 1))
            case "home":
                self._move(0)
            case "end":
                self._move(len(self._lines) - 1)
            case "left":
                self.set(name, False)
            case "right":
                self.set(name, True)
            case _:
                return False
        return True

    def _where(self) -> int:
        """Return the marked plugin's position among the rows the search leaves, or the first when it has none."""
        return self._lines.index(self.mark) if self.mark in self._lines else 0

    def _move(self, position: int) -> None:
        """Put the marker on a visible row, round the ends, and take back what the last press said."""
        self.note = None
        if self._lines:
            self.mark = self._lines[position % len(self._lines)]

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Mark the row under a click, and flip its switch when the click is on the switch or its word."""
        if event.action is MouseAction.SCROLL_UP:
            self._move(self._where() - 1)
            return True
        if event.action is MouseAction.SCROLL_DOWN:
            self._move(self._where() + 1)
            return True
        if event.action is not MouseAction.DOWN:
            return False
        offset = event.y - (self.rect.y + LIST_TOP)
        index = self.top + offset
        if not 0 <= offset < self._view() or index >= len(self._lines):
            return False
        at = self._lines[index]
        row = self.rows[at]
        start = self._switch_column()
        if start <= event.x < start + SWITCH_WIDTH + 1 + WORD_WIDTH:
            self.mark = at
            rail = self.switches.get(row.origin)
            self.set(row.origin, not (rail.selected if rail is not None else False))
        else:
            self.note = None
            self.mark = at
        return True

    def _view(self) -> int:
        """Return how many rows of the list the page has room for."""
        return max(1, self.rect.height - CHROME)

    def _switch_column(self) -> int:
        """Return the column the first switch cell is in, after the marker, the number and the name."""
        return self.rect.x + 4 + self.digits + NUMBER_GAP + NAME_WIDTH

    def _reveal(self) -> None:
        """Scroll the list the least that shows the marked plugin."""
        if self.mark not in self._lines:
            return
        view = self._view()
        row = self._lines.index(self.mark)
        if row < self.top:
            self.top = row
        if row >= self.top + view:
            self.top = row - view + 1
        self.top = max(0, min(self.top, max(0, len(self._lines) - view)))

    def render(self, canvas: Canvas) -> None:
        """Fill the page, then draw the title, the list, what the marked plugin does, and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        bold = Style(foreground=theme.text, background=surface, bold=True)
        canvas.draw_text(x, self.rect.y + 1, "Plugins", bold, max_width=room)
        on = sum(1 for state in self.shown.values() if state)
        total = len(self.shown)
        changes = len(self.changes)
        suffix = " (not applied)" if changes else ""
        gap = room - display_width("Plugins") - 2
        candidates = (
            [
                f"{on} of {total} on{suffix}",
                f"{on} of {total} on",
                f"{on}/{total}",
            ]
            if total
            else ["nothing here can be switched", "no switch"]
        )
        state = next((text for text in candidates if display_width(text) <= gap), "")
        if state:
            canvas.draw_text(
                self.rect.right - 2 - display_width(state),
                self.rect.y + 1,
                state,
                Style(foreground=theme.accent if changes else theme.muted, background=surface, bold=bool(changes)),
            )
        draw_search(
            canvas,
            theme,
            x,
            self.rect.y + 2,
            room,
            self._query,
            hint=SEARCH_HINT,
            active=self.focused,
        )
        self._reveal()
        self._draw_list(canvas)
        if not self.rows:
            canvas.draw_text(x, self.rect.y + LIST_TOP, "No plugin is loaded.", muted, max_width=room)
        elif not self._lines:
            said = truncate(f"No plugin matches \u201c{self._query.strip()}\u201d", room)
            canvas.draw_text(x, self.rect.y + LIST_TOP, said, muted, max_width=room)
        else:
            row = self.rows[self.mark]
            head = f"{row.name}:"
            said = f"{head} {self.note or self._description(row)}"
            canvas.draw_text(x, self.rect.bottom - 2, truncate(said, room), muted, max_width=room)
            canvas.draw_text(x, self.rect.bottom - 2, head, bold, max_width=min(room, display_width(head)))
        keys = self.SEARCHING if self._query else self.HINT
        canvas.draw_text(x, self.rect.bottom - 1, truncate(keys, room), muted, max_width=room)

    def _description(self, row: PluginRow) -> str:
        """Return what the marked plugin does at the next start, or why it is not the reader's to switch."""
        if row.note:
            return row.note
        if row.failure:
            return f"could not load: {row.failure}"
        if not row.switchable:
            return row.why
        rail = self.switches[row.origin]
        state = "loads at the next start" if rail.selected else "is left out of the next start"
        where = f" ({row.setting})" if row.setting else ""
        return f"{row.origin}{where} {state}"

    def _why_fixed(self, row: PluginRow) -> str:
        """Return why the switch of one row cannot move, for the line under the list."""
        if row.note:
            return row.note
        return "it could not load, so there is no switch to move" if row.failure else row.why

    def _draw_list(self, canvas: Canvas) -> None:
        """Draw the visible rows: each plugin with its switch."""
        theme = self.theme
        surface = theme.surface_alt
        x = self.rect.x + 2
        right = self.rect.right - 2
        view = self._view()
        groove = blend(theme.muted, surface, 0.55)
        now = self._now()
        for offset in range(view):
            index = self.top + offset
            if index >= len(self._lines):
                break
            y = self.rect.y + LIST_TOP + offset
            at = self._lines[index]
            row = self.rows[at]
            rail = self.switches.get(row.origin) if row.switchable else None
            on = rail.position(now) if rail is not None else float(row.enabled)
            marked = at == self.mark
            if marked:
                canvas.draw_text(x, y, "\u25b8", Style(foreground=theme.accent, background=surface, bold=True))
            lit = theme.text if marked or on >= 0.5 else blend(theme.muted, surface, 0.25)
            # The number is the plugin's place in the whole list, not in what the query leaves: a search narrows the
            # rows but does not renumber them, so the number a reader saw before typing still names the same plugin.
            canvas.draw_text(
                x + 2,
                y,
                f"{at + 1:>{self.digits}}.",
                Style(foreground=theme.muted, background=surface, bold=marked),
                max_width=self.digits + 1,
            )
            canvas.draw_text(
                x + 2 + self.digits + NUMBER_GAP + 1,
                y,
                truncate(row.name, NAME_WIDTH),
                Style(foreground=lit, background=surface, bold=marked),
                max_width=NAME_WIDTH,
            )
            switch = self._switch_column()
            word_at = switch + SWITCH_WIDTH + 1
            if rail is None:
                if row.note:
                    text, colour = "name taken", theme.muted
                elif row.failure:
                    text, colour = "failed", theme.error
                else:
                    text, colour = OFF_IN_CONFIG, theme.warning
                canvas.draw_text(
                    switch,
                    y,
                    truncate(text, SWITCH_WIDTH + 1 + WORD_WIDTH),
                    Style(foreground=colour, background=surface),
                )
            else:
                draw_switch(canvas, theme, y, switch, on, groove)
                canvas.draw_text(
                    word_at,
                    y,
                    "on" if rail.selected else "off",
                    Style(
                        foreground=theme.accent if rail.selected else blend(theme.muted, surface, 0.25),
                        background=surface,
                    ),
                )
            start = word_at + WORD_WIDTH + 1
            room = right - EDGE - start
            if room >= SETTING_WIDTH + COLUMN_GAP + MIN_DESCRIPTION:
                # Wide enough for both columns: where the switch writes (or which distribution it came from), then
                # what the plugin does. The setting is the footnote, so it is the dimmer of the two. A row nothing
                # writes from — a compiled-in plugin that failed, whose setting never loaded — has no second column
                # to line up with, so what it has to say starts where the first one would have.
                setting = row.setting or row.origin
                said_at = start
                if setting:
                    canvas.draw_text(
                        start,
                        y,
                        truncate(setting, SETTING_WIDTH),
                        Style(foreground=blend(theme.muted, surface, 0.35), background=surface),
                        max_width=SETTING_WIDTH,
                    )
                    said_at = start + SETTING_WIDTH + COLUMN_GAP
                said = f"could not load: {row.failure}" if row.failure else row.description
                said_room = right - EDGE - said_at
                if said and said_room > 0:
                    canvas.draw_text(
                        said_at,
                        y,
                        truncate(said, said_room),
                        Style(foreground=theme.muted if not row.failure else theme.error, background=surface),
                        max_width=said_room,
                    )
                continue
            if room >= MIN_DESCRIPTION:
                if row.failure:
                    text, colour = f"could not load: {row.failure}", theme.error
                else:
                    text, colour = row.setting or row.origin, blend(theme.muted, surface, 0.35)
                canvas.draw_text(
                    start, y, truncate(text, room), Style(foreground=colour, background=surface), max_width=room
                )
        edge = Style(foreground=theme.muted, background=surface)
        if self.top > 0:
            canvas.draw_text(self.rect.right - 1, self.rect.y + LIST_TOP, "\u25b2", edge)
        if self.top + view < len(self._lines):
            canvas.draw_text(self.rect.right - 1, self.rect.y + LIST_TOP + view - 1, "\u25bc", edge)
