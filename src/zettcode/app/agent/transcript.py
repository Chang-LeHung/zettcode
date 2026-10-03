"""The conversation model: entries, their mutations, and their render cache.

The projector writes into this model and the UI reads it, so it lives on the
agent side of the application and never imports the shell. The scrollable view
over these entries is ``app.ui.widgets.transcript``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from time import monotonic

from ...tui import LineSource, TextLine
from ...tui.render import inset_line, wrap_columns
from .blocks import DEFAULT_PROCESSORS, EntryProcessors
from .entries import Entry, EntryStatus, MarkdownEntry, ProcessingEntry, TextEntry, ThinkingEntry, ToolEntry
from .rendering import ANSWER, DEFAULT_RENDERERS, THINKING, Renderers

#: Left margin of every transcript row: the width of the composer's ``\u203a ``
#: prompt, so text lines up under what the user types and never starts left of
#: the caret in an empty composer.
CONTENT_INDENT = 2

#: Wall-clock length of one animation step. ``Transcript.frame`` counts these
#: steps rather than terminal ticks, so the pace of the sweep and the running
#: marker does not depend on how often the terminal happens to repaint.
ANIMATION_SECONDS = 0.1

MAX_TOOL_OUTPUT = 64_000
TOOL_PREVIEW_ROWS = 5
TOOL_EXPANDED_ROWS = 40

#: Label of a row shown while the model is working and has not answered yet.
#: One request can show it more than once: every tool batch is followed by
#: another model call, and until that call produces something there is nothing
#: else on screen to say work is still going on.
PROCESSING = "Processing"

# Matches both escape families a tool can smuggle into its output: CSI
# (``ESC [`` parameters and a final byte) and OSC (``ESC ]`` up to BEL or ST).
# Stripping them keeps a coloured compiler message from repainting the canvas.
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def terminal_safe(value: str) -> str:
    """Strip escape sequences and replace characters the canvas cannot paint.

    Args:
        value: Raw tool output; newlines survive, a tab advances to the next
            four-column stop, and anything else non-printable becomes the
            replacement character so a tool cannot smuggle control codes into
            the canvas.

    Line endings are normalised first. Output printed with CRLF — a tool that
    shells out to ``curl -i`` or to a Windows program — would otherwise leave a
    replacement glyph at the end of every line, because a carriage return stops
    being a line break the moment it is replaced.
    """
    cleaned = _ANSI.sub("", value).replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return "".join(
        character if character in "\n" else character if character.isprintable() else "\ufffd" for character in cleaned
    )


def bounded_rows(value: str, width: int, limit: int) -> tuple[list[str], int]:
    """Wrap tool output and return a bounded viewport plus omitted rows.

    Args:
        value: Raw tool output.
        width: Wrap width in cells.
        limit: Most rows to return; the remainder is reported as omitted.
    """
    rows: list[str] = []
    for source in terminal_safe(value).splitlines() or [""]:
        rows.extend(wrap_columns(source, width))
    omitted = max(0, len(rows) - limit)
    return rows[:limit], omitted


def limit_output(value: str) -> str:
    """Bound stored tool output while keeping both ends useful.

    Args:
        value: Raw tool output; anything past ``MAX_TOOL_OUTPUT`` keeps its head
            and tail with a marker in between, so a huge result cannot dominate
            memory while still showing how it started and ended.
    """
    if len(value) <= MAX_TOOL_OUTPUT:
        return value
    half = MAX_TOOL_OUTPUT // 2
    omitted = len(value) - half * 2
    return f"{value[:half]}\n\u2026 {omitted:,} characters omitted \u2026\n{value[-half:]}"


def duration_text(seconds: float | None) -> str:
    """Format an elapsed time for a row header, to a tenth of a second.

    Args:
        seconds: Elapsed time, or ``None`` for a row that has already finished
            without a recorded duration.

    Milliseconds are deliberately not shown: the tenth is enough to see a row
    move, and three digits would change width on every repaint. A whole
    request's wall time is a different question, so it goes through
    :func:`elapsed_text` instead.
    """
    if seconds is None:
        return "done"
    return f"{max(0.0, seconds):.1f} s"


def elapsed_text(seconds: float) -> str:
    """Show every nonzero time unit in a finished request's wall time.

    Args:
        seconds: Wall time of the request, negative values clamped to zero.
    """
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def clock_text(moment: datetime | None = None) -> str:
    """Format a wall-clock reading as local ``HH:MM``.

    Args:
        moment: Time to show; ``None`` reads the clock, and tests inject a value
            so a rendered footer stays deterministic.
    """
    return (moment or datetime.now()).strftime("%H:%M")


class Transcript:
    """Own the conversation entries and their rendered block boundaries."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        renderers: Renderers = DEFAULT_RENDERERS,
        processors: EntryProcessors = DEFAULT_PROCESSORS,
    ) -> None:
        """Start an empty transcript whose elapsed times come from ``clock``.

        Args:
            clock: Time source for row durations, injectable for tests.
            renderers: Chain that phrases tool rows; tests can pass their own to
                pin the wording a row would show.
            processors: Chain that produces presentation lines for entries.
        """
        self.renderers = renderers
        self.processors = processors
        self.entries: list[Entry] = []
        self.clock = clock
        self.version = 0
        self.frame = 0
        self._next_id = 1

    def _add[T: Entry](self, entry: T) -> T:
        """Append a typed entry and invalidate the transcript's line boundaries."""
        self._next_id += 1
        self.entries.append(entry)
        self.version += 1
        return entry

    def _last[T: Entry](self, entry_type: type[T]) -> T | None:
        """Return the newest entry of one type, or None when there is none."""
        return next((entry for entry in reversed(self.entries) if isinstance(entry, entry_type)), None)

    def entry(self, entry_id: int) -> Entry | None:
        """Return the entry with this id, or None when it has been cleared."""
        return next((item for item in self.entries if item.id == entry_id), None)

    def clear(self) -> None:
        """Drop every entry, for instance when starting a new session."""
        self.entries.clear()
        self.version += 1

    def replace(self, entries: list[Entry]) -> None:
        """Replace visible entries with the chosen session's rebuilt history."""
        self.entries[:] = entries
        self._next_id = max((entry.id for entry in entries), default=0) + 1
        self.version += 1

    def user_message(self, text: str) -> None:
        """Append a historical user message without opening a live wait row."""
        self._add(TextEntry(id=self._next_id, kind="user", text=text))

    def restore_thinking(self, text: str, duration_ns: int | None) -> None:
        """Append completed reasoning from one stored assistant response."""
        duration = duration_ns / 1_000_000_000 if duration_ns is not None else None
        self._add(
            ThinkingEntry(
                id=self._next_id,
                text=self.renderers.text(THINKING, text, opening=True),
                status=EntryStatus.COMPLETED,
                duration=duration,
            )
        )

    def finish_restored_tools(self) -> None:
        """Mark tool calls without stored results as interrupted, not running."""
        for entry in self.entries:
            if isinstance(entry, ToolEntry) and entry.status is EntryStatus.RUNNING:
                entry.status = EntryStatus.SKIPPED
                entry.text = "Result unavailable (session interrupted)"
                self.version += 1

    def advance_frame(self) -> None:
        """Move the activity animation on so running rows repaint.

        The counter is derived from the clock, one step per
        :data:`ANIMATION_SECONDS`, rather than counted in terminal ticks: the
        renderers pace their sweep and blink with it, so a terminal repainting
        ten times a second and one repainting sixty times a second look the
        same. Ticks that fall inside one step leave the counter where it is.
        """
        self.frame = int(self.clock() / ANIMATION_SECONDS)
        for entry in self.entries:
            if (
                isinstance(entry, (ProcessingEntry, ThinkingEntry, ToolEntry))
                and entry.status is EntryStatus.RUNNING
                and entry.started_at is not None
            ):
                entry.duration = self.clock() - entry.started_at
        self.version += 1

    def notice(self, text: str) -> None:
        """Append a muted one-off status line."""
        self._add(TextEntry(id=self._next_id, kind="notice", text=text))

    def model_changed(self, previous: str, current: str) -> None:
        """Announce a model change as a centered line in the conversation."""
        self._add(TextEntry(id=self._next_id, kind="model_change", text=f"Model changed from {previous} to {current}."))

    def markdown(self, text: str) -> None:
        """Append a Markdown block, parsed and rendered like an answer.

        Use it for command output, which is usually a list or a table; a notice
        is the terse alternative for one-line status such as ``stopped``.
        """
        entry = MarkdownEntry(id=self._next_id, kind="message")
        entry.markdown.append(text)
        entry.text = text
        self._add(entry)

    def welcome(self, text: str) -> None:
        """Append the banner shown once at startup."""
        self._add(TextEntry(id=self._next_id, kind="welcome", text=text))

    def begin_turn(self, prompt: str) -> None:
        """Record the user prompt and open the first wait row for the reply."""
        self._add(TextEntry(id=self._next_id, kind="user", text=prompt))
        self.wait_for_model()

    def wait_for_model(self) -> bool:
        """Open a wait row for the next model call, and report whether it opened.

        Nothing is known about the response yet, and a call can take seconds, so
        the row goes up as soon as the call starts. It is opened again after a
        tool batch, because the loop then calls the model a second time; a wait
        is not repeated while a tool is still running, and never while a wait is
        already open.
        """
        if any(isinstance(entry, ToolEntry) and entry.status is EntryStatus.RUNNING for entry in self.entries):
            return False
        pending = self._last(ProcessingEntry)
        if pending is not None and pending.status is EntryStatus.RUNNING:
            return False
        self._add(ProcessingEntry(id=self._next_id, title=PROCESSING, started_at=self.clock()))
        return True

    def start_thinking(self) -> ThinkingEntry:
        """Return the open thinking block, promoting the placeholder when it fits."""
        current = self._last(ThinkingEntry)
        if current is not None and current.status is EntryStatus.RUNNING:
            return current
        pending = self._last(ProcessingEntry)
        thinking = ThinkingEntry(id=pending.id if pending is not None else self._next_id, started_at=self.clock())
        if pending is not None:
            # The placeholder turned out to be reasoning: replace the same row,
            # retaining its id and position for hit-testing and focus.
            self.entries[self.entries.index(pending)] = thinking
            self.version += 1
            return thinking
        return self._add(thinking)

    def drop_pending(self) -> bool:
        """Remove the placeholder once real output has started."""
        if self.entries and isinstance(self.entries[-1], ProcessingEntry):
            self.entries.pop()
            self.version += 1
            return True
        return False

    def append_thinking(self, delta: str) -> None:
        """Append a reasoning delta to the running thinking block."""
        entry = self.start_thinking()
        entry.text += self.renderers.text(THINKING, delta, opening=not entry.text)
        self.version += 1

    def complete_thinking(self) -> None:
        """Close the running thinking block and stamp its elapsed time."""
        entry = self._last(ThinkingEntry)
        if entry is None or entry.status is not EntryStatus.RUNNING:
            self.drop_pending()
            return
        entry.status = EntryStatus.COMPLETED
        if entry.started_at is not None:
            entry.duration = self.clock() - entry.started_at
        self.version += 1

    def append_answer(self, delta: str) -> None:
        """Stream a delta into the trailing answer block, opening one if needed."""
        self.drop_pending()
        current = self.entries[-1] if self.entries else None
        if not isinstance(current, MarkdownEntry) or current.kind != "answer":
            current = MarkdownEntry(id=self._next_id, kind="answer")
            self._add(current)
        delta = self.renderers.text(ANSWER, delta, opening=not current.text)
        current.markdown.append(delta)
        current.text += delta
        self.version += 1

    def start_tool(self, call_id: str, name: str, arguments: Mapping[str, object]) -> None:
        """Open a tool row, closing any reasoning or placeholder row first.

        Args:
            call_id: Identifier the matching result will carry.
            name: Tool name; the renderer chain turns it into the row's words.
            arguments: Arguments the chain reads to phrase the call.
        """
        self.complete_thinking()
        self.drop_pending()
        row = self.renderers.describe(name, arguments)
        self._add(
            ToolEntry(
                id=self._next_id,
                call_id=call_id,
                tool=name,
                title=row.title,
                language=row.language,
                started_at=self.clock(),
            )
        )

    def complete_tool(
        self, call_id: str, output: str, *, status: EntryStatus = EntryStatus.COMPLETED, wait: bool = True
    ) -> None:
        """Attach a tool result to its row, ignoring calls that are no longer on screen.

        Args:
            call_id: Identifier from the matching ``start_tool`` call.
            output: Raw output; bounded before it is stored.
            status: Final status, normally ``completed``, ``failed``, or
                ``skipped``.
        """
        entry = next(
            (item for item in reversed(self.entries) if isinstance(item, ToolEntry) and item.call_id == call_id), None
        )
        if entry is None:
            return
        outcome = EntryStatus(status)
        entry.text = limit_output(self.renderers.body(entry.tool, output))
        entry.status = outcome
        if entry.started_at is not None:
            entry.duration = self.clock() - entry.started_at
        self.version += 1
        # The loop calls the model again once the batch has produced its
        # results, so the reader is told that work continues.
        if wait:
            self.wait_for_model()

    def toggle(self, entry_id: int) -> bool:
        """Expand or collapse one collapsible entry and report whether it changed.

        Args:
            entry_id: Id from the click or key that triggered the toggle; a
                running or empty tool row refuses to expand.
        """
        entry = self.entry(entry_id)
        if not isinstance(entry, (ThinkingEntry, ToolEntry)):
            return False
        if isinstance(entry, ToolEntry) and (entry.status is EntryStatus.RUNNING or not entry.text):
            return False
        entry.expanded = not entry.expanded
        self.version += 1
        return True

    def toggle_latest_thinking(self) -> bool:
        """Expand or collapse the newest thinking block."""
        entry = self._last(ThinkingEntry)
        if entry is None:
            return False
        entry.expanded = not entry.expanded
        self.version += 1
        return True

    def collapse_thinking_except(self, entry_id: int | None) -> bool:
        """Collapse every expanded thinking block except the one to keep open.

        Args:
            entry_id: Block to leave expanded, or ``None`` to collapse them all.
        """
        changed = False
        for entry in self.entries:
            if isinstance(entry, ThinkingEntry) and entry.expanded and entry.id != entry_id:
                entry.expanded = False
                changed = True
        if changed:
            self.version += 1
        return changed


