"""The page ``/plugins`` opens: the plugins the program carries, the ones installed beside it, and a switch for each.

Which rows have a switch is not this page's decision: the engine's catalog works it out (a compiled-in plugin has one
only when it declares the configuration key that decides it; an installed one always has, unless a line of the
configuration holds it), so the editor's panel and this one cannot disagree. What a switch writes is a promise about
the *next* start — the file is read once, when a process starts — and this one keeps what it already loaded.

Nothing here imports the engine: a row is the few facts the page draws, and the command that opens it fills them in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic

from zettcode.tui import ARROW_DOWN, ARROW_UP, SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

from .panel import pressed
from .switch import SWITCH_WIDTH, Rail, draw_switch

#: Rows the page spends on something other than the list: a blank, the title, a blank under it, a blank above the
#: description, the description, and the keys.
CHROME = 6

#: The first row of the list, counted from the top of the page.
LIST_TOP = 3

#: The headings the rows are grouped under: what the program carries, and what was installed beside it.
BUILTIN = "Built in"
INSTALLED = "Third-party"

#: What a row without a switch says in the switch column, when the configuration file holds the switch.
OFF_IN_CONFIG = "fixed"

#: Columns the plugin's name takes, the switch, and the word beside it. The name column fits the longest one the
#: program ships (``project-instructions``) with room to breathe before the switch.
NAME_WIDTH = 24
WORD_WIDTH = 8

#: The least columns a description is worth drawing in; narrower and the line under the list says it alone.
MIN_DESCRIPTION = 16

#: Columns kept free at the right of the list, where the marks saying it scrolls go.
EDGE = 2


@dataclass(frozen=True, slots=True)
class PluginRow:
    """One plugin as the page draws it.

    Attributes:
        name: What the plugin calls itself.
        origin: The distribution that carries it, and the name a switch is written with.
        builtin: Compiled into the program, so it is switched by a configuration key rather than `[plugins] disable`.
        enabled: Whether the next start does its work.
        failure: Why it could not load here, or ``""`` when it did.
        setting: The configuration key that decides a compiled-in plugin, such as ``"skills.enabled"``.
        switchable: Whether there is a switch to draw; the catalog decides it, so the editor's panel agrees.
        why: Why there is none, when there is none.
    """

    name: str
    origin: str
    builtin: bool = False
    enabled: bool = True
    failure: str = ""
    setting: str = ""
    switchable: bool = True
    why: str = ""


class PluginsPage(Widget):
    """Choose which plugins the next start does the work of.

    Shape::

        Plugins                                              3 of 5 on

          Built in ────────────────────────────────────────────────────────────
          ▸ skills       ━━━━●  on           skills.enabled
            mcp          ━━━━●  on           mcp.enabled
            todos        ●────  off          harness.todowrite
            coding       failed              could not load: no plugin provides the model
          Third-party ─────────────────────────────────────────────────────────
            monitor      ━━━━●  on           zettcode-monitor
            acme         ●────  off          zettcode-acme
            held         fixed               zettcode-held

          skills (skills.enabled) loads at the next start
          ↑ ↓ plugin · ← → switch · enter apply · esc cancel

    Up and Down move the marker, round from the last row to the first and back; Left, Right and Space move the switch
    of the marked plugin; Enter hands every change to the caller, which writes them down and closes the page; Escape
    writes nothing.

    Every row has a switch but the ones a reader cannot move, and those say why on the line under the list: a
    compiled-in plugin that could not load (its setting is unknown to this process, so the row has none), one whose
    switch is a line in the configuration file, and a group the configuration turned off as a whole. A compiled-in
    plugin with no setting of its own is not on the page at all — there would be nothing to press. It is an installed
    plugin that failed which keeps its switch, because `[plugins] disable` is exactly what would leave it out.

    Args:
        rows: The plugins a list shows, in the order they are grouped: the program's first.
        on_apply: Receives every changed plugin's origin and the state to write when Enter is pressed.
        on_cancel: Called when the reader backs out.
    """

    HINT = f"{ARROW_UP} {ARROW_DOWN} plugin {SEPARATOR} \u2190 \u2192 switch {SEPARATOR} enter apply {SEPARATOR} esc cancel"

    def __init__(
        self,
        rows: Sequence[PluginRow],
        *,
        on_apply: Callable[[dict[str, bool]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with every switch where the file has it, and the marker on the first plugin."""
        super().__init__()
        self.rows: tuple[PluginRow, ...] = tuple(rows)
        self.start = {row.origin: row.enabled for row in self.rows}
        self.switches = {row.origin: Rail(("off", "on"), int(row.enabled)) for row in self.rows if row.switchable}
        self.on_apply = on_apply
        self.on_cancel = on_cancel
        #: The plugin the marker is on, as an index into :attr:`rows`.
        self.mark = 0
        #: The first visible row of the list, counted in list rows (headings included).
        self.top = 0
        #: Why the last press did nothing, on the line under the list; cleared by the next move.
        self.note: str | None = None
        self._token = f"plugins-panel:{id(self)}"
        self._lines: list[tuple[str, int]] = []
        previous = None
        for index, row in enumerate(self.rows):
            title = BUILTIN if row.builtin else INSTALLED
            if title != previous:
                self._lines.append(("heading", index))
                previous = title
            self._lines.append(("plugin", index))

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

    def set(self, origin: str, on: bool) -> None:
        """Send one plugin's switch to on or off, and say on the line below why when it cannot move."""
        row = next((row for row in self.rows if row.origin == origin), None)
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

    def capture_event(self, event, host: Host) -> bool:
        """Take Escape before the focused widget can."""
        if pressed(event) == "escape":
            self.on_cancel()
            return True
        return False

    def handle(self, event, host: Host) -> bool:
        """Move with Up and Down, flip with Left, Right and Space, and apply with Enter."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        if not self.rows:
            return False
        name = self.rows[self.mark].origin
        match pressed(event):
            case "up" | "backtab":
                self._move(self.mark - 1)
            case "down" | "tab":
                self._move(self.mark + 1)
            case "pageup":
                self._move(self.mark - max(1, self._view() - 1))
            case "pagedown":
                self._move(self.mark + max(1, self._view() - 1))
            case "home":
                self._move(0)
            case "end":
                self._move(len(self.rows) - 1)
            case "left":
                self.set(name, False)
            case "right":
                self.set(name, True)
            case " ":
                rail = self.switches.get(name)
                self.set(name, not (rail.selected if rail is not None else False))
            case "enter":
                self.on_apply(self.changes)
            case _:
                return False
        return True

    def _move(self, index: int) -> None:
        """Put the marker on a row, round the ends, and take back what the last press said."""
        self.note = None
        self.mark = index % len(self.rows) if self.rows else 0

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Mark the row under a click, and flip its switch when the click is on the switch or its word."""
        if event.action is MouseAction.SCROLL_UP:
            self._move(self.mark - 1)
            return True
        if event.action is MouseAction.SCROLL_DOWN:
            self._move(self.mark + 1)
            return True
        if event.action is not MouseAction.DOWN:
            return False
        offset = event.y - (self.rect.y + LIST_TOP)
        index = self.top + offset
        if not 0 <= offset < self._view() or index >= len(self._lines):
            return False
        kind, at = self._lines[index]
        if kind != "plugin":
            return False
        row = self.rows[at]
        start = self._switch_column()
        if start <= event.x < start + SWITCH_WIDTH + 1 + WORD_WIDTH:
            self.mark = at
            rail = self.switches.get(row.origin)
            self.set(row.origin, not (rail.selected if rail is not None else False))
        else:
            self._move(at)
        return True

    def _view(self) -> int:
        """Return how many rows of the list the page has room for."""
        return max(1, self.rect.height - CHROME)

    def _switch_column(self) -> int:
        """Return the column the first switch cell is in."""
        return self.rect.x + 4 + NAME_WIDTH

    def _reveal(self) -> None:
        """Scroll the list the least that shows the marked plugin, and its heading when it is the first of its group."""
        if not self.rows:
            return
        view = self._view()
        row = self._lines.index(("plugin", self.mark))
        first = row - 1 if self._lines[row - 1][0] == "heading" else row
        if first < self.top:
            self.top = first
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
        self._reveal()
        self._draw_list(canvas)
        if not self.rows:
            canvas.draw_text(x, self.rect.y + LIST_TOP, "No plugin is loaded.", muted, max_width=room)
        if self.rows:
            row = self.rows[self.mark]
            head = f"{row.name}:"
            said = f"{head} {self.note or self._description(row)}"
            canvas.draw_text(x, self.rect.bottom - 2, truncate(said, room), muted, max_width=room)
            canvas.draw_text(x, self.rect.bottom - 2, head, bold, max_width=min(room, display_width(head)))
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.HINT, room), muted, max_width=room)

    def _description(self, row: PluginRow) -> str:
        """Return what the marked plugin does at the next start, or why it is not the reader's to switch."""
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
        return "it could not load, so there is no switch to move" if row.failure else row.why

    def _draw_list(self, canvas: Canvas) -> None:
        """Draw the visible rows: a heading for each group, then its plugins with their switches."""
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
            kind, at = self._lines[index]
            row = self.rows[at]
            if kind == "heading":
                title = BUILTIN if row.builtin else INSTALLED
                canvas.draw_text(x, y, title, Style(foreground=theme.muted, background=surface, bold=True))
                start = x + display_width(title) + 1
                if start < right:
                    canvas.draw_text(start, y, "\u2500" * (right - start), Style(foreground=groove, background=surface))
                continue
            rail = self.switches.get(row.origin)
            on = rail.position(now) if rail is not None else float(row.enabled)
            marked = at == self.mark
            if marked:
                canvas.draw_text(x, y, "\u25b8", Style(foreground=theme.accent, background=surface, bold=True))
            lit = theme.text if marked or on >= 0.5 else blend(theme.muted, surface, 0.25)
            canvas.draw_text(
                x + 2,
                y,
                truncate(row.name, NAME_WIDTH),
                Style(foreground=lit, background=surface, bold=marked),
                max_width=NAME_WIDTH,
            )
            switch = self._switch_column()
            word_at = switch + SWITCH_WIDTH + 1
            if rail is None:
                text = "failed" if row.failure else OFF_IN_CONFIG
                colour = theme.error if row.failure else theme.warning
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
            if room >= MIN_DESCRIPTION:
                if row.failure:
                    text, colour = f"could not load: {row.failure}", theme.error
                elif row.builtin:
                    text, colour = row.setting, blend(theme.muted, surface, 0.35)
                else:
                    text, colour = row.origin, blend(theme.muted, surface, 0.35)
                canvas.draw_text(
                    start, y, truncate(text, room), Style(foreground=colour, background=surface), max_width=room
                )
        edge = Style(foreground=theme.muted, background=surface)
        if self.top > 0:
            canvas.draw_text(self.rect.right - 1, self.rect.y + LIST_TOP, "\u25b2", edge)
        if self.top + view < len(self._lines):
            canvas.draw_text(self.rect.right - 1, self.rect.y + LIST_TOP + view - 1, "\u25bc", edge)
