"""The page ``/context`` opens: how full the window is, and where the tokens in it went."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from zettcode.app.agent.extensions.context import ContextReport
from zettcode.tui import SEPARATOR, KeyEvent, MouseAction, MouseEvent, Style, Widget
from zettcode.tui.render import blend

from ..labels import compact_path
from . import context_charts as charts

#: Rows above the body: a blank, the title, and the file the session is stored in.
HEAD_ROWS = 3

#: How far a mouse-wheel notch moves the body.
WHEEL_ROWS = 3


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
    """

    def __init__(
        self,
        report: ContextReport,
        *,
        path: Path | None = None,
        model: str = "",
        trigger: int | None = None,
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
            on_cancel: Called on Escape instead of the page popping itself, for an owner that
                keeps its own screen stack.
        """
        super().__init__()
        self.report = report
        self.path = compact_path(path, limit=None) if path is not None else ""
        self.model = model
        self.trigger = trigger
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
        return charts.context_lines(self.report, self.trigger, width)

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
            else:
                return False
            host.invalidate()
            return True
        key = self._key_of(event)
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
        self._body_rows = max(0, rect.bottom - 2 - top)
        self.offset = min(self.offset, max(0, len(body) - self._body_rows))
        for row, line in enumerate(body[self.offset : self.offset + self._body_rows]):
            self._draw(canvas, rect.x + 2, top + row, line, room)
        keys = "\u2191\u2193 scroll" if len(body) > self._body_rows else ""
        hint = f" {SEPARATOR} ".join(part for part in (keys, "esc back") if part)
        canvas.draw_text(rect.x + 2, rect.bottom - 1, hint, self.style_of("muted"), max_width=room)

    def _draw(self, canvas, x: int, y: int, line: charts.Line, room: int) -> None:
        """Draw one line of roles from ``x``, stopping at the edge of the page."""
        used = 0
        for text, role in line:
            if used >= room:
                break
            used += canvas.draw_text(x + used, y, text, self.style_of(role), max_width=room - used)
