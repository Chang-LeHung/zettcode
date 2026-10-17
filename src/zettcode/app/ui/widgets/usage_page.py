"""The page ``/usage`` opens: where the tokens went, by model, by session, and by day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from zettcode.app.agent.storage.ledger import Ledger
from zettcode.tui import SEPARATOR, KeyEvent, MouseAction, MouseEvent, Style, Widget
from zettcode.tui.render import blend

from . import usage_charts as charts

#: The tabs, in the order Tab walks through them.
TABS = ("Models", "Sessions", "Calendar")

#: Rows above the body: a blank, the title, the tabs, and the totals.
HEAD_ROWS = 4

#: How far a mouse-wheel notch moves the body.
WHEEL_ROWS = 3

#: Shade of each calendar level, as how far it sits from the page colour towards the accent.
HEAT = (0.0, 0.32, 0.55, 0.78, 1.0)


class UsagePage(Widget):
    """A full-screen page with three views of one workspace's usage.

    Shape::

        Usage  ~/projects/api                       <- title and workspace
        Models  Sessions  Calendar                  <- tabs; the open one is filled
        All models   1.2B tokens   in ...           <- totals, on every tab
        <body>                                      <- scrolls
        tab switch · ↑↓ scroll · esc back           <- footer

    **Models** draws two bars for each model, **Sessions** one row for each session with its
    input and output, and **Calendar** a grid of weeks like the one GitHub draws for
    contributions: a column is a week, a square a day, and the shade is the day's tokens.
    On the calendar the arrow keys choose a day and the line under the grid says what it
    spent.

    The page is the whole screen, and paints on every frame from the lines the chart module
    describes, so a resize costs nothing but a repaint.
    """

    def __init__(
        self,
        ledger: Ledger,
        *,
        workspace: str = "",
        on_cancel: Callable[[], None] | None = None,
        today: date | None = None,
        tab: str = TABS[0],
    ) -> None:
        """Hold the ledger to draw and start on one tab.

        Args:
            ledger: What the workspace has spent.
            workspace: Shown beside the title, so the page says whose usage it is.
            on_cancel: Called on Escape instead of the page popping itself, for an owner that
                keeps its own screen stack; most callers leave it out.
            today: The last day the calendar draws; the real date when omitted.
            tab: Which tab opens first.
        """
        super().__init__()
        self.ledger = ledger
        self.workspace = workspace
        self.on_cancel = on_cancel
        self.today = today or date.today()
        self.tab = TABS.index(tab) if tab in TABS else 0
        self.selected = self.today
        self.offset = 0
        self._body_rows = 0

    @property
    def focusable(self) -> bool:
        """Take the keyboard when the page opens, so its keys work without a click."""
        return True

    @property
    def tab_name(self) -> str:
        """Return the name of the open tab."""
        return TABS[self.tab]

    # -- content ------------------------------------------------------------
    def lines(self, width: int) -> tuple[list[charts.Line], list[charts.Line]]:
        """Return the open tab's fixed heading lines and its scrolling body."""
        if self.tab_name == "Models":
            return charts.models_tab(self.ledger, width)
        if self.tab_name == "Sessions":
            return charts.sessions_tab(self.ledger, width)
        head, body, _, _ = charts.calendar_tab(self.ledger, width, self.today, self.selected)
        return head, body

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
        """Switch tabs, scroll the body, or move the day chosen on the calendar."""
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
        if key is None:
            return False
        if key in ("tab", "backtab"):
            self._open((self.tab + (1 if key == "tab" else -1)) % len(TABS))
        elif key in ("1", "2", "3"):
            self._open(int(key) - 1)
        elif self.tab_name == "Calendar" and key in ("left", "right", "up", "down", "home", "end"):
            self._move_day(key)
        elif key in ("left", "right"):
            self._open((self.tab + (1 if key == "right" else -1)) % len(TABS))
        elif key in ("up", "k"):
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

    def _open(self, tab: int) -> None:
        """Show another tab from its top."""
        self.tab = tab
        self.offset = 0

    def _scroll(self, rows: int) -> None:
        """Move the body, never past its first row or its last."""
        _, body = self.lines(max(1, self.rect.width - 4))
        furthest = max(0, len(body) - self._body_rows)
        self.offset = min(max(0, self.offset + rows), furthest)

    def _move_day(self, key: str) -> None:
        """Move the chosen calendar day: a day for up and down, a week for left and right."""
        step = {"left": -7, "right": 7, "up": -1, "down": 1}.get(key)
        earliest = charts.first_day(self.today, charts.weeks_that_fit(max(1, self.rect.width - 4)))
        if key == "home":
            self.selected = earliest
        elif key == "end":
            self.selected = self.today
        elif step is not None:
            self.selected = min(self.today, max(earliest, self.selected + timedelta(days=step)))

    # -- painting -----------------------------------------------------------
    def style_of(self, role: str) -> Style:
        """Return how a role is painted in the active theme."""
        theme = self.theme
        page = theme.surface_alt
        if role.startswith("heat"):
            chosen = role.endswith("*")
            level = int(role.removeprefix("heat").removesuffix("*"))
            if level == 0:
                colour = blend(page, theme.text, 0.14)
            else:
                colour = blend(page, theme.accent, HEAT[level])
            return Style(foreground=colour, background=theme.selection if chosen else page, bold=chosen)
        colours = {
            "text": theme.text,
            "heading": theme.text,
            "muted": theme.muted,
            "input": theme.accent,
            "output": theme.warning,
            "track": blend(page, theme.text, 0.18),
        }
        return Style(foreground=colours.get(role, theme.text), background=page, bold=role == "heading")

    def render(self, canvas) -> None:
        """Fill the page, then draw the title, the tabs, the totals, the body, and the footer."""
        if self.rect.empty:
            return
        theme = self.theme
        rect = self.rect
        page = Style(background=theme.surface_alt)
        canvas.fill(rect.x, rect.y, rect.width, rect.height, page)
        room = max(0, rect.width - 4)
        canvas.draw_text(rect.x + 2, rect.y + 1, "Usage", self.style_of("heading"), max_width=room)
        canvas.draw_text(rect.x + 9, rect.y + 1, self.workspace, self.style_of("muted"), max_width=max(0, room - 7))
        column = rect.x + 2
        for index, name in enumerate(TABS):
            label = f" {name} "
            style = (
                Style(foreground=theme.surface_alt, background=theme.accent, bold=True)
                if index == self.tab
                else self.style_of("muted")
            )
            column += canvas.draw_text(column, rect.y + 2, label, style) + 1
        head, body = self.lines(room)
        for row, line in enumerate(head):
            self._draw(canvas, rect.x + 2, rect.y + 3 + row, line, room)
        top = rect.y + 3 + len(head) + 1
        self._body_rows = max(0, rect.bottom - 2 - top)
        self.offset = min(self.offset, max(0, len(body) - self._body_rows))
        for row, line in enumerate(body[self.offset : self.offset + self._body_rows]):
            self._draw(canvas, rect.x + 2, top + row, line, room)
        if self.tab_name == "Calendar":
            keys = "arrows choose a day"
        else:
            keys = "\u2191\u2193 scroll" if len(body) > self._body_rows else ""
        hint = f" {SEPARATOR} ".join(part for part in ("tab switch", keys, "esc back") if part)
        canvas.draw_text(rect.x + 2, rect.bottom - 1, hint, self.style_of("muted"), max_width=room)

    def _draw(self, canvas, x: int, y: int, line: charts.Line, room: int) -> None:
        """Draw one line of roles from ``x``, stopping at the edge of the page."""
        used = 0
        for text, role in line:
            if used >= room:
                break
            used += canvas.draw_text(x + used, y, text, self.style_of(role), max_width=room - used)
