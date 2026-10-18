"""The bottom panel ``/statusline`` opens: every named part of the header and status line, each with a switch."""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from time import monotonic

from zettcode.statusline import GAP, PET, Part, Row
from zettcode.tui import ARROW_DOWN, ARROW_UP, SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

from .. import labels
from .panel import pressed
from .self_compact_page import _Rail

#: Rows the panel needs besides the list: a blank, the title, a blank, the two preview rows, a blank above the
#: list, then below it a blank, the selected part's description and the keys.
CHROME = 9

#: The first row of the list, counted from the top of the panel.
LIST_TOP = 6

#: The least rows the list may be left with on a short screen, and the rows of the screen the panel leaves to
#: the conversation above it.
MIN_LIST = 4
LEFT_FOR_CONVERSATION = 8

#: The two rows of the screen as the panel shows them, each as its left and right side. They are built by the
#: functions that build the real rows, on a plausible session rather than the reader's own, so the names and
#: descriptions listed here are the ones the rows declare and cannot drift from them.
SAMPLE: dict[str, tuple[Row, Row]] = {
    "Header": (
        labels.header_left(Path("~/projects/api"), "Fix the parser", "fix-the-parser"),
        labels.header_right("gpt-5", "medium"),
    ),
    "Status line": (
        labels.status_left(
            "ready",
            permission="safe",
            self_compact=True,
            tokens=f"{ARROW_UP}12.3k {ARROW_DOWN}1.2k",
            cache="77.3% cached",
            speed="48 tok/s",
            ctx="ctx 34.0%",
        ),
        labels.status_right(),
    ),
}

#: Every part, in the order the rows show them, and the title of the row each is on. The pet is on no row of
#: the screen; it stands under a heading of its own, last.
PARTS: tuple[Part, ...] = (*(part for sides in SAMPLE.values() for side in sides for part in side.parts()), PET)
ROW_OF: dict[str, str] = {
    **{part.name: title for title, sides in SAMPLE.items() for side in sides for part in side.parts()},
    PET.name: "Companion",
}

#: One row for each part, and one heading for each group of them.
LIST_ROWS = len(PARTS) + len(SAMPLE) + 1

#: Columns the part names take, the switch, and the word beside it.
NAME_WIDTH = 14
SWITCH_WIDTH = 10
WORD_WIDTH = 7

#: The least columns a description is worth drawing in; narrower and the line under the list says it alone.
MIN_DESCRIPTION = 18


def statusline_rows(height: int) -> int:
    """Return the rows to ask for: the whole list when the screen has room for it, else what it can spare."""
    return max(CHROME + MIN_LIST, min(CHROME + LIST_ROWS, height - LEFT_FOR_CONVERSATION))