class LeadingGap(LineSource):
    """LineSource that renders one blank row before a nested source.

    Streamed answers are served by ``Markdown`` so their parsing stays
    incremental, which means the separating blank line cannot come from the
    generic entry renderer.
    """

    def __init__(self, source: LineSource) -> None:
        """Wrap the nested line source.

        Args:
            source: Line source whose rows shift down by one; it is a
                ``LineSource`` itself, so the wrapper stays composable.
        """
        self.source = source

    def count(self, width: int) -> int:
        """Return the nested line count plus the leading blank row."""
        return self.source.count(width) + 1

    def line(self, index: int, width: int) -> TextLine:
        """Shift the index past the blank row and delegate to the nested source."""
        if index == 0:
            return TextLine()
        return self.source.line(index - 1, width)


class Indented(LineSource):
    """LineSource that shifts every row right by a fixed margin.

    The margin is drawn with the row's own leading style, so a line that carries
    a background keeps it across the gutter. The nested source wraps at the
    remaining width, which keeps long lines inside the window instead of
    wrapping past its right edge.
    """

    def __init__(self, source: LineSource, columns: int = CONTENT_INDENT) -> None:
        """Wrap ``source`` with ``columns`` cells of leading space.

        Args:
            source: Line source to shift right.
            columns: Margin in cells; the nested source wraps that much narrower.
        """
        self.source = source
        self.columns = max(0, columns)

    def count(self, width: int) -> int:
        """Return the nested row count, which the margin does not change."""
        return self.source.count(max(1, width - self._margin(width)))

    def line(self, index: int, width: int) -> TextLine:
        """Draw the margin, then the nested row at the reduced width."""
        margin = self._margin(width)
        row = self.source.line(index, max(1, width - margin))
        return inset_line(row, margin)

    def _margin(self, width: int) -> int:
        """Keep at least one column available for content on narrow screens."""
        return min(self.columns, max(0, width - 1))


