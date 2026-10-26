"""What the model produces as it arrives: reasoning, a compaction, an answer, tool calls.

Each of these is a row that grows while a request runs, or opens when the agent starts
something and closes when it reports back. They land above the wait row (the log's
rule), and a tool's result ends by telling the reader that work continues, which is
why this builds on :class:`~.turn.TurnMixin` rather than on the log alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..entries import EntryKind, EntryStatus, MarkdownEntry, ThinkingEntry, ToolEntry
from ..rendering import ANSWER, THINKING, Renderers
from ..text import COMPACTING_LABEL, limit_output
from .turn import TurnMixin


class StreamMixin(TurnMixin):
    """Open, grow, and close the rows that carry the agent's output."""

    #: Chain that phrases tool rows and shapes streamed text; set by :class:`~.Transcript`.
    renderers: Renderers
    clock: Callable[[], float]

    # -- reasoning ------------------------------------------------------------
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

    def start_thinking(self) -> ThinkingEntry:
        """Open a reasoning row, which lands above the wait row below it.

        The wait row is not turned into this one: it stays where it is, saying
        that a model call is still running, and the reasoning grows above it.
        """
        current = self._last(ThinkingEntry)
        if current is not None and current.running:
            return current
        return self._add(ThinkingEntry(id=self._next_id, started_at=self.clock()))

    def append_thinking(self, delta: str) -> None:
        """Append a reasoning delta to the running thinking block."""
        entry = self.start_thinking()
        entry.text += self.renderers.text(THINKING, delta, opening=not entry.text)
        self._changed(entry)

    def complete_thinking(self) -> None:
        """Close the running thinking block and stamp its elapsed time."""
        entry = self._last(ThinkingEntry)
        if entry is None or not entry.running:
            return
        entry.finish(EntryStatus.COMPLETED, self.clock())
        self._changed(entry)

    # -- compaction -----------------------------------------------------------
    def start_compaction(self) -> ThinkingEntry:
        """Open the row that shows the summarizer working.

        A compaction is a model call streamed back like any other, so it gets
        the same row as reasoning — marker, and timer included — under its own
        label. The two never borrow each other's row: a compaction that happens
        between reasoning spans keeps its text out of the thinking one.
        """
        current = self._last(ThinkingEntry)
        if current is not None and current.running and current.title == COMPACTING_LABEL:
            return current
        return self._add(
            ThinkingEntry(
                id=self._next_id,
                title=COMPACTING_LABEL,
                started_at=self.clock(),
            )
        )

    def append_compaction(self, delta: str) -> None:
        """Append one summary fragment to the running compaction row."""
        row = self.start_compaction()
        row.text += delta
        self._changed(row)

    def complete_compaction(self) -> None:
        """Close the running compaction row and stamp its elapsed time."""
        row = self._last(ThinkingEntry)
        if row is None or row.title != COMPACTING_LABEL or not row.running:
            return
        row.finish(EntryStatus.COMPLETED, self.clock())
        self._changed(row)

    # -- the answer -----------------------------------------------------------
    def append_answer(self, delta: str) -> None:
        """Stream a delta into the answer block, opening one if needed.

        The wait row stays open below it: the answer is being written, not
        finished, and the pinned row is how that still reads while it streams.
        """
        # The answer is the entry the reply is writing into: the tail, or the
        # one the pinned wait row sits under.
        index = self._add_index() - 1
        current = self.entries[index] if index >= 0 else None
        if not isinstance(current, MarkdownEntry) or current.kind is not EntryKind.ANSWER:
            current = MarkdownEntry(id=self._next_id, kind=EntryKind.ANSWER)
            self._add(current)
        delta = self.renderers.text(ANSWER, delta, opening=not current.text)
        current.markdown.append(delta)
        current.text += delta
        self._changed(current)

    # -- tools ----------------------------------------------------------------
    def start_tool(self, call_id: str, name: str, arguments: Mapping[str, object]) -> None:
        """Open a tool row, closing the reasoning span it interrupts.

        Args:
            call_id: Identifier the matching result will carry.
            name: Tool name; the renderer chain turns it into the row's words.
            arguments: Arguments the chain reads to phrase the call.
        """
        self.complete_thinking()
        # The tool's own handler decides which entry the call is, so what a row carries is its
        # tool's business and this opens every one the same way.
        self._add(self.renderers.open_tool(name, arguments, id=self._next_id, call_id=call_id, started_at=self.clock()))

    def restate_tool(self, call_id: str, arguments: Mapping[str, object]) -> None:
        """Phrase a row again with arguments that arrived after it opened.

        A hosted tool's input may stream in fragments after the call started, so the row opens knowing only the tool's
        name. This is where the query it really ran appears, before the row is closed.

        Args:
            call_id: Identifier the matching result will carry.
            arguments: What the call turned out to be, which the chain phrases.
        """
        entry = next(
            (item for item in reversed(self.entries) if isinstance(item, ToolEntry) and item.call_id == call_id), None
        )
        if entry is None:
            return
        entry.title = self.renderers.describe(entry.tool, arguments).title
        self._changed(entry)

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
        # An unknown status is refused before the row is touched at all.
        outcome = EntryStatus(status)
        entry.text = limit_output(self.renderers.body(entry.tool, output))
        self.renderers.finished(entry, entry.text)
        entry.finish(outcome, self.clock())
        self._changed(entry)
        # The loop calls the model again once the batch has produced its
        # results, so the reader is told that work continues.
        if wait:
            self.wait_for_model()
