"""A full-screen command line: the output of what was run, and a line to type the next command on.

The widget is only the screen. It does not start a process or know what a command is: the owner is told what was
typed (``on_submit``), writes whatever the command prints (:meth:`ConsolePanel.write`, which understands colours and
carriage returns) and says when it is running and when it has finished. That is what lets the same panel show a
shell, a build, or a log tail, and what keeps the framework free of the application.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from ..core.events import KeyEvent, MouseAction, MouseEvent
from ..core.geometry import Point, Rect
from ..core.host import Host
from ..core.theme import Theme
from ..core.widget import Widget
from ..glyphs import RULE, SEPARATOR
from ..render import Canvas, Span, Style
from ..render.ansi import AnsiBuffer
from ..render.text import ELLIPSIS, character_width, display_width
from .completion import Completer
from .textarea import TextArea

#: Rows one notch of the wheel moves the output.
WHEEL_ROWS = 3

#: Columns of margin on each side of the output and the input line.
MARGIN = 2

#: Most rows the input line grows to when a long command wraps.
INPUT_ROWS = 3

#: What a candidate can be, as the owner's completer says in ``CompletionItem.type``. The strip of candidates
#: paints each kind in a colour of its own, as ``ls`` does, so a directory is told from a file before it is chosen.
DIRECTORY = "directory"
EXECUTABLE = "executable"
SYMLINK = "symlink"
COMMAND = "command"
FILE = "file"
REFERENCE = "reference"
ARGUMENT = "argument"


def keep_tail(text: str, width: int) -> str:
    """Return ``text`` cut from the left to fit ``width`` columns, an ellipsis where it was cut.

    For a path: the end of it is what says where you are, and the start is the part that every path shares.
    """
    if display_width(text) <= width:
        return text
    if width <= 1:
        return ELLIPSIS[:width]
    kept, used = "", 0
    for character in reversed(text):
        columns = character_width(character)
        if used + columns > width - 1:
            break
        kept, used = character + kept, used + columns
    return ELLIPSIS + kept


def kind_colour(kind: str, theme: Theme) -> str:
    """Return the colour a candidate of this kind is painted in.

    The hues are the palette's own, so they follow the theme: directories take the lavender the palettes use for
    what the agent reads, programs and executables the accent, links the teal, a branch or tag the orange of what is
    written, and a plain file or a word taken from the history the quiet body colour. A kind nobody named is a
    plain file.
    """
    if kind == DIRECTORY:
        return theme.tools.read
    if kind in (EXECUTABLE, COMMAND):
        return theme.accent
    if kind == SYMLINK:
        return theme.tools.subagent
    if kind == REFERENCE:
        return theme.tools.write
    return theme.subtle


class ConsolePanel(Widget):
    """Show a scrolling output with a line to type commands on.

    Shape::

        Shell  ~/projects/api                          exit 0 · 1.2s   <- title, location, outcome
        $ pytest -q                                                    <- what was typed
        ......                                                         <- what it printed
        6 passed in 0.24s
        ────────────────────────────────────────────────
        src/  tests/  README.md                                        <- candidates while Tab cycles
        $ git st_                                                      <- the line
        enter run · tab complete · ↑↓ history · esc close              <- keys

    The output follows the newest line until the reader scrolls up (the wheel, PageUp), and stays where it is
    while more arrives; typing, or PageDown to the end, follows again. The panel keeps at most ``max_lines`` lines.

    Args:
        title: The heading.
        location: Shown beside the title; the directory the commands run in.
        prompt: Drawn before the line to type on, and before each command echoed into the output.
        completer: Candidates for the word under the cursor when Tab is pressed.
        history: Earlier commands, oldest first, which Up and Ctrl-R walk through.
        max_lines: Lines of output kept.
        on_submit: Called with the command when Enter is pressed and nothing is running.
        on_interrupt: Called to stop the running command; returns whether there was one to stop.
        on_close: Called when the reader leaves the panel (Escape, or Ctrl-D on an empty line).
    """

    def __init__(
        self,
        *,
        title: str = "Shell",
        location: str = "",
        prompt: str = "$",
        completer: Completer | None = None,
        history: Sequence[str] = (),
        max_lines: int = 5000,
        on_submit: Callable[[str], None] | None = None,
        on_interrupt: Callable[[], bool] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self.location = location
        self.prompt = prompt
        self.on_submit = on_submit
        self.on_interrupt = on_interrupt
        self.on_close = on_close
        self.buffer = AnsiBuffer(max_lines)
        self.input = TextArea(
            prompt=f"{prompt} ",
            completer=completer,
            history_limit=max(200, len(history) + 200),
            on_submit=self._submit,
            on_change=self._typed,
            max_height=INPUT_ROWS,
        )
        self.input.remember(history)
        #: Rows the output is scrolled up from the newest line; zero follows it.
        self.offset = 0
        self.status = ""
        self._running = False
        self._started_at = 0.0
        self._shown_seconds = -1
        self._output_rows = 0

    # -- what the owner drives ---------------------------------------------
    @property
    def running(self) -> bool:
        """Return whether a command is running."""
        return self._running

    @property
    def children(self) -> Sequence[Widget]:
        """Return the line the commands are typed on."""
        return (self.input,)

    def write(self, text: str, style: Style | None = None) -> None:
        """Append output, escape sequences and all; the view follows it unless the reader scrolled up."""
        started = self.buffer.write(text, style)
        if self.offset:
            self.offset += started
        self._changed()

    def begin(self) -> None:
        """Say that a command has started: the header counts the seconds until :meth:`finish`."""
        self._running = True
        self._started_at = self._now()
        self._shown_seconds = -1
        self.status = ""
        self._changed()

    def finish(self, status: str) -> None:
        """Say that the command ended, and how (``"exit 0 · 1.2s"``)."""
        self._running = False
        self.status = status
        self._changed()

    def clear(self) -> None:
        """Forget the output."""
        self.buffer.clear()
        self.offset = 0
        self._changed()

    def echo(self, command: str) -> None:
        """Write the command as the reader typed it, after the prompt, so the output reads as a session."""
        self.write(f"{self.prompt} {command}\n", Style(bold=True))

    def set_location(self, location: str) -> None:
        """Change the directory shown beside the title."""
        self.location = location
        self._changed()

    def close(self) -> None:
        """Leave the panel."""
        if self.on_close is not None:
            self.on_close()
        elif self.app is not None and self.app.screens.top.widget is self:
            self.app.pop_screen()
            self.app.request_layout()

    def interrupt(self) -> bool:
        """Stop the running command, if there is one; otherwise let Ctrl-C do what it does on any page."""
        if not self._running or self.on_interrupt is None:
            return False
        return self.on_interrupt()

    # -- the line -----------------------------------------------------------
    def _submit(self, command: str) -> bool | None:
        """Take a command from the line, or refuse it while another is running (the draft stays)."""
        if self._running:
            return False
        self.offset = 0
        if self.on_submit is not None:
            self.on_submit(command)
        return None

    def _typed(self) -> None:
        """Follow the newest output once the reader starts typing."""
        self.offset = 0
        self._changed()

    # -- events -------------------------------------------------------------
    def capture_event(self, event, host: Host) -> bool:
        """Escape stops a running command, or else leaves; Ctrl-D on an empty line leaves, as it ends a shell."""
        if not isinstance(event, KeyEvent):
            return False
        if event.key == "escape":
            if not self.interrupt():
                self.close()
            host.invalidate()
            return True
        if event.key == "ctrl_d" and not self.input.text and not self._running:
            self.close()
            return True
        return False

    def bubble_event(self, event, host: Host) -> bool:
        """Scroll with the keys the line does not use, and with the wheel over the line."""
        return self.handle(event, host)

    def handle(self, event, host: Host) -> bool:
        """Scroll the output: the wheel, PageUp and PageDown."""
        if isinstance(event, MouseEvent):
            if event.action is MouseAction.SCROLL_UP:
                self._scroll(WHEEL_ROWS)
            elif event.action is MouseAction.SCROLL_DOWN:
                self._scroll(-WHEEL_ROWS)
            else:
                return False
        elif isinstance(event, KeyEvent) and event.key in ("page_up", "page_down"):
            page = max(1, self._output_rows - 1)
            self._scroll(page if event.key == "page_up" else -page)
        else:
            return False
        host.invalidate()
        return True

    def _scroll(self, rows: int) -> None:
        """Move the view up (positive) or towards the newest line, never past either end."""
        self.offset = max(0, min(self.offset + rows, self._furthest()))

    def _furthest(self) -> int:
        """Return how far up the view can go: the rows of output beyond what the screen shows."""
        return max(0, self._total_rows(self._text_width()) - self._output_rows)

    # -- clock --------------------------------------------------------------
    def _now(self) -> float:
        return self.app.clock() if self.app is not None else 0.0

    def on_tick(self) -> bool:
        """Repaint each second while a command runs, for the header's counter."""
        if not self._running:
            return False
        seconds = int(self._now() - self._started_at)
        if seconds == self._shown_seconds:
            return False
        self._shown_seconds = seconds
        return True

    def _changed(self) -> None:
        if self.app is not None:
            self.app.invalidate()
        self.invalidate()

    # -- geometry -----------------------------------------------------------
    def _text_width(self) -> int:
        return max(1, self.rect.width - 2 * MARGIN)

    def _lines(self) -> list:
        """Return the lines to show: the newest is left out while it is still empty, so no blank row trails."""
        lines = self.buffer.lines
        return lines[:-1] if lines and not lines[-1].chars else lines

    def _total_rows(self, width: int) -> int:
        return sum(len(line.rows(width)) for line in self._lines())

    def layout(self, rect: Rect) -> None:
        """Put the line to type on at the bottom, above the key hints."""
        super().layout(rect)
        width = self._text_width()
        height = min(INPUT_ROWS, self.input.preferred_height(width))
        top = rect.bottom - 1 - height
        self.input.layout(Rect(rect.x + MARGIN, top, width, height))

    # -- painting -----------------------------------------------------------
    def render(self, canvas: Canvas) -> None:
        """Paint the page, the visible output, the candidates and the keys, then the line."""
        rect = self.rect
        if rect.empty:
            return
        theme = self.theme
        page = Style(foreground=theme.text, background=theme.surface_alt)
        muted = replace(page, foreground=theme.muted)
        canvas.fill(rect.x, rect.y, rect.width, rect.height, page)
        room = self._text_width()
        left = rect.x + MARGIN

        # Heading: the title and the place on the left, the outcome on the right.
        canvas.draw_text(left, rect.y, self.title, replace(page, bold=True), max_width=room)
        title_width = display_width(self.title) + 2
        outcome = self._outcome()
        outcome_width = display_width(outcome)
        place_room = max(0, room - title_width - outcome_width - 2)
        canvas.draw_text(left + title_width, rect.y, keep_tail(self.location, place_room), muted, max_width=place_room)
        if outcome:
            colour = theme.accent if self._running else muted.foreground
            canvas.draw_text(
                left + max(title_width, room - outcome_width),
                rect.y,
                outcome,
                replace(page, foreground=colour),
                max_width=room,
            )

        # Output, newest at the bottom of its region.
        input_top = self.input.rect.y
        menu = self.input.completion_menu
        strip = 1 if menu is not None else 0
        separator = input_top - 1 - strip
        first, last = rect.y + 1, separator - 1
        self._output_rows = max(0, last - first + 1)
        self.offset = min(self.offset, self._furthest())
        for row, (line, start, end) in enumerate(self._visible(room, self._output_rows)):
            used = 0
            for span in line.spans(start, end):
                shown = self._themed(span, page)
                used += canvas.draw_text(left + used, first + row, shown.text, shown.style, max_width=room - used)

        canvas.draw_text(
            rect.x, separator, RULE * rect.width, replace(muted, foreground=theme.border), max_width=rect.width
        )
        if menu is not None:
            self._draw_candidates(canvas, menu, left, input_top - 1, room, page)

        hint = self._hint(room)
        canvas.draw_text(left, rect.bottom - 1, hint, muted, max_width=room)
        self.input.render(canvas)

    def _outcome(self) -> str:
        """Return what the right of the heading says: the seconds so far while running, else how it ended."""
        if self._running:
            return f"running {int(self._now() - self._started_at)}s"
        return self.status

    def _hint(self, room: int) -> str:
        """Return the keys that do something now, fewer of them when the line is narrow.

        Each hint has a rank, and the highest rank goes first until the line fits: history, then scrolling, then
        completion, then the way to run. The way out (rank 0) never goes, so a narrow terminal loses hints and never
        the key that leaves; and once the reader has scrolled up, the way back down outranks completion and history.
        """
        scroll = ("pgdn follow", 2) if self.offset else ("pgup scroll", 4)
        if self._running:
            hints = [("ctrl-c stop", 1), scroll, ("esc stop", 0)]
        else:
            hints = [("enter run", 1), ("tab complete", 3), ("\u2191\u2193 history", 5), scroll, ("esc close", 0)]
        joined = f" {SEPARATOR} "
        while True:
            hint = joined.join(text for text, _ in hints)
            droppable = [rank for _, rank in hints if rank]
            if display_width(hint) <= room or not droppable:
                return hint
            worst = max(droppable)
            hints.pop(max(index for index, (_, rank) in enumerate(hints) if rank == worst))

    def _visible(self, width: int, height: int) -> list:
        """Return the rows to draw, top to bottom, as ``(line, start, end)``, counting up from the newest by ``offset``."""
        skip = self.offset
        rows: list = []
        for line in reversed(self._lines()):
            for start, end in reversed(line.rows(width)):
                if skip:
                    skip -= 1
                    continue
                rows.append((line, start, end))
                if len(rows) >= height:
                    rows.reverse()
                    return rows
        rows.reverse()
        return rows

    @staticmethod
    def _themed(span: Span, page: Style) -> Span:
        """Give a span the page's colours where the program chose none, so default text follows the theme."""
        style = span.style
        return Span(
            span.text,
            replace(
                style, foreground=style.foreground or page.foreground, background=style.background or page.background
            ),
        )

    def _draw_candidates(self, canvas: Canvas, menu, left: int, row: int, room: int, page: Style) -> None:
        """Draw the candidates Tab is cycling through on one row, the one in the line highlighted."""
        items, current = menu
        theme = self.theme
        used = 0
        # Begin at the current one, so it is on show however many there are.
        for index in list(range(current, len(items))) + list(range(0, current)):
            label = items[index].display
            width = display_width(label) + 2
            if used + width > room and used:
                canvas.draw_text(
                    left + used, row, "\u2026", replace(page, foreground=theme.muted), max_width=room - used
                )
                break
            kind = kind_colour(items[index].type, theme)
            bold = items[index].type == DIRECTORY
            style = (
                Style(foreground=theme.surface_alt, background=kind, bold=True)
                if index == current
                else replace(page, foreground=kind, bold=bold)
            )
            used += canvas.draw_text(left + used, row, f" {label} ", style, max_width=room - used)

    def cursor(self) -> Point | None:
        """Show the cursor where the line has it."""
        return self.input.cursor()
