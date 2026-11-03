"""The bottom panel ``/self-compact`` opens: two rails, one for this session and one for every session."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from zettcode.tui import SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Theme, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

from .panel import pressed
from .switch import Rail

#: Rows the panel takes: a blank, the title, a blank, the session rail and its labels, a blank, the default
#: rail and its labels, a blank, what is in effect, the note, and the keys.
SELF_COMPACT_ROWS = 12

#: Columns kept free at the right of a rail so the last label stays inside the panel.
RAIL_MARGIN = 5

#: Columns the row names take, and the least a rail may be left with before the names shrink to make room.
NAME_WIDTH = 15
MIN_RAIL = 12

#: Characters of a rail: a lit stretch, the groove it runs in, a node passed, a node ahead, and the knob.
LIT, GROOVE, PASSED, AHEAD, KNOB = "\u2501", "\u2500", "\u25cf", "\u25cb", "\u25c9"

#: What this session can be: no choice (it follows the default), off, or on. ``None`` is the first.
SESSION_CHOICES: tuple[bool | None, ...] = (None, False, True)
SESSION_WORDS = ("default", "off", "on")
DEFAULT_WORDS = ("off", "on")

#: One line per option, shown under the rails for the one the knob is on.
SESSION_NOTES = {
    "default": "this session follows the default below, whatever it becomes",
    "off": "the model cannot compact its own context in this session",
    "on": "the model may compact its own context in this session",
}
DEFAULT_NOTES = {
    "off": "sessions that never chose start with it off",
    "on": "sessions that never chose start with it on",
}


class SelfCompactPage(Widget):
    """Choose whether the model may compact its own context, for this session and as the default.

    Shape::

        Self-compaction                                  in effect here: on

        \u25b8 This session   \u25cf\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u25c9\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u25cb
                         default (off)      off          on
          Every session  \u25cf\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u25c9
                         off                             on

        this session chose it \u00b7 sessions that never chose start with it on
        the model may compact its own context in this session

        \u2191 \u2193 row \u00b7 \u2190 \u2192 set \u00b7 enter apply \u00b7 esc cancel

    The top rail is this session's own choice: ``default`` means it has none and follows the rail below,
    ``off`` and ``on`` are a choice that stays with the session. The bottom rail is the default for every
    session that never chose, which is what ``[compaction] self`` in the config file says. Moving a knob
    changes nothing: the line under the rails says what would be in effect, and Enter applies both rails
    (the default is written to the config file, the choice is saved with the session). Escape applies
    nothing. The knobs travel the way the effort panel's does, from the clock and not from a frame count.

    Args:
        choice: This session's own choice, ``None`` when it has none.
        default: The default for every session.
        on_apply: Receives the session's choice and the default when Enter is pressed.
        on_cancel: Called when the reader backs out.
        session_open: Whether this process may change the session. A session another process has open
            keeps what it has, and only the default can be moved.
    """

    HINT = f"\u2191 \u2193 row {SEPARATOR} \u2190 \u2192 set {SEPARATOR} enter apply {SEPARATOR} esc cancel"

    def __init__(
        self,
        choice: bool | None,
        default: bool,
        *,
        on_apply: Callable[[bool | None, bool], None],
        on_cancel: Callable[[], None],
        session_open: bool = True,
    ) -> None:
        """Start with both knobs where the settings are now."""
        super().__init__()
        self.session_rail = Rail(SESSION_WORDS, SESSION_CHOICES.index(choice))
        self.default_rail = Rail(DEFAULT_WORDS, int(default))
        self.on_apply = on_apply
        self.on_cancel = on_cancel
        self.session_open = session_open
        #: The row the arrows move: 0 for the session, 1 for the default.
        self.row = 0 if session_open else 1
        self._token = f"self-compact-panel:{id(self)}"

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def choice(self) -> bool | None:
        """Return this session's choice once the knob arrives."""
        return SESSION_CHOICES[self.session_rail.selected]

    @property
    def default(self) -> bool:
        """Return the default once the knob arrives."""
        return bool(self.default_rail.selected)

    @property
    def effective(self) -> bool:
        """Return what would be in force in this session if the panel were applied now."""
        return self.default if self.choice is None else self.choice

    @property
    def changed(self) -> bool:
        """Return whether either knob is anywhere but where it started."""
        return (
            self.session_rail.selected != self.session_rail.start
            or self.default_rail.selected != self.default_rail.start
        )

    @property
    def moving(self) -> bool:
        """Return whether a knob is still on its way."""
        return self.session_rail.moving or self.default_rail.moving

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def _active(self) -> Rail:
        return self.session_rail if self.row == 0 else self.default_rail

    def choose(self, row: int, index: int) -> None:
        """Send one row's knob to an option, and make that the row the arrows move."""
        if row == 0 and not self.session_open:
            return
        self.row = row
        rail = self.session_rail if row == 0 else self.default_rail
        reduced = self.app is not None and self.app.reduced_motion
        if rail.choose(index, self._now(), instant=reduced) and self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the frame loop, so a panel put away mid-slide stops costing frames."""
        self.session_rail.moving = self.default_rail.moving = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_tick(self) -> bool:
        """Hand the frame loop back once both knobs have arrived; say whether the picture is still changing."""
        now = self._now()
        landed = self.session_rail.arrive(now) | self.default_rail.arrive(now)
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
        """Move between the rows with Up and Down, along one with Left and Right, and apply with Enter."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        rail = self._active()
        match pressed(event):
            case "up" | "backtab":
                self.row = 0 if self.session_open else 1
            case "down" | "tab":
                self.row = 1
            case "left":
                self.choose(self.row, rail.selected - 1)
            case "right":
                self.choose(self.row, rail.selected + 1)
            case "home":
                self.choose(self.row, 0)
            case "end":
                self.choose(self.row, len(rail.words) - 1)
            case "enter":
                self.on_apply(self.choice, self.default)
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Send a knob to the option nearest a click on its rail or its labels."""
        if event.action is not MouseAction.DOWN:
            return False
        top = self.rect.y + 3
        for row, first in ((0, top), (1, top + 3)):
            if first <= event.y <= first + 1:
                rail = self.session_rail if row == 0 else self.default_rail
                left, right = self._rail()
                nearest = min(
                    range(len(rail.words)), key=lambda index: abs(self._column(rail, index, left, right) - event.x)
                )
                self.choose(row, nearest)
                return True
        return False

    def _names(self) -> int:
        """Return the columns the row names take: less on a panel too narrow to leave the rails room."""
        room = max(0, self.rect.width - 4 - RAIL_MARGIN)
        return max(0, min(NAME_WIDTH, room - MIN_RAIL))

    def _rail(self) -> tuple[int, int]:
        """Return the first and last column of a rail."""
        left = self.rect.x + 2 + self._names() + 2
        return left, max(left, self.rect.right - RAIL_MARGIN - 1)

    @staticmethod
    def _column(rail: Rail, index: float, left: int, right: int) -> int:
        """Return the column a (possibly fractional) option sits at."""
        steps = max(1, len(rail.words) - 1)
        return left + round(index * (right - left) / steps)

    def _colour(self, theme: Theme, rail: Rail, index: float) -> str:
        """Return the colour of a point on a rail: grey for off, the accent for on, the text for no choice."""
        stops: tuple[str, ...]
        if rail is self.session_rail:
            stops = (theme.text, theme.muted, theme.accent)
        else:
            stops = (theme.muted, theme.accent)
        scaled = min(max(index, 0.0), len(stops) - 1)
        low = min(int(scaled), len(stops) - 2)
        return blend(stops[low], stops[low + 1], scaled - low)

    def _label(self, rail: Rail, index: int) -> str:
        """Return the words under an option: ``default`` says what it would be, and the old place says ``now``."""
        word = rail.words[index]
        if rail is self.session_rail and index == 0:
            word = f"default ({'on' if self.default else 'off'})"
        if index == rail.start and rail.selected != rail.start:
            word = f"{word} (now)"
        return word

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the title, the two rails, what is in effect, the note and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        bold = Style(foreground=theme.text, background=surface, bold=True)
        canvas.draw_text(x, self.rect.y + 1, "Self-compaction", bold, max_width=room)
        word = "on" if self.effective else "off"
        # What is in force, as long as there is room beside the title; shorter before it would run into it.
        gap = room - display_width("Self-compaction") - 2
        suffix = " (not applied)" if self.changed else ""
        state = next(
            (
                text
                for text in (f"in effect here: {word}{suffix}", f"in effect here: {word}", word)
                if display_width(text) <= gap
            ),
            "",
        )
        canvas.draw_text(
            self.rect.right - 2 - display_width(state),
            self.rect.y + 1,
            state,
            Style(foreground=theme.accent if self.effective else theme.muted, background=surface, bold=True),
            max_width=room,
        )
        left, right = self._rail()
        now = self._now()
        names = self._names()
        for row, (title, rail) in enumerate(
            (("This session", self.session_rail), ("Every session", self.default_rail))
        ):
            top = self.rect.y + 3 + row * 3
            enabled = row == 1 or self.session_open
            active = row == self.row
            mark = "\u25b8 " if active and enabled else "  "
            canvas.draw_text(
                x,
                top,
                truncate(mark + title, names),
                bold if active and enabled else muted,
                max_width=names,
            )
            self._draw_rail(canvas, rail, top, left, right, now, enabled)
            self._draw_labels(canvas, rail, top + 1, left, right, now, enabled)
        summary = self._summary()
        canvas.draw_text(x, self.rect.y + 9, truncate(summary, room), muted, max_width=room)
        canvas.draw_text(x, self.rect.y + 10, truncate(self._note(), room), muted, max_width=room)
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.HINT, room), muted, max_width=room)

    def _draw_rail(self, canvas: Canvas, rail: Rail, y: int, left: int, right: int, now: float, enabled: bool) -> None:
        """Draw one rail: lit up to the knob in the colour of where each cell sits, the nodes, and the knob."""
        theme = self.theme
        surface = theme.surface_alt
        position = rail.position(now)
        knob = self._column(rail, position, left, right)
        groove = blend(theme.muted, surface, 0.55)
        dim = 0.0 if enabled else 0.6
        steps = max(1, len(rail.words) - 1)
        for column in range(left, right + 1):
            if column <= knob:
                colour = blend(self._colour(theme, rail, (column - left) / max(1, right - left) * steps), surface, dim)
                canvas.draw_text(column, y, LIT, Style(foreground=colour, background=surface))
            else:
                canvas.draw_text(column, y, GROOVE, Style(foreground=groove, background=surface))
        for index in range(len(rail.words)):
            column = self._column(rail, index, left, right)
            if column < knob:
                colour = blend(self._colour(theme, rail, index), surface, dim)
                canvas.draw_text(column, y, PASSED, Style(foreground=colour, background=surface, bold=True))
            elif column > knob:
                colour = blend(theme.muted, surface, 0.2 + dim)
                canvas.draw_text(column, y, AHEAD, Style(foreground=colour, background=surface))
        colour = blend(blend(self._colour(theme, rail, position), theme.text, 0.35), surface, dim)
        canvas.draw_text(knob, y, KNOB, Style(foreground=colour, background=surface, bold=True))

    def _draw_labels(
        self, canvas: Canvas, rail: Rail, y: int, left: int, right: int, now: float, enabled: bool
    ) -> None:
        """Write each option under its node, skipping any that would run into one already written.

        The option the knob is on is written first and never skipped, then the rest from the left, so on a
        narrow panel what is left is the knob's neighbourhood rather than an arbitrary run.
        """
        theme = self.theme
        nearest = min(len(rail.words) - 1, max(0, round(rail.position(now))))
        taken: list[tuple[int, int]] = []
        order = [nearest] + [index for index in range(len(rail.words)) if index != nearest]
        for index in order:
            label = self._label(rail, index)
            width = display_width(label)
            start = self._column(rail, index, left, right) - width // 2
            start = max(self.rect.x + 1, min(start, self.rect.right - 1 - width))
            if any(start < stop + 1 and first < start + width + 1 for first, stop in taken):
                continue
            taken.append((start, start + width))
            on = index == nearest and enabled
            style = Style(foreground=theme.text if on else theme.muted, background=theme.surface_alt, bold=on)
            canvas.draw_text(start, y, label, style, max_width=width)

    def _summary(self) -> str:
        """Say where what is in force comes from, and what the default is."""
        default = "on" if self.default else "off"
        if self.choice is None:
            return f"following the default, which is {default}"
        return f"this session chose it; the default is {default}"

    def _note(self) -> str:
        """Return the note for the option the active knob is on."""
        if not self.session_open and self.row == 1:
            return "this session is open in another process, so only the default can change"
        rail = self._active()
        notes = SESSION_NOTES if self.row == 0 else DEFAULT_NOTES
        return notes[rail.words[rail.selected]]