#: The running marker's two states: the sparkle, then a dot of the same width so
#: the label after it never shifts as the marker blinks.
RUNNING_GLYPHS = ("\u2726", "\u00b7")

#: Steps per half-blink: 2.7 steps is the quarter second a marker holds each of
#: its two states, so a running row blinks about twice a second.
BLINK_FRAMES = 2.7

#: Steps the highlight spends on one column, where a step is
#: :data:`ANIMATION_SECONDS` of wall time: one step is the 100 ms a column stays
#: lit, ten columns a second. The step, not the terminal frame, is what sets the
#: pace, so a repaint at 60 fps and one at 10 look the same.
SWEEP_FRAMES = 1.0


def sweep_step(frame: int) -> int:
    """Return the column the highlight has reached at one animation frame.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return int(frame / SWEEP_FRAMES)


def activity_glyph(frame: int) -> str:
    """Return the marker shared by every running row, which blinks in place.

    The marker keeps one column and alternates between its two states instead of
    cycling through different symbols: a row that blinks reads as "still
    working" the way a terminal spinner does, while a rotating glyph just looks
    like noise. Every running row is drawn with the same ``frame``, so the
    transcript and the status bar icon blink in step.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return RUNNING_GLYPHS[0 if blinking(frame) else 1]


def blinking(frame: int) -> bool:
    """Say whether a running row is in the bright half of its blink."""
    return int(frame / BLINK_FRAMES) % 2 == 0
