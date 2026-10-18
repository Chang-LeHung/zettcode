"""The bottom panel ``/effort`` opens: a rail with a node for every level and a knob that slides along it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from time import monotonic

from zettcode.tui import SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Theme, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

from .panel import pressed

#: Rows the panel takes: a blank, the title, a blank, the name over the knob, the rail, the labels, what is
#: in force, the note, and the keys.
EFFORT_ROWS = 9

#: Seconds the knob takes to travel to the level it was sent to.
SLIDE_SECONDS = 0.28

#: Columns kept free on each side of the rail so the first and last labels stay inside the panel.
RAIL_MARGIN = 5

#: Characters of the rail: a lit stretch, the groove it runs in, a node passed, a node ahead, and the knob.
LIT, GROOVE, PASSED, AHEAD, KNOB = "\u2501", "\u2500", "\u25cf", "\u25cb", "\u25c9"


def heat_colour(theme: Theme, heat: float) -> str:
    """Return the colour of a point on the effort scale, from cheap to dear.

    The ramp runs through the theme's own accents \u2014 green, a brighter green, amber, and the error colour
    \u2014 rather than through fixed hues, so it follows ``/theme`` and a light palette gets the darker ends of
    the same story. Position on the scale is the only input: the same level is the same colour whether
    it is being switched to or away from. The header's gauge and this panel read the same ramp.
    """
    stops = (theme.accent, theme.accent_bright, theme.warning, theme.error)
    scaled = min(max(heat, 0.0), 1.0) * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    return blend(stops[index], stops[index + 1], scaled - index)


class EffortPage(Widget):
    """Choose how much the model reasons by sliding a knob along a rail.

    Shape::

        Reasoning effort                                      medium \u2192 high

                                      high
        \u25cf\u2501\u2501\u2501\u2501\u2501\u25cf\u2501\u2501\u2501\u2501\u2501\u25cf\u2501\u2501\u2501\u2501\u2501\u25c9\u2500\u2500\u2500\u2500\u2500\u25cb\u2500\u2500\u2500\u2500\u2500\u25cb\u2500\u2500\u2500\u2500\u2500\u25cb
        off  minimal  low  medium  high  xhigh  max  ultra
                        now
        more thought on hard problems

        \u2190 \u2192 move \u00b7 enter select \u00b7 esc cancel

    Left and Right send the knob to the next level and it *travels* there: it eases along the rail, the
    stretch behind it lights in the colour of the scale (green for the cheap end, warm for the dear end), the
    nodes it passes light as it reaches them, and the name over it follows. Nothing is changed by moving
    it: Enter applies the level under the knob and puts the panel away, which is when the header plays its
    own gauge; Escape puts the panel away and leaves the level as it was. Left and Right stop at the ends of the
    scale, which is ordered cheapest first: wrapping from ``ultra`` to ``off`` would be the one move in the
    row that takes a reader across the whole range.

    The motion is the clock's, not a frame count: the knob is placed from the time since it set off, so a slow
    terminal drops frames instead of slowing the knob down, and under reduced motion it simply jumps.

    Args:
        levels: The levels, cheapest first.
        current: The level in force when the panel opens.
        notes: One line per level, shown under the rail for the level under the knob.
        on_select: Receives the level Enter applied.
        on_cancel: Called when the reader backs out.
    """

    HINT = f"\u2190 \u2192 move {SEPARATOR} enter select {SEPARATOR} esc cancel"

    def __init__(
        self,
        levels: Sequence[str],
        current: str,
        *,
        notes: Mapping[str, str] | None = None,
        on_select: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with the knob on ``current`` (or the first level when it is not one of ``levels``)."""
        super().__init__()
        self.levels = tuple(levels)
        self.notes = dict(notes or {})
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.start = self.levels.index(current) if current in self.levels else 0
        self.selected = self.start
        self._origin = float(self.start)
        self._set_off = 0.0
        self._token = f"effort-panel:{id(self)}"
        self._moving = False

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def level(self) -> str:
        """Return the level under the knob once it arrives."""
        return self.levels[self.selected] if self.levels else ""

    @property
    def moving(self) -> bool:
        """Return whether the knob is still on its way."""
        return self._moving

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def position(self) -> float:
        """Return where the knob is on the scale now, in levels from the first: a fraction while it travels."""
        if not self._moving:
            return float(self.selected)
        progress = (self._now() - self._set_off) / SLIDE_SECONDS
        if progress >= 1.0:
            return float(self.selected)
        eased = 1 - (1 - max(0.0, progress)) ** 3
        return self._origin + (self.selected - self._origin) * eased

    def choose(self, index: int) -> None:
        """Send the knob to a level by position; the one it is already heading for is left alone."""
        if not self.levels:
            return
        index = max(0, min(len(self.levels) - 1, index))
        if index == self.selected:
            return
        self._origin = self.position()
        self.selected = index
        self._set_off = self._now()
        if self.app is not None and self.app.reduced_motion:
            self._origin = float(index)
            self._moving = False
            return
        self._moving = True
        if self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the frame loop, so a panel put away mid-slide stops costing frames."""
        self._moving = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_tick(self) -> bool:
        """Hand the frame loop back once the knob has arrived; say whether the picture is still changing."""
        if self._moving and self.position() == float(self.selected):
            self._moving = False
            self._origin = float(self.selected)
            if self.app is not None:
                self.app.scheduler.animate(self._token, active=False)
            return True  # the last frame, with the knob on its node
        return self._moving

    def capture_event(self, event, host: Host) -> bool:
        """Take Escape before the focused widget can."""
        if pressed(event) == "escape":
            self.on_cancel()
            return True
        return False

    def handle(self, event, host: Host) -> bool:
        """Slide with Left and Right (and Home and End), and apply with Enter."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        match pressed(event):
            case "left":
                self.choose(self.selected - 1)
            case "right":
                self.choose(self.selected + 1)
            case "home":
                self.choose(0)
            case "end":
                self.choose(len(self.levels) - 1)
            case "enter":
                self.on_select(self.level)
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Send the knob to the level nearest a click on the rail or its labels."""
        top = self.rect.y + 3
        if event.action is not MouseAction.DOWN or not top <= event.y <= top + 3 or not self.levels:
            return False
        left, right = self._rail()
        nearest = min(range(len(self.levels)), key=lambda index: abs(self._column(index, left, right) - event.x))
        self.choose(nearest)
        return True

    def _rail(self) -> tuple[int, int]:
        """Return the first and last column of the rail."""
        left = self.rect.x + RAIL_MARGIN
        return left, max(left, self.rect.right - RAIL_MARGIN - 1)

    def _column(self, index: float, left: int, right: int) -> int:
        """Return the column a (possibly fractional) level sits at."""
        steps = max(1, len(self.levels) - 1)
        return left + round(index * (right - left) / steps)

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the title, the rail with its knob, the labels, the note and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        canvas.draw_text(
            x,
            self.rect.y + 1,
            "Reasoning effort",
            Style(foreground=theme.text, background=surface, bold=True),
            max_width=room,
        )
        if not self.levels:
            return
        last = max(1, len(self.levels) - 1)
        position = self.position()
        nearest = min(len(self.levels) - 1, max(0, round(position)))
        if self.selected != self.start:
            change = f"{self.levels[self.start]} \u2192 {self.level}"
            canvas.draw_text(
                self.rect.right - 2 - display_width(change),
                self.rect.y + 1,
                change,
                Style(foreground=heat_colour(theme, self.selected / last), background=surface),
                max_width=room,
            )
        left, right = self._rail()
        knob = self._column(position, left, right)
        rail_y = self.rect.y + 4
        groove = blend(theme.muted, surface, 0.55)
        # The rail first: lit up to the knob in the colour of where each cell sits on the scale, groove after it.
        for column in range(left, right + 1):
            if column <= knob:
                heat = (column - left) / max(1, right - left)
                canvas.draw_text(column, rail_y, LIT, Style(foreground=heat_colour(theme, heat), background=surface))
            else:
                canvas.draw_text(column, rail_y, GROOVE, Style(foreground=groove, background=surface))
        for index in range(len(self.levels)):
            column = self._column(index, left, right)
            if column < knob:
                style = Style(foreground=heat_colour(theme, index / last), background=surface, bold=True)
                canvas.draw_text(column, rail_y, PASSED, style)
            elif column > knob:
                canvas.draw_text(
                    column, rail_y, AHEAD, Style(foreground=blend(theme.muted, surface, 0.2), background=surface)
                )
        knob_colour = heat_colour(theme, position / last)
        canvas.draw_text(
            knob, rail_y, KNOB, Style(foreground=blend(knob_colour, theme.text, 0.35), background=surface, bold=True)
        )
        # The name over the knob follows it, in the colour of the level it is nearest.
        word = self.levels[nearest]
        over = min(max(knob - display_width(word) // 2, x), max(x, self.rect.right - 2 - display_width(word)))
        canvas.draw_text(
            over, rail_y - 1, word, Style(foreground=heat_colour(theme, nearest / last), background=surface, bold=True)
        )
        self._labels(canvas, rail_y + 1, left, right, nearest, muted)
        now_column = self._column(self.start, left, right) - 1
        canvas.draw_text(now_column, rail_y + 2, "now", muted, max_width=max(0, self.rect.right - 1 - now_column))
        note = self.notes.get(self.level, "")
        if note:
            canvas.draw_text(x, rail_y + 3, truncate(note, room), muted, max_width=room)
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.HINT, room), muted, max_width=room)

    def _labels(self, canvas: Canvas, y: int, left: int, right: int, nearest: int, muted: Style) -> None:
        """Write each level under its node, skipping the ones that would run into a label already written.

        The level the knob is on is written first and never skipped, then the rest from the left, so on a
        narrow panel what is left is the knob's neighbourhood rather than an arbitrary run.
        """
        theme = self.theme
        taken: list[tuple[int, int]] = []
        order = [nearest] + [index for index in range(len(self.levels)) if index != nearest]
        for index in order:
            label = self.levels[index]
            width = display_width(label)
            start = self._column(index, left, right) - width // 2
            start = max(self.rect.x + 1, min(start, self.rect.right - 1 - width))
            if any(start < stop + 1 and first < start + width + 1 for first, stop in taken):
                continue
            taken.append((start, start + width))
            on = index == nearest
            style = Style(foreground=theme.text if on else theme.muted, background=theme.surface_alt, bold=on)
            canvas.draw_text(start, y, label, style, max_width=width)
