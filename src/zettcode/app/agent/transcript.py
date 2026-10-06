"""The conversation model: entries, their mutations, and their render cache.

The projector writes into this model and the UI reads it, so it lives on the
agent side of the application and never imports the shell. The scrollable view
over these entries is ``app.ui.widgets.transcript``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from typing import TypeVar

from ...config import DEFAULT_TRANSCRIPT_MAX_ENTRIES
from ...tui import LineSource, TextLine
from ...tui.render import inset_line
from .blocks import DEFAULT_PROCESSORS, EntryProcessors
from .entries import Entry, EntryStatus, MarkdownEntry, ProcessingEntry, TextEntry, ThinkingEntry, ToolEntry
from .rendering import ANSWER, DEFAULT_RENDERERS, THINKING, Renderers
from .rows import (
    ANIMATION_SECONDS,
    COMPACTING_LABEL,
    CONTENT_INDENT,
    PROCESSING,
    limit_output,
)

#: The entry subtype an add/look-up call works with, pinned by the caller.
E = TypeVar("E", bound=Entry)

#: Smallest batch a trim drops, so the list shift and the view rebuild that
#: follow a trim are paid once per several appends instead of per append. The
#: real batch is a share of the cap, so a large cap trims off more at a time.
MIN_TRIM_SLACK = 8

#: Share of the cap the list may grow past before a trim: 1/32 of it. Small caps
#: keep a proportionally small overrun, large caps trim fewer times.
TRIM_SLACK_SHARE = 32


class Transcript:
    """Own the conversation entries and their rendered block boundaries."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        renderers: Renderers = DEFAULT_RENDERERS,
        processors: EntryProcessors = DEFAULT_PROCESSORS,
        max_entries: int = DEFAULT_TRANSCRIPT_MAX_ENTRIES,
    ) -> None:
        """Start an empty transcript whose elapsed times come from ``clock``.

        Args:
            clock: Time source for row durations, injectable for tests.
            renderers: Chain that phrases tool rows; tests can pass their own to
                pin the wording a row would show.
            processors: Chain that produces presentation lines for entries.
            max_entries: Conversation entries kept for display; older ones are
                dropped, while the session file keeps the whole tree. Must be
                positive.
        """
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.renderers = renderers
        self.processors = processors
        self.entries: list[Entry] = []
        self.clock = clock
        self.max_entries = max_entries
        self._trim_threshold = max_entries + max(MIN_TRIM_SLACK, max_entries // TRIM_SLACK_SHARE)
        self.version = 0
        self.frame = 0
        self._next_id = 1
        # Earliest entry touched since the view last took the mark, so it can
        # re-measure only the changed suffix instead of the whole transcript.
        self._dirty_from: int | None = None

    def take_dirty(self) -> int | None:
        """Return the earliest changed entry index and reset the mark.

        A view calls this once per version and rebuilds its line boundaries
        from that index on; everything before it is unchanged and can be kept.
        The mark is consumed rather than merely read so a later append starts
        from the new tail instead of the oldest edit ever made. ``None`` means
        no precise mark is available and the caller should rebuild in full.
        """
        dirty = self._dirty_from
        self._dirty_from = None
        return dirty

    def _touch(self, index: int) -> None:
        """Record that the entry at ``index`` changed, keeping the earliest one."""
        self._dirty_from = index if self._dirty_from is None else min(self._dirty_from, index)

    def _touch_entry(self, entry: Entry) -> None:
        """Mark one entry changed, checking the tail before searching the list."""
        last = len(self.entries) - 1
        if last >= 0 and self.entries[last] is entry:
            self._touch(last)
            return
        index = next((index for index, item in enumerate(self.entries) if item is entry), None)
        if index is not None:
            self._touch(index)

    def _add(self, entry: E) -> E:
        """Append a typed entry and invalidate the transcript's line boundaries."""
        self._next_id += 1
        self._touch(len(self.entries))
        self.entries.append(entry)
        self._trim()
        self.version += 1
        return entry

    def _trim(self) -> None:
        """Drop the oldest entries once the display cap is well past.

        Trimming from the front shifts every remaining index, so the render
        view is told to rebuild its boundaries from zero. That rebuild is cheap
        at an unchanged width — cached blocks only re-key — and it happens once
        per trim batch, so the amortized cost per new entry stays flat. The
        store keeps the full conversation; this bounds what is shown.
        """
        if len(self.entries) <= self._trim_threshold:
            return
        del self.entries[: len(self.entries) - self.max_entries]
        self._dirty_from = 0

    def _last(self, entry_type: type[E]) -> E | None:
        """Return the newest entry of one type, or None when there is none."""
        return next((entry for entry in reversed(self.entries) if isinstance(entry, entry_type)), None)

    def entry(self, entry_id: int) -> Entry | None:
        """Return the entry with this id, or None when it has been cleared."""
        return next((item for item in self.entries if item.id == entry_id), None)

    def clear(self) -> None:
        """Drop every entry, for instance when starting a new session."""
        self.entries.clear()
        self._dirty_from = 0
        self.version += 1

    def replace(self, entries: list[Entry]) -> None:
        """Replace visible entries with the chosen session's rebuilt history."""
        self.entries[:] = entries
        self._next_id = max((entry.id for entry in entries), default=0) + 1
        self._trim()
        self._dirty_from = 0
        self.version += 1

    def user_message(self, text: str) -> None:
        """Append a historical user message without opening a live wait row."""
        self._add(TextEntry(id=self._next_id, kind="user", text=text))

    def restore_thinking(self, text: str, duration_ns: int | None) -> None:
        """Append completed reasoning from one stored assistant response."""
        duration = duration_ns / 1_000_000_000 if duration_ns is not None else None
        self._add(
            ThinkingEntry(  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
                id=self._next_id,
                text=self.renderers.text(THINKING, text, opening=True),
                status=EntryStatus.COMPLETED,
                duration=duration,
            )
        )

    def finish_restored_tools(self) -> None:
        """Mark tool calls without stored results as interrupted, not running."""
        for index, entry in enumerate(self.entries):
            if isinstance(entry, ToolEntry) and entry.status is EntryStatus.RUNNING:
                entry.status = EntryStatus.SKIPPED
                entry.text = "Result unavailable (session interrupted)"
                self._touch(index)
                self.version += 1

    def advance_frame(self) -> None:
        """Move the activity animation on so running rows repaint.

        The counter is derived from the clock, one step per
        :data:`ANIMATION_SECONDS`, rather than counted in terminal ticks: the
        renderers pace their sweep and blink with it, so a terminal repainting
        ten times a second and one repainting sixty times a second look the
        same. A tick that falls inside the step it already sits on changes
        nothing, and says so: every version bump makes the transcript view
        measure every entry again, so the frame rate a busy shell paints at
        must not decide how much work that is.
        """
        frame = int(self.clock() / ANIMATION_SECONDS)
        if frame == self.frame:
            return
        self.frame = frame
        changed = False
        # Running rows are the tail: each opener appends, and a result closes
        # the row it answers before anything new lands. Walking back from the
        # end stops at the first settled row instead of scanning the whole
        # transcript, whose length must not decide the animation's cost.
        for index in range(len(self.entries) - 1, -1, -1):
            entry = self.entries[index]
            if not isinstance(entry, (ProcessingEntry, ThinkingEntry, ToolEntry)):
                break
            if entry.status is not EntryStatus.RUNNING:
                break
            if entry.started_at is not None:
                entry.duration = self.clock() - entry.started_at
            self._touch(index)
            changed = True
        if changed:
            self.version += 1

    def notice(self, text: str) -> None:
        """Append a muted one-off status line."""
        self._add(TextEntry(id=self._next_id, kind="notice", text=text))

    def error(self, text: str) -> None:
        """Append a one-off failure line, painted as an error."""
        self._add(TextEntry(id=self._next_id, kind="notice", text=text, level="error"))

    def announce(self, text: str) -> None:
        """Announce a change as one centered line between horizontal rules."""
        self._add(TextEntry(id=self._next_id, kind="announcement", text=text))

    def model_changed(self, previous: str, current: str) -> None:
        """Announce a model change in the conversation."""
        self.announce(f"Model changed from {previous} to {current}.")

    def effort_changed(self, previous: str, current: str) -> None:
        """Announce a reasoning-effort change the way a model change is shown."""
        self.announce(f"Reasoning effort changed from {previous} to {current}.")

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
        self._add(ProcessingEntry(id=self._next_id, title=PROCESSING, started_at=self.clock()))  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
        return True

    def start_thinking(self) -> ThinkingEntry:
        """Return the open thinking block, promoting the placeholder when it fits."""
        current = self._last(ThinkingEntry)
        if current is not None and current.status is EntryStatus.RUNNING:
            return current
        pending = self._last(ProcessingEntry)
        thinking = ThinkingEntry(id=pending.id if pending is not None else self._next_id, started_at=self.clock())  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
        if pending is not None:
            # The placeholder turned out to be reasoning: replace the same row,
            # retaining its id and position for hit-testing and focus.
            index = self.entries.index(pending)
            self.entries[index] = thinking
            self._touch(index)
            self.version += 1
            return thinking
        return self._add(thinking)

    def start_compaction(self) -> ThinkingEntry:
        """Open the row that shows the summarizer working.

        A compaction is a model call streamed back like any other, so it gets
        the same row as reasoning — blinking, sweep, and timer included — under
        its own label. The two never borrow each other's row: a compaction that
        happens between reasoning spans keeps its text out of the thinking one.
        """
        current = self._last(ThinkingEntry)
        if current is not None and current.status is EntryStatus.RUNNING and current.title == COMPACTING_LABEL:
            return current
        pending = self._last(ProcessingEntry)
        row = ThinkingEntry(  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
            id=pending.id if pending is not None else self._next_id,
            title=COMPACTING_LABEL,
            started_at=self.clock(),
        )
        if pending is not None:
            index = self.entries.index(pending)
            self.entries[index] = row
            self._touch(index)
            self.version += 1
            return row
        return self._add(row)

    def append_compaction(self, delta: str) -> None:
        """Append one summary fragment to the running compaction row."""
        row = self.start_compaction()
        row.text += delta
        self._touch_entry(row)
        self.version += 1

    def complete_compaction(self) -> None:
        """Close the running compaction row and stamp its elapsed time."""
        row = self._last(ThinkingEntry)
        if row is None or row.title != COMPACTING_LABEL or row.status is not EntryStatus.RUNNING:
            return
        row.status = EntryStatus.COMPLETED
        if row.started_at is not None:
            row.duration = self.clock() - row.started_at
        self._touch_entry(row)
        self.version += 1

    def drop_pending(self) -> bool:
        """Remove the placeholder once real output has started."""
        if self.entries and isinstance(self.entries[-1], ProcessingEntry):
            self._touch(len(self.entries) - 1)
            self.entries.pop()
            self.version += 1
            return True
        return False

    def append_thinking(self, delta: str) -> None:
        """Append a reasoning delta to the running thinking block."""
        entry = self.start_thinking()
        entry.text += self.renderers.text(THINKING, delta, opening=not entry.text)
        self._touch_entry(entry)
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
        self._touch_entry(entry)
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
        self._touch_entry(current)
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
            ToolEntry(  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
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
        self._touch_entry(entry)
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
        self._touch_entry(entry)
        self.version += 1
        return True

    def toggle_latest_thinking(self) -> bool:
        """Expand or collapse the newest thinking block."""
        entry = self._last(ThinkingEntry)
        if entry is None:
            return False
        entry.expanded = not entry.expanded
        self._touch_entry(entry)
        self.version += 1
        return True

    def collapse_thinking_except(self, entry_id: int | None) -> bool:
        """Collapse every expanded thinking block except the one to keep open.

        Args:
            entry_id: Block to leave expanded, or ``None`` to collapse them all.
        """
        changed = False
        for index, entry in enumerate(self.entries):
            if isinstance(entry, ThinkingEntry) and entry.expanded and entry.id != entry_id:
                entry.expanded = False
                self._touch(index)
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
