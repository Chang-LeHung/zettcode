"""The switch the shell's panels draw: a short rail with a round knob, and the state of one row's switch.

``/self-compact``, ``/statusline``, ``/config``'s one-model panel and ``/plugins`` all draw the same switch, so the thing
a reader presses looks the same wherever they press it. It lives in a module of its own because more than one page
draws it: a page importing another page's private helper was how it used to be spelled.
"""

from __future__ import annotations

from zettcode.tui import Canvas, Theme
from zettcode.tui.render import Style, blend

#: Seconds a knob takes to travel to the option it was sent to.
SLIDE_SECONDS = 0.28

#: Columns of the rail: short enough to sit beside a name, long enough that the knob crosses nine columns in the slide
#: instead of the four a five-column rail gives it, which is what made it jump.
SWITCH_WIDTH = 10


class Rail:
    """One row's choices and the knob on them: where it is, where it is going, and how it gets there."""

    def __init__(self, words: tuple[str, ...], current: int) -> None:
        self.words = words
        self.start = current
        self.selected = current
        self.origin = float(current)
        self.set_off = 0.0
        self.moving = False

    def position(self, now: float) -> float:
        """Return where the knob is, in options from the first: a fraction while it travels."""
        if not self.moving:
            return float(self.selected)
        progress = (now - self.set_off) / SLIDE_SECONDS
        if progress >= 1.0:
            return float(self.selected)
        eased = 1 - (1 - max(0.0, progress)) ** 3
        return self.origin + (self.selected - self.origin) * eased

    def choose(self, index: int, now: float, *, instant: bool) -> bool:
        """Send the knob to an option; say whether it has somewhere to travel."""
        index = max(0, min(len(self.words) - 1, index))
        if index == self.selected:
            return False
        self.origin = self.position(now)
        self.selected = index
        self.set_off = now
        self.moving = not instant
        if instant:
            self.origin = float(index)
        return self.moving

    def arrive(self, now: float) -> bool:
        """Stop the knob if it has arrived; say whether this was its last frame."""
        if self.moving and self.position(now) == float(self.selected):
            self.moving = False
            self.origin = float(self.selected)
            return True
        return False


def draw_switch(canvas: Canvas, theme: Theme, y: int, x: int, position: float, groove: str) -> None:
    """Draw a switch as a short thin rail: lit up to the knob when on, the knob at the start of a groove when off.

    It is the rail every panel uses, drawn the same way, with its round knob. The position is the clock's, so a slow
    terminal drops frames instead of slowing the knob.

    Args:
        canvas: Where to draw.
        theme: The palette; the rail is drawn on its raised surface.
        y: The row.
        x: The column of the rail's first cell.
        position: Where the knob is, from 0 (off) to 1 (on); a fraction while it travels.
        groove: The colour of the empty stretch.
    """
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