class StatuslinePage(Widget):
    """Choose which named parts of the header and the status line are shown.

    Shape::

        Status line                                          12 of 14 shown

          ◈ zettcode  Fix the parser · ~/projects/api              gpt-5 · medium
          ● ready · safe  ↑12.3k ↓1.2k · 77.3% cached · ctx 34.0%     ^C stop  ^D exit

          Header ──────────────────────────────────────────────────────────────
            app           ━━━━●  shown   The mark and name of the program
          ▸ session       ━━━━●  shown   The session's title; New session until it has one
            handle        ●────  hidden  The @name other sessions reach this one by
          …
          session: The session's title; New session until it has one
          ↑ ↓ part · ← → hide or show · enter apply · esc cancel

    Up and Down move between the parts, round from the last to the first and back, Left and Right (or Space) hide and show the one the marker is on, and
    the two rows above the list are what the header and the status line would look like with the choices as
    they stand, the marked part picked out. Nothing changes in the shell until Enter: Escape applies nothing.
    The switches travel the way the other panels' knobs do, from the clock and not from a frame count, and the
    list scrolls when the screen is too short for it.

    Args:
        hidden: The names of the parts that are hidden now; every other part is shown.
        on_apply: Receives every part's name and whether it is shown when Enter is pressed.
        on_cancel: Called when the reader backs out.
    """

    HINT = f"{ARROW_UP} {ARROW_DOWN} part {SEPARATOR} \u2190 \u2192 hide or show {SEPARATOR} enter apply {SEPARATOR} esc cancel"

    def __init__(
        self,
        hidden: Collection[str],
        *,
        on_apply: Callable[[dict[str, bool]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with every switch where the settings are now, and the marker on the first part."""
        super().__init__()
        self.start = {part.name: part.name not in hidden for part in PARTS}
        self.switches = {name: _Rail(("hidden", "shown"), int(shown)) for name, shown in self.start.items()}
        self.on_apply = on_apply
        self.on_cancel = on_cancel
        #: The part the marker is on, as an index into :data:`PARTS`.
        self.mark = 0
        #: The first visible row of the list, counted in list rows (headings included).
        self.top = 0
        self._token = f"statusline-panel:{id(self)}"
        self._lines: list[tuple[str, int]] = []
        previous = None
        for index, part in enumerate(PARTS):
            if ROW_OF[part.name] != previous:
                self._lines.append(("heading", index))
                previous = ROW_OF[part.name]
            self._lines.append(("part", index))

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def shown(self) -> dict[str, bool]:
        """Return every part's name and whether it is shown once the switches arrive."""
        return {name: bool(rail.selected) for name, rail in self.switches.items()}

    @property
    def changed(self) -> bool:
        """Return whether any switch is anywhere but where it started."""
        return self.shown != self.start

    @property
    def moving(self) -> bool:
        """Return whether a switch is still on its way."""
        return any(rail.moving for rail in self.switches.values())

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def set(self, name: str, shown: bool) -> None:
        """Send one part's switch to shown or hidden, and set the marker on it."""
        self.mark = next(index for index, part in enumerate(PARTS) if part.name == name)
        reduced = self.app is not None and self.app.reduced_motion
        if self.switches[name].choose(int(shown), self._now(), instant=reduced) and self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the frame loop, so a panel put away mid-slide stops costing frames."""
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
        """Move the marker with Up and Down, hide and show with Left and Right, and apply with Enter."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        name = PARTS[self.mark].name
        match pressed(event):
            case "up" | "backtab":
                self.mark = (self.mark - 1) % len(PARTS)
            case "down" | "tab":
                self.mark = (self.mark + 1) % len(PARTS)
            case "pageup":
                self.mark = max(0, self.mark - max(1, self._view() - 1))
            case "pagedown":
                self.mark = min(len(PARTS) - 1, self.mark + max(1, self._view() - 1))
            case "home":
                self.mark = 0
            case "end":
                self.mark = len(PARTS) - 1
            case "left":
                self.set(name, False)
            case "right":
                self.set(name, True)
            case " ":
                self.set(name, not self.switches[name].selected)
            case "enter":
                self.on_apply(self.shown)
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Mark the part under a click, and flip its switch when the click is on the switch or its word."""
        if event.action is MouseAction.SCROLL_UP:
            self.mark = max(0, self.mark - 1)
            return True
        if event.action is MouseAction.SCROLL_DOWN:
            self.mark = min(len(PARTS) - 1, self.mark + 1)
            return True
        if event.action is not MouseAction.DOWN:
            return False
        offset = event.y - (self.rect.y + LIST_TOP)
        index = self.top + offset
        if not 0 <= offset < self._view() or index >= len(self._lines):
            return False
        kind, part = self._lines[index]
        if kind != "part":
            return False
        name = PARTS[part].name
        start = self._switch_column()
        if start <= event.x < start + SWITCH_WIDTH + 1 + WORD_WIDTH:
            self.set(name, not self.switches[name].selected)
        else:
            self.mark = part
        return True

    def _view(self) -> int:
        """Return how many rows of the list the panel has room for."""
        return max(1, self.rect.height - CHROME)

    def _switch_column(self) -> int:
        """Return the column the first switch cell is in."""
        return self.rect.x + 2 + 2 + NAME_WIDTH

    def _reveal(self) -> None:
        """Scroll the list the least that shows the marked part, and its heading when it is the first of its row."""
        view = self._view()
        row = self._lines.index(("part", self.mark))
        first = row - 1 if self._lines[row - 1][0] == "heading" else row
        if first < self.top:
            self.top = first
        if row >= self.top + view:
            self.top = row - view + 1
        self.top = max(0, min(self.top, len(self._lines) - view))

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the title, the preview, the list, the description and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        bold = Style(foreground=theme.text, background=surface, bold=True)
        canvas.draw_text(x, self.rect.y + 1, "Status line", bold, max_width=room)
        count = sum(self.shown.values())
        gap = room - display_width("Status line") - 2
        suffix = " (not applied)" if self.changed else ""
        state = next(
            (
                text
                for text in (
                    f"{count} of {len(PARTS)} shown{suffix}",
                    f"{count} of {len(PARTS)} shown",
                    f"{count}/{len(PARTS)}",
                )
                if display_width(text) <= gap
            ),
            "",
        )
        canvas.draw_text(
            self.rect.right - 2 - display_width(state),
            self.rect.y + 1,
            state,
            Style(foreground=theme.accent if self.changed else theme.muted, background=surface, bold=self.changed),
            max_width=room,
        )
        for offset, title in enumerate(SAMPLE):
            self._draw_preview(canvas, SAMPLE[title], self.rect.y + 3 + offset)
        self._reveal()
        self._draw_list(canvas)
        part = PARTS[self.mark]
        description = (
            f"{part.name}: {part.summary}" if self.shown[part.name] else f"{part.name} is hidden: {part.summary}"
        )
        head = f"{part.name}:" if self.shown[part.name] else f"{part.name} is hidden:"
        canvas.draw_text(x, self.rect.bottom - 2, truncate(description, room), muted, max_width=room)
        canvas.draw_text(x, self.rect.bottom - 2, head, bold, max_width=min(room, display_width(head)))
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.HINT, room), muted, max_width=room)

    def _draw_preview(self, canvas: Canvas, sides: tuple[Row, Row], y: int) -> None:
        """Draw one row of the screen as it would read with the switches as they stand, in a strip of its own."""
        theme = self.theme
        strip = blend(theme.surface_alt, theme.muted, 0.14)
        left = self.rect.x
        width = self.rect.width
        canvas.fill(left, y, width, 1, Style(background=strip))
        hidden = {name for name, shown in self.shown.items() if not shown}
        runs = [self._runs(side, hidden) for side in sides]
        lengths = [sum(display_width(text) for text, _ in side) for side in runs]
        if not any(lengths):
            canvas.draw_text(
                left + 2, y, "nothing is shown here", Style(foreground=theme.muted, background=strip, italic=True)
            )
            return
        # The right side keeps its width and the left gives way, as the real bar does.
        right_at = max(left, left + width - lengths[1])
        room = max(0, right_at - left - (display_width(GAP) if lengths[1] else 0))
        self._draw_runs(canvas, runs[0], left, y, min(room, width), strip)
        self._draw_runs(canvas, runs[1], right_at, y, lengths[1], strip)

    @staticmethod
    def _runs(side: Row, hidden: Collection[str]) -> list[tuple[str, str | None]]:
        """Return a side as the runs of text it is written in, each with the part it belongs to (``None`` for glue)."""
        runs: list[tuple[str, str | None]] = []
        for glue, part in side.shown(hidden):
            runs.extend([(glue, None), (part.text, part.name)])
        return [*runs, (side.trail, None)] if runs and side.trail else runs

    def _draw_runs(
        self, canvas: Canvas, runs: list[tuple[str, str | None]], x: int, y: int, room: int, strip: str
    ) -> None:
        """Draw a side's runs one after the other, the marked part picked out, and stop when the room is used."""
        theme = self.theme
        marked = PARTS[self.mark].name
        column = x
        for piece, name in runs:
            left = room - (column - x)
            if left <= 0:
                break
            style = (
                Style(foreground=theme.text, background=strip, bold=True)
                if name == marked
                else Style(foreground=theme.muted, background=strip)
            )
            text = truncate(piece, left) if display_width(piece) > left else piece
            canvas.draw_text(column, y, text, style, max_width=left)
            column += display_width(text)

    def _draw_list(self, canvas: Canvas) -> None:
        """Draw the visible rows of the list: a heading for each screen row, then its parts with their switches."""
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
            if kind == "heading":
                title = ROW_OF[PARTS[at].name]
                canvas.draw_text(x, y, title, Style(foreground=theme.muted, background=surface, bold=True))
                start = x + display_width(title) + 1
                if start < right:
                    canvas.draw_text(start, y, "\u2500" * (right - start), Style(foreground=groove, background=surface))
                continue
            part = PARTS[at]
            rail = self.switches[part.name]
            on = rail.position(now)
            marked = at == self.mark
            lit = blend(theme.muted, theme.text, 0.55) if on < 0.5 else theme.text
            name_style = Style(foreground=lit if on >= 0.5 else blend(theme.muted, surface, 0.25), background=surface)
            if marked:
                name_style = Style(foreground=theme.text, background=surface, bold=True)
                canvas.draw_text(x, y, "\u25b8", Style(foreground=theme.accent, background=surface, bold=True))
            canvas.draw_text(x + 2, y, truncate(part.name, NAME_WIDTH), name_style, max_width=NAME_WIDTH)
            switch = self._switch_column()
            self._draw_switch(canvas, y, switch, on, groove)
            word = "shown" if rail.selected else "hidden"
            canvas.draw_text(
                switch + SWITCH_WIDTH + 1,
                y,
                word,
                Style(
                    foreground=theme.accent if rail.selected else blend(theme.muted, surface, 0.25),
                    background=surface,
                ),
            )
            start = switch + SWITCH_WIDTH + 1 + WORD_WIDTH + 1
            room = right - 2 - start
            if room >= MIN_DESCRIPTION:
                canvas.draw_text(
                    start,
                    y,
                    truncate(part.summary, room),
                    Style(foreground=blend(theme.muted, surface, 0.15), background=surface),
                    max_width=room,
                )
        # A mark at the edge says there is more list than the screen could give it.
        edge = Style(foreground=theme.muted, background=surface)
        if self.top > 0:
            canvas.draw_text(self.rect.right - 2, self.rect.y + LIST_TOP, "\u25b2", edge)
        if self.top + view < len(self._lines):
            canvas.draw_text(self.rect.right - 2, self.rect.y + LIST_TOP + view - 1, "\u25bc", edge)

    def _draw_switch(self, canvas: Canvas, y: int, x: int, position: float, groove: str) -> None:
        """Draw a switch as a short thin rail: lit up to the knob when shown, the knob at the start of a groove when not.

        It is the rail the other panels use, drawn the same way, with its round knob. The rail is ten columns:
        short enough to sit beside a name, long enough that the knob crosses nine columns in the slide instead of
        the four a five-column rail gives it, which is what made it jump. The position is the clock's, so a slow
        terminal drops frames instead of slowing the knob.
        """
        theme = self.theme
        surface = theme.surface_alt
        knob = round(max(0.0, min(1.0, position)) * (SWITCH_WIDTH - 1))
        lit = blend(blend(theme.muted, surface, 0.25), theme.accent, position)
        for cell in range(SWITCH_WIDTH):
            if cell < knob:
                canvas.draw_text(x + cell, y, "\u2501", Style(foreground=lit, background=surface))
            elif cell > knob:
                canvas.draw_text(x + cell, y, "\u2500", Style(foreground=groove, background=surface))
        colour = blend(lit, theme.text, 0.35 * position)
        canvas.draw_text(x + knob, y, "\u25cf", Style(foreground=colour, background=surface, bold=True))
