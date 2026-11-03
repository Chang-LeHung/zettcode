"""The page ``/context`` opens: how full the window is, and where the tokens in it went."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from zettcode.sdk.types import ContextReport
from zettcode.tui import SEPARATOR, KeyEvent, MouseAction, MouseEvent, Style, Widget
from zettcode.tui.render import blend, display_width

from ..labels import compact_path
from . import context_charts as charts
from .effort_page import heat_colour

#: Rows above the body: a blank, the title, and the file the session is stored in.
HEAD_ROWS = 3

#: How far a mouse-wheel notch moves the body.
WHEEL_ROWS = 3

#: How far ← and → move the share the window is compacted at: five percent a press, to a multiple of five.
PERCENT_STEP = 5
PERCENT_LEAST = 1

#: Seconds the knob takes to travel to the share it was sent to; the same as the other panels' knobs.
SLIDE_SECONDS = 0.42

#: The columns the label before the rail takes, the most the rail is drawn across, and the least.
LABEL_WIDTH = 13
RAIL_MAX = 72
RAIL_MIN = 10

#: Columns kept beside the number for what the share was, when the rail has room to spare for it.
NOTE_WIDTH = 10

#: Characters of the rail: the lit stretch, the groove ahead, the knob, and the mark where it began.
LIT, GROOVE, KNOB, ORIGIN = "\u2501", "\u2500", "\u25cf", "\u2506"


class ContextPage(Widget):
    """A full-screen page that shows what the next request is made of.

    Shape::

        Context  Opus 5                              <- title and model
        ~/.zettcode/sessions/…/conversation.jsonl    <- where this session is stored
        Window   17,926 / 200,000 tokens   9.0% full
        ██▌░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                                            ▲ compacts at 160,000 tokens (80.0%)
        Used               17,926    9.0%
        Until compaction  142,074   71.0%
        Free in window    182,074   91.0%

        Where it goes   how the 17,926 tokens divide between sources
        ██████████████████████████▓▓▓▓▓▒▒▒░                  <- the sources, side by side
          Source               Tokens   Share  Items
        ■ System prompt         2,700   15.1%      1
        …
        esc back

    The gauge answers how full the window is and warms as the request nears the point where it
    is compacted, so a reader sees the trouble coming rather than the number. The bar and the rows
    under it answer a different question, where the tokens went, and divide the request rather than
    the window: a source is a share of the request and not of the model. The two ratios are never
    drawn on one scale. The total is the provider's whenever it reported one; the local count only
    supplies the proportions, so the rows add up to it exactly.

    The page paints on every frame from the lines the chart module describes, so a resize costs
    nothing but a repaint, and a terminal too short for all of it scrolls.

    When it is given the share the window is compacted at, a row above the keys shows it as a rail with
    a knob, and ← → slide the knob by five percent (a click on the rail sends it there):
    the rail runs through the theme's colours from calm to hot, the knob is a single dot that slides along it,
    and the mark under the gauge glides with it, from the clock and not from a frame count. Nothing is
    written until Enter, and Escape leaves the model as it was.
    """

    def __init__(
        self,
        report: ContextReport,
        *,
        path: Path | None = None,
        model: str = "",
        trigger: int | None = None,
        compact_percent: float | None = None,
        on_apply: Callable[[float], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Hold the report to draw.

        Args:
            report: Breakdown to show, as produced by the context extension.
            path: File this session is stored in. The home directory collapses to ``~``; a line
                too long for the page is cut at the edge, so a narrow terminal loses the end of
                the path and not which file it named.
            model: The model the window belongs to, shown beside the title.
            trigger: Tokens at which a request is compacted; the gauge marks it. ``None`` for a
                model that is never compacted.
            compact_percent: The share of the window at which a request is compacted, to be moved with ← →.
                ``None`` leaves the page a read-only report, and the mark is drawn at ``trigger``.
            on_apply: Receives the share when Enter is pressed on one that was moved; it owns closing the page.
            on_cancel: Called on Escape instead of the page popping itself, for an owner that
                keeps its own screen stack.
        """
        super().__init__()
        self.report = report
        self.path = compact_path(path, limit=None) if path is not None else ""
        self.model = model
        self.trigger = trigger
        self.start_percent = compact_percent
        self.percent = compact_percent
        #: Where the knob set off from, when it set off, and whether it is still on its way.
        self._origin = compact_percent
        self._set_off = 0.0
        self._moving = False
        self._token = f"context-panel:{id(self)}"
        #: Where the rail was drawn last (left column, row, width), for a click to land on.
        self._rail: tuple[int, int, int] | None = None
        self.on_apply = on_apply
        self.on_cancel = on_cancel
        self.offset = 0
        self._body_rows = 0

    @property
    def focusable(self) -> bool:
        """Take the keyboard when the page opens, so its keys work without a click."""
        return True

    @property
    def title(self) -> str:
        """Return the heading: the page's name and how much of the window the request fills."""
        return f"Context  {self.report.used:,} / {self.report.window:,} tokens"

    def lines(self, width: int) -> list[charts.Line]:
        """Return the body at ``width`` columns."""
        return charts.context_lines(self.report, self._trigger(), width)

    def _trigger(self) -> int | None:
        """Return the tokens a request is compacted at: where the knob is now, else the point given."""
        if self.percent is None or not self.report.window:
            return self.trigger
        return max(1, round(self.report.window * self.knob_at(self._now()) / 100))

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def knob_at(self, now: float) -> float:
        """Return the share the knob is at, which is between where it set off and where it is going while it travels."""
        assert self.percent is not None
        if not self._moving or self._origin is None:
            return self.percent
        progress = (now - self._set_off) / SLIDE_SECONDS
        if progress >= 1.0:
            return self.percent
        eased = 1 - (1 - max(0.0, progress)) ** 3
        return self._origin + (self.percent - self._origin) * eased

    def _slide_to(self, share: float) -> None:
        """Send the knob to a share, from wherever it is now; with reduced motion it is simply there."""
        assert self.percent is not None
        share = float(min(100, max(PERCENT_LEAST, share)))
        if share == self.percent:
            return
        now = self._now()
        self._origin = self.knob_at(now)
        self.percent = share
        self._set_off = now
        if self.app is not None and self.app.reduced_motion:
            self._moving = False
            self._origin = share
            return
        self._moving = True
        if self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_tick(self) -> bool:
        """Hand the frame loop back once the knob has arrived; say whether the picture is still changing."""
        if not self._moving:
            return False
        if self._now() - self._set_off >= SLIDE_SECONDS:
            self._moving = False
            self._origin = self.percent
            if self.app is not None:
                self.app.scheduler.animate(self._token, active=False)
        return True

    def on_unmount(self) -> None:
        """Release the frame loop, so a page put away mid-slide stops costing frames."""
        self._moving = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    @property
    def adjustable(self) -> bool:
        """Return whether the share can be moved here."""
        return self.percent is not None and self.on_apply is not None

    @property
    def changed(self) -> bool:
        """Return whether the share is anywhere but where it started."""
        return self.percent != self.start_percent

    def _move_percent(self, direction: int) -> None:
        """Move the share to the next multiple of five in ``direction``, and never off 1 to 100."""
        assert self.percent is not None
        if direction > 0:
            moved = math.floor(self.percent / PERCENT_STEP + 1) * PERCENT_STEP
        else:
            moved = (math.ceil(self.percent / PERCENT_STEP) - 1) * PERCENT_STEP
        self._slide_to(moved)

    # -- input --------------------------------------------------------------
    def close(self) -> None:
        """Leave the page: through the owner's callback when it gave one, else by popping itself."""
        if self.on_cancel is not None:
            self.on_cancel()
        elif self.app is not None and self.app.screens.top.widget is self:
            self.app.pop_screen()
            self.app.request_layout()

    def capture_event(self, event, host) -> bool:
        """Close on Escape before anything else can take the key."""
        if isinstance(event, KeyEvent) and event.key == "escape":
            self.close()
            return True
        return False

    def handle(self, event, host) -> bool:
        """Scroll the body, or close on ``q``."""
        if isinstance(event, MouseEvent):
            if event.action is MouseAction.SCROLL_UP:
                self._scroll(-WHEEL_ROWS)
            elif event.action is MouseAction.SCROLL_DOWN:
                self._scroll(WHEEL_ROWS)
            elif event.action is MouseAction.DOWN and self._rail is not None and self.adjustable:
                left, row, width = self._rail
                if event.y != row or not left <= event.x < left + width:
                    return False
                self._slide_to(round((event.x - left) / max(1, width - 1) * 100))
            else:
                return False
            host.invalidate()
            return True
        key = self._key_of(event)
        if self.adjustable and key in ("left", "right", "enter"):
            if key == "enter":
                if self.changed:
                    assert self.percent is not None and self.on_apply is not None
                    self.on_apply(self.percent)
            else:
                self._move_percent(-1 if key == "left" else 1)
            host.invalidate()
            return True
        if key in ("up", "k"):
            self._scroll(-1)
        elif key in ("down", "j"):
            self._scroll(1)
        elif key == "page_up":
            self._scroll(-max(1, self._body_rows - 1))
        elif key == "page_down":
            self._scroll(max(1, self._body_rows - 1))
        elif key == "home":
            self.offset = 0
        elif key == "end":
            self._scroll(10**9)
        elif key == "q":
            self.close()
        else:
            return False
        host.invalidate()
        return True

    @staticmethod
    def _key_of(event: object) -> str | None:
        """Return the key an event names, whether it came as a key or as typed text."""
        if isinstance(event, KeyEvent):
            return None if event.alt or event.control else event.key
        text = getattr(event, "text", None)
        return text if isinstance(text, str) and len(text) == 1 else None

    def _scroll(self, rows: int) -> None:
        """Move the body, never past its first row or its last."""
        furthest = max(0, len(self.lines(max(1, self.rect.width - 4))) - self._body_rows)
        self.offset = min(max(0, self.offset + rows), furthest)

    # -- painting -----------------------------------------------------------
    def style_of(self, role: str) -> Style:
        """Return how a role is painted in the active theme.

        Each source has a colour of its own, taken from the hues the theme already gives the tool
        families, so every palette has seven that are told apart without this page asking for any.
        """
        theme = self.theme
        page = theme.surface_alt
        tools = theme.tools
        colours = {
            "text": theme.text,
            "heading": theme.text,
            "muted": theme.muted,
            "track": blend(page, theme.text, 0.18),
            "gauge_calm": theme.accent,
            "gauge_warm": theme.warning,
            "gauge_hot": theme.error,
            "source0": tools.read,
            "source1": tools.subagent,
            "source2": tools.message,
            "source3": theme.accent,
            "source4": tools.write,
            "source5": theme.warning,
            "source6": theme.subtle,
        }
        return Style(foreground=colours.get(role, theme.text), background=page, bold=role == "heading")

    def render(self, canvas) -> None:
        """Fill the page, then draw the title, the file, the body, and the footer."""
        if self.rect.empty:
            return
        theme = self.theme
        rect = self.rect
        canvas.fill(rect.x, rect.y, rect.width, rect.height, Style(background=theme.surface_alt))
        room = max(0, rect.width - 4)
        used = canvas.draw_text(rect.x + 2, rect.y + 1, "Context", self.style_of("heading"), max_width=room)
        if self.model:
            canvas.draw_text(
                rect.x + 2 + used + 2, rect.y + 1, self.model, self.style_of("muted"), max_width=max(0, room - used - 2)
            )
        if self.path:
            canvas.draw_text(rect.x + 2, rect.y + 2, self.path, self.style_of("muted"), max_width=room)
        body = self.lines(room)
        top = rect.y + HEAD_ROWS + 1
        control = self.adjustable
        self._body_rows = max(0, rect.bottom - 2 - top - (1 if control else 0))
        self.offset = min(self.offset, max(0, len(body) - self._body_rows))
        for row, line in enumerate(body[self.offset : self.offset + self._body_rows]):
            self._draw(canvas, rect.x + 2, top + row, line, room)
        keys = "\u2191\u2193 scroll" if len(body) > self._body_rows else ""
        if control:
            self._draw_control(canvas, rect.x + 2, rect.bottom - 2, room)
            keys = f" {SEPARATOR} ".join(part for part in (keys, "\u2190 \u2192 compress at", "enter apply") if part)
        hint = f" {SEPARATOR} ".join(part for part in (keys, "esc back") if part)
        canvas.draw_text(rect.x + 2, rect.bottom - 1, hint, self.style_of("muted"), max_width=room)

    def _draw_control(self, canvas, x: int, y: int, room: int) -> None:
        """Draw the share the window is compacted at as a rail with a knob, its value, and what it was until Enter.

        The rail is the theme's own ramp, calm to hot, drawn lit up to the knob and dimmed beyond it, so
        where the knob stands is told by colour as well as place. The knob is one dot on one cell, and nothing
        follows it: the rail is as wide as the page allows, so five percent is several cells of travel.
        """
        assert self.percent is not None and self.start_percent is not None
        theme = self.theme
        surface = theme.surface_alt
        now = self._now()
        shown = self.knob_at(now)
        # By the clock, not by the flag: the frame after the knob lands is drawn before the tick that clears it.
        travelling = self._moving and now - self._set_off < SLIDE_SECONDS
        canvas.draw_text(x, y, "Compress at", self.style_of("heading"), max_width=room)
        width = min(RAIL_MAX, room - LABEL_WIDTH - 6 - NOTE_WIDTH)
        if width < RAIL_MIN:
            width = min(RAIL_MAX, room - LABEL_WIDTH - 6)
        value = self._shown(self.percent) if not travelling else f"{round(shown)}"
        hue = heat_colour(theme, shown / 100)
        if width < RAIL_MIN:
            self._rail = None
            canvas.draw_text(
                x + LABEL_WIDTH,
                y,
                f"{value}%",
                Style(foreground=hue, background=surface, bold=True),
                max_width=max(0, room - LABEL_WIDTH),
            )
            return
        left = x + LABEL_WIDTH
        self._rail = (left, y, width)
        last = width - 1
        # One knob on one cell, and nothing trailing it: the rail is wide enough that five percent is several cells,
        # and the colour of the knob and of the number follows the position exactly, so the glide reads as one move.
        knob = round(shown / 100 * last)
        glow = blend(hue, theme.text, 0.35)
        for cell in range(width):
            base = heat_colour(theme, cell / last)
            if cell == knob:
                canvas.draw_text(left + cell, y, KNOB, Style(foreground=glow, background=surface, bold=True))
                continue
            colour, glyph = (base, LIT) if cell < knob else (blend(base, surface, 0.5), GROOVE)
            canvas.draw_text(left + cell, y, glyph, Style(foreground=colour, background=surface))
        began = round(self.start_percent / 100 * last)
        if self.changed and began != knob:
            canvas.draw_text(left + began, y, ORIGIN, Style(foreground=theme.muted, background=surface, bold=True))
        after = left + width + 1
        number = f"{value}%"
        canvas.draw_text(after, y, number, Style(foreground=hue, background=surface, bold=True), max_width=5)
        beyond = after + max(4, display_width(number)) + 2
        note = f"was {self._shown(self.start_percent)}%" if self.changed else ""
        if note and x + room - beyond >= display_width(note):
            canvas.draw_text(
                beyond,
                y,
                note,
                Style(foreground=theme.accent if self.changed else theme.muted, background=surface),
                max_width=x + room - beyond,
            )

    @staticmethod
    def _shown(percent: float) -> str:
        """Return a share without a pointless decimal: ``80`` for 80.0, ``82.5`` as it is."""
        return f"{percent:g}"

    def _draw(self, canvas, x: int, y: int, line: charts.Line, room: int) -> None:
        """Draw one line of roles from ``x``, stopping at the edge of the page."""
        used = 0
        for text, role in line:
            if used >= room:
                break
            used += canvas.draw_text(x + used, y, text, self.style_of(role), max_width=room - used)
