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
        # Where the current request's own rows begin: the wait row is opened
        # against the content already there, and everything above it until the
        # next request is this request's work. The animation walks this range
        # and no further, so a step's cost follows the request, not the session.
        self._turn_from = 0
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

    def _open_wait(self) -> ProcessingEntry | None:
        """Return the wait row while it is open, which is what keeps it pinned.

        The row is the last entry for as long as the request runs, so "open"
        and "at the tail" are the same thing: anything that lands below it would
        be something the reader is still waiting for.
        """
        last = self.entries[-1] if self.entries else None
        if isinstance(last, ProcessingEntry) and last.status is EntryStatus.RUNNING:
            return last
        return None

    def _add_index(self) -> int:
        """Return where a new entry belongs: above the pinned wait row, or at the end.

        The one place the pin is written down as an index, so the add path and
        the answer path cannot disagree about where the row sits.
        """
        return len(self.entries) - 1 if self._open_wait() is not None else len(self.entries)

    def _add(self, entry: E) -> E:
        """Add a typed entry above the wait row, or append it when none is open.

        The wait row is pinned to the bottom of the transcript while the request
        runs: reasoning, tool calls, and the answer all land above it, so the one
        line that says work is going on stays where the reader is already
        looking instead of scrolling off with the reply that replaced it.
        """
        self._next_id += 1
        index = self._add_index()
        self._touch(index)
        self.entries.insert(index, entry)
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
        dropped = len(self.entries) - self.max_entries
        del self.entries[:dropped]
        # Every index the transcript is holding on to moves with the list.
        self._turn_from = max(0, self._turn_from - dropped)
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
        self._turn_from = 0
        self._dirty_from = 0
        self.version += 1

    def replace(self, entries: list[Entry]) -> None:
        """Replace visible entries with the chosen session's rebuilt history."""
        self.entries[:] = entries
        self._next_id = max((entry.id for entry in entries), default=0) + 1
        # A rebuilt history is all in the past: no request is open in it, so the
        # animation has no range of its own to walk.
        self._turn_from = len(self.entries)
        self._trim()
        self._dirty_from = 0
        self.version += 1

    def user_message(self, text: str, *, side: bool = False) -> None:
        """Append a historical user message without opening a live wait row.

        Args:
            text: What the reader asked.
            side: The message was a side question, which the row shows as such.
        """
        self._add(TextEntry(id=self._next_id, kind="user", text=text, side=side))

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
        self.finish_running_rows("Result unavailable (session interrupted)")

    def finish_running_rows(self, note: str) -> None:
        """Close every row a finished run left open, and say why.

        A request that ends mid-call — stopped, failed, or restored from a
        session whose turn never completed — leaves rows whose result will never
        arrive. They keep their own timer up to the moment the request ended and
        are marked skipped, so the transcript holds no row that still claims to
        be working after nothing is. The wait row is not one of them: the shell
        settles that one with the line the request ended on.

        Args:
            note: What the body of an unfinished tool row is replaced with.
        """
        changed = False
        for index, entry in enumerate(self.entries):
            if not isinstance(entry, (ThinkingEntry, ToolEntry)) or entry.status is not EntryStatus.RUNNING:
                continue
            entry.status = EntryStatus.SKIPPED
            if isinstance(entry, ToolEntry) and not entry.text:
                entry.text = note
            if entry.started_at is not None:
                entry.duration = self.clock() - entry.started_at
            self._touch(index)
            changed = True
        if changed:
            self.version += 1

    def advance_frame(self) -> None:
        """Move the activity animation on, and bring every running timer up.

        The waiting row is the one row that sweeps; a reasoning or tool row
        above it is painted flat, so a step rebuilds it only because its timer
        moved.

        The walk covers the request's own rows and no more: a row that is not a
        row at all can sit between two running ones — an approval or a command
        notice lands beside the call it answered, and a batch's results can
        arrive out of order — so every running row in the range is brought up,
        and the range bounds the cost instead of the length of the session.

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
        for index in range(self._turn_from, len(self.entries)):
            entry = self.entries[index]
            if not isinstance(entry, (ProcessingEntry, ThinkingEntry, ToolEntry)):
                continue
            if entry.status is not EntryStatus.RUNNING:
                continue
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

    def begin_turn(self, prompt: str, *, side: bool = False) -> None:
        """Record the user prompt and open the first wait row for the reply.

        Args:
            prompt: What the reader asked, as it should appear in the transcript.
            side: The question is a side one: answered here, never part of the
                conversation the model carries afterwards.
        """
        self._add(TextEntry(id=self._next_id, kind="user", text=prompt, side=side))
        self.wait_for_model()

    def wait_for_model(self) -> bool:
        """Open the pinned wait row for a request, and report whether it opened.

        Nothing is known about the response yet, and a call can take seconds, so
        the row goes up as soon as the request starts and stays for all of it:
        the loop calls the model again after every tool batch, and one row that
        has been counting the whole time says more than a row per batch would.
        """
        if self._open_wait() is not None:
            return False
        # A row an interrupted request left running is one more reason not to
        # open a second: the transcript already says work is in progress, and
        # the animation walks only the rows a request opens, so a stray row
        # behind that range would never be brought up. The request's own end
        # closes them (:meth:`finish_running_rows`), which is what keeps the
        # range the whole truth; this is the backstop that depends on it.
        if any(
            isinstance(entry, (ThinkingEntry, ToolEntry)) and entry.status is EntryStatus.RUNNING
            for entry in self.entries
        ):
            return False
        self._turn_from = len(self.entries)
        self._add(ProcessingEntry(id=self._next_id, title=PROCESSING, started_at=self.clock()))  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
        return True

    def settle_wait(self, text: str) -> bool:
        """Close the pinned wait row with the line its request ended on.

        The row is what the reader watched for the whole request, so it is where
        the outcome belongs: it keeps its place at the bottom of the transcript
        and its own timer becomes the elapsed time it reports. A row left running
        — or removed, as one used to be as soon as the answer started — is how a
        stopped request reads as one that said nothing at all.

        Args:
            text: The line to leave in its place, such as
                ``Processed for 12s · 22:53``.
        """
        row = self._open_wait()
        if row is None:
            return False
        row.status = EntryStatus.COMPLETED
        row.text = text
        row.duration = self.clock() - row.started_at
        self._touch_entry(row)
        self.version += 1
        return True

    def start_thinking(self) -> ThinkingEntry:
        """Open a reasoning row, which lands above the wait row below it.

        The wait row is not turned into this one: it stays where it is, saying
        that a model call is still running, and the reasoning grows above it.
        """
        current = self._last(ThinkingEntry)
        if current is not None and current.status is EntryStatus.RUNNING:
            return current
        return self._add(ThinkingEntry(id=self._next_id, started_at=self.clock()))  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py

    def start_compaction(self) -> ThinkingEntry:
        """Open the row that shows the summarizer working.

        A compaction is a model call streamed back like any other, so it gets
        the same row as reasoning — marker, and timer included — under its own
        label. The two never borrow each other's row: a compaction that happens
        between reasoning spans keeps its text out of the thinking one.
        """
        current = self._last(ThinkingEntry)
        if current is not None and current.status is EntryStatus.RUNNING and current.title == COMPACTING_LABEL:
            return current
        return self._add(
            ThinkingEntry(  # type: ignore[call-arg]  # kind is a fixed class value; see entries.py
                id=self._next_id,
                title=COMPACTING_LABEL,
                started_at=self.clock(),
            )
        )

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
            return
        entry.status = EntryStatus.COMPLETED
        if entry.started_at is not None:
            entry.duration = self.clock() - entry.started_at
        self._touch_entry(entry)
        self.version += 1

    def append_answer(self, delta: str) -> None:
        """Stream a delta into the answer block, opening one if needed.

        The wait row stays open below it: the answer is being written, not
        finished, and the pinned row is how that still reads while it streams.
        """
        # The answer is the entry the reply is writing into: the tail, or the
        # one the pinned wait row sits under.
        index = self._add_index() - 1
        current = self.entries[index] if index >= 0 else None
        if not isinstance(current, MarkdownEntry) or current.kind != "answer":
            current = MarkdownEntry(id=self._next_id, kind="answer")
            self._add(current)
        delta = self.renderers.text(ANSWER, delta, opening=not current.text)
        current.markdown.append(delta)
        current.text += delta
        self._touch_entry(current)
        self.version += 1

    def start_tool(self, call_id: str, name: str, arguments: Mapping[str, object]) -> None:
        """Open a tool row, closing the reasoning span it interrupts.

        Args:
            call_id: Identifier the matching result will carry.
            name: Tool name; the renderer chain turns it into the row's words.
            arguments: Arguments the chain reads to phrase the call.
        """
        self.complete_thinking()
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
