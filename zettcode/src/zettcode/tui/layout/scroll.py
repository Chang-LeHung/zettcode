"""A virtualized scrollable window over a line source."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import replace
from time import monotonic

from ..core.events import KeyEvent, MouseAction, MouseEvent
from ..core.geometry import Constraints, Size
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, TextLine
from ..render.text import display_width, slice_columns

#: Rows one wheel event scrolls. One event is one row however fast they come, which is how Codex does it:
#: a mouse wheel's notch is one row, a trackpad that sends sixty events a second scrolls sixty rows a
#: second, and nothing grows with how long the wheel has been turning. The reader who wants it faster
#: says so (``ScrollView(wheel_speed=...)``, ``transcript.mouse_scroll_speed`` in the configuration)
#: instead of the view guessing from how hard they flicked. An earlier version did guess — a turn that
#: went on gained a row a notch, to ten — and a trackpad's momentum then threw the view across several
#: pages in one flick.
WHEEL_SPEED = 1.0

#: The most a single frame may move the view by the wheel, as a share of the window: half. Events that
#: pile up (a terminal that was busy, a flick delivered in one burst) are applied together and drawn
#: once, so without a bound the rows between where the view was and where it ends up are never drawn at
#: all, which reads as content that was skipped. Half a window always leaves half of what was on screen
#: still there to follow.
WHEEL_FRAME_SHARE = 0.5


class LineSource(ABC):
    """Supplies already-wrapped lines without materializing the whole list.

    ``count`` must be cheap, because it runs on every frame, and ``line`` is
    only ever called for rows that are actually visible. Subclass this and
    answer both; a class that merely looks compatible does not count.
    """

    @abstractmethod
    def count(self, width: int) -> int:
        """Return the total number of lines at ``width``; this runs every frame."""

    @abstractmethod
    def line(self, index: int, width: int) -> TextLine:
        """Return one line; only indexes that are actually visible are requested."""


class StaticLines(LineSource):
    """A LineSource over a fixed sequence of lines."""

    def __init__(self, lines: Sequence[TextLine] = ()) -> None:
        """Freeze an already-wrapped sequence of lines."""
        self.lines = tuple(lines)

    def count(self, width: int) -> int:
        """Return the number of stored lines; the width is ignored."""
        return len(self.lines)

    def line(self, index: int, width: int) -> TextLine:
        """Return one stored line; the width is already baked in."""
        return self.lines[index]


class ScrollView(Widget):
    """Show a window of a LineSource and keep scrolling anchored.

    ``top`` is an absolute line index rather than a distance from the bottom,
    so appending content never moves the view while the reader is scrolled up.
    Call :meth:`adjust_for_insertion` when lines are inserted above the window
    to keep the same content on screen.

    Shape::

        line 01                           <- row 0 of the window (top = 0 here)
        line 02
        line 03                           <- only rect.height lines are asked for
        line 04
        ------
        ^ the source is never materialised: count(width) then line(i, width)

    ``measure`` claims nothing, because the window size comes from the slot it
    is placed in, not from its contents. With ``selectable`` a drag inverts the
    covered cells and copies them on release.
    """

    def __init__(
        self,
        source: LineSource,
        *,
        follow_tail: bool = True,
        focusable: bool = False,
        selectable: bool = False,
        clock: Callable[[], float] = monotonic,
        double_click_seconds: float = 0.4,
        wheel_speed: float = WHEEL_SPEED,
    ) -> None:
        """Configure the window, the tail behavior, and the selection state.

        Args:
            source: Supplies already-wrapped lines; only visible indexes are read.
            follow_tail: Stick to the newest line until the reader scrolls up.
            focusable: Let Tab traversal land on the view so its keys work.
            selectable: Enable mouse selection and copying.
            clock: Time source used to detect double clicks.
            double_click_seconds: Window in which two clicks on one line count as
                a double click, which selects the whole line.
            wheel_speed: Rows one wheel event scrolls; a fraction is carried to the next event, so
                ``0.5`` is a row every second event. Not positive or not finite is the default.
        """
        super().__init__()
        self.source = source
        self.follow_tail = follow_tail
        self.top = 0
        self._focusable = focusable
        self.selectable = selectable
        self.clock = clock
        self.double_click_seconds = double_click_seconds
        self._selection_start: tuple[int, int] | None = None
        self._selection_end: tuple[int, int] | None = None
        self._dragging = False
        self._mouse_down: tuple[int, int] | None = None
        self._mouse_down_at = float("-inf")
        self._double_click = False
        self._last_click_at = float("-inf")
        self._last_click_line: int | None = None
        self.wheel_speed = wheel_speed if math.isfinite(wheel_speed) and wheel_speed > 0 else WHEEL_SPEED
        self._wheel_owed = 0.0
        self._frame_start: int | None = None

    @property
    def focusable(self) -> bool:
        """Report whether Tab traversal may land on this view."""
        return self._focusable

    @property
    def selects_text(self) -> bool:
        """Keep the drag: this view selects its own lines rather than the frame."""
        return self.selectable

    @property
    def line_width(self) -> int:
        """Return the width lines are wrapped to, never below one column."""
        return max(1, self.rect.width)

    def measure(self, constraints: Constraints) -> Size:
        """Claim no preferred size; the parent decides the viewport."""
        return constraints.constrain(Size(0, 0))

    def render(self, canvas: Canvas) -> None:
        """Clamp the window first, then paint the visible rows and selection."""
        count = self.line_count()
        wanted = count - self.rect.height if self.follow_tail else self.top
        self.top = self._clamp(wanted, count)
        self._frame_start = None  # the next frame measures how far the wheel has moved from here
        for row in range(self.rect.height):
            index = self.top + row
            if index >= count:
                break
            line = self.source.line(index, self.line_width)
            canvas.draw_spans(self.rect.x, self.rect.y + row, line.spans, max_width=self.rect.width)
            self._paint_selection(canvas, row, index, line)

    def handle(self, event, host: Host) -> bool:
        """Scroll with the wheel or keys, running selection when enabled."""
        if isinstance(event, MouseEvent) and self.selectable:
            return self._handle_pointer(event, host)
        if isinstance(event, MouseEvent) and self.rect.contains(event.x, event.y):
            if event.action is MouseAction.SCROLL_UP:
                self._wheel(-1)
                return True
            if event.action is MouseAction.SCROLL_DOWN:
                self._wheel(1)
                return True
            return False
        if not isinstance(event, KeyEvent) or host.focused_widget() is not self:
            return False
        page = max(1, self.rect.height - 1)
        match event.key:
            case "up":
                self.scroll_by(-1)
            case "down":
                self.scroll_by(1)
            case "page_up":
                self.scroll_by(-page)
            case "page_down":
                self.scroll_by(page)
            case "home" | "ctrl_home":
                self.scroll_to(0)
            case "end" | "ctrl_end":
                self.scroll_end()
            case _:
                return False
        return True

    def selection_bounds(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """Return the sorted selection corners, or None when nothing is selected."""
        if self._selection_start is None or self._selection_end is None:
            return None
        start, end = sorted((self._selection_start, self._selection_end))
        return None if start == end else (start, end)

    def has_selection(self) -> bool:
        """Return whether a selection still names a line in the current source.

        A transcript can shrink while a selection is held: an entry may be
        completed or removed while the reader has rows selected. That makes the
        old line numbers stale, and asking for their text used to raise. Here a
        stale selection is dropped instead of being allowed to answer Escape.
        """
        bounds = self.selection_bounds()
        if bounds is None:
            return False
        count = max(0, self.line_count())
        if count == 0 or bounds[0][0] >= count or bounds[1][0] >= count:
            self.clear_selection()
            return False
        return True

    def selected_text(self) -> str:
        """Return the text the current selection covers, clamped to the source."""
        bounds = self.selection_bounds()
        if bounds is None:
            return ""
        count = max(0, self.line_count())
        if count == 0:
            self.clear_selection()
            return ""
        (first, first_column), (last, last_column) = bounds
        if first >= count:
            self.clear_selection()
            return ""
        last = min(last, count - 1)
        lines: list[str] = []
        for index in range(first, last + 1):
            text = self.source.line(index, self.line_width).text
            left = first_column if index == first else 0
            right = last_column if index == last else display_width(text)
            lines.append(slice_columns(text, left, right))
        return "\n".join(lines)

    def clear_selection(self) -> None:
        """Drop both selection corners."""
        self._selection_start = None
        self._selection_end = None

    def _handle_pointer(self, event: MouseEvent, host: Host) -> bool:
        """Implement click, drag, and double-click selection for the mouse."""
        inside = self.rect.contains(event.x, event.y)
        if event.action is MouseAction.SCROLL_UP and inside:
            self._wheel(-1)
            return True
        if event.action is MouseAction.SCROLL_DOWN and inside:
            self._wheel(1)
            return True
        if event.action is MouseAction.DOWN and inside:
            point = self._point(event.x, event.y)
            now = self.clock()
            self._double_click = (
                self._last_click_line == point[0] and now - self._last_click_at <= self.double_click_seconds
            )
            self._mouse_down = point
            self._mouse_down_at = now
            if self._double_click:
                self._select_line(point[0])
                self._dragging = False
            else:
                if not event.shift or self._selection_start is None:
                    self._selection_start = point
                self._selection_end = point
                self._dragging = True
            return True
        if event.action is MouseAction.MOVE and (self._dragging or self._double_click):
            # A double click that keeps moving is a drag: the second press
            # selected the whole line, and carrying on from there extends it
            # instead of leaving the reader stuck with that one row.
            self._double_click = False
            self._dragging = True
            if event.y < self.rect.y:
                self.scroll_by(-1)
            elif event.y >= self.rect.y + self.rect.height:
                self.scroll_by(1)
            self._selection_end = self._point_clamped(event.x, event.y)
            return True
        if event.action is MouseAction.UP and (self._dragging or self._double_click):
            finish_double_click = self._double_click
            self._double_click = False
            if self._dragging:
                self._dragging = False
                if inside:
                    self._selection_end = self._point(event.x, event.y)
                clicked = inside and self._point(event.x, event.y) == self._mouse_down
                if clicked:
                    self._last_click_at = self._mouse_down_at
                    self._last_click_line = self._mouse_down[0] if self._mouse_down else None
                else:
                    self._last_click_at = float("-inf")
                    self._last_click_line = None
            if finish_double_click:
                self._last_click_at = float("-inf")
                self._last_click_line = None
            self._copy_selection(host)
            return True
        return False

    def _paint_selection(self, canvas: Canvas, row: int, index: int, line: TextLine) -> None:
        """Invert the cells the selection covers on one visible row."""
        bounds = self.selection_bounds()
        if bounds is None:
            return
        (first, first_column), (last, last_column) = bounds
        if not first <= index <= last:
            return
        start = first_column if index == first else 0
        end = last_column if index == last else display_width(line.text)
        if end > start:
            canvas.restyle(self.rect.x + start, self.rect.y + row, end - start, _invert)

    def _copy_selection(self, host: Host) -> None:
        """Hand the selected text to the host clipboard."""
        selected = self.selected_text()
        if selected:
            host.copy(selected)

    def _select_line(self, index: int) -> None:
        """Select a whole line, clamping the index to the buffer."""
        if self.line_count() == 0:
            return
        index = min(max(0, index), self.line_count() - 1)
        text = self.source.line(index, self.line_width).text
        self._selection_start = (index, 0)
        self._selection_end = (index, max(1, display_width(text)))

    def _point(self, x: int, y: int) -> tuple[int, int]:
        """Translate a screen cell into a clamped (line, column) point."""
        count = max(0, self.line_count())
        line = min(max(0, self.top + y - self.rect.y), max(0, count - 1))
        text = self.source.line(line, self.line_width).text if count else ""
        column = min(max(0, x - self.rect.x), display_width(text))
        return line, column

    def _point_clamped(self, x: int, y: int) -> tuple[int, int]:
        """Translate a point outside the viewport, as during a drag."""
        clamped_x = min(max(x, self.rect.x), max(self.rect.x, self.rect.x + self.rect.width - 1))
        clamped_y = min(max(y, self.rect.y), max(self.rect.y, self.rect.y + self.rect.height - 1))
        return self._point(clamped_x, clamped_y)

    def line_count(self) -> int:
        """Return how many lines the source reports at the current width."""
        return self.source.count(self.line_width)

    @property
    def max_top(self) -> int:
        """Return the largest ``top`` that still fills the viewport."""
        return max(0, self.line_count() - self.rect.height)

    def visible_range(self) -> tuple[int, int]:
        """Return the half-open range of line indexes currently on screen."""
        count = self.line_count()
        return self.top, min(count, self.top + self.rect.height)

    def scroll_to(self, index: int) -> None:
        """Jump so that index is the first visible line.

        Args:
            index: Absolute line index, clamped into the scrollable range. The
                tail is followed again only when the window reaches the end.
        """
        count = self.line_count()
        maximum = max(0, count - self.rect.height)
        self.top = min(max(0, index), maximum)
        self.follow_tail = maximum == 0 or self.top >= maximum

    def _wheel(self, direction: int) -> None:
        """Scroll one wheel event: :attr:`wheel_speed` rows, and never far enough in a frame to skip content.

        The fraction of a row a slow speed leaves over is carried to the next event, and dropped when the
        wheel turns the other way, so a reversal starts from a whole row.

        Args:
            direction: ``-1`` for up, ``1`` for down.
        """
        if self._wheel_owed * direction < 0:
            self._wheel_owed = 0.0
        self._wheel_owed += direction * self.wheel_speed
        rows = int(self._wheel_owed)
        # A speed such as 0.1 reaches a whole row after repeated addition only by a hair; round the hair off.
        if rows == 0 and abs(round(self._wheel_owed) - self._wheel_owed) < 1e-9 and round(self._wheel_owed) != 0:
            rows = int(round(self._wheel_owed))
        self._wheel_owed -= rows
        if rows == 0:
            return
        if self._frame_start is None:
            self._frame_start = self.top
        reach = max(1, int(self.rect.height * WHEEL_FRAME_SHARE))
        target = min(max(self.top + rows, self._frame_start - reach), self._frame_start + reach)
        self.scroll_to(target)

    def scroll_by(self, amount: int) -> None:
        """Move the window by a relative number of lines."""
        self.scroll_to(self.top + amount)

    def scroll_end(self) -> None:
        """Follow the tail again, so appended lines stay visible."""
        self.follow_tail = True

    def adjust_for_insertion(self, index: int, count: int = 1) -> None:
        """Keep the same content visible when lines are inserted above.

        Args:
            index: Line index where the inserted lines begin.
            count: How many lines were inserted there.
        """
        if index < self.top:
            self.top += count

    def _clamp(self, top: int, count: int) -> int:
        """Keep ``top`` inside the scrollable range."""
        return min(max(0, top), max(0, count - self.rect.height))


def _invert(style):
    """Flip reverse video, which is how a selection marks a cell."""
    return replace(style, reverse=not style.reverse)
