"""The ordered list of entries, and the bookkeeping every verb on it shares.

Whatever the transcript does to the conversation comes down to four things: put an
entry in, change one, drop the old ones, and tell the view what moved. This is the
part that is the same for all of them, and nothing here knows what a tool call or an
answer is — the verbs that do are the mixins in this package, each of which inherits
:class:`EntryLog` to be type-checked against the surface it shares with the rest.

It holds exactly one rule about order, because the list cannot be kept without it:
while a request runs, its wait row is the last entry, and everything new lands above.
"""

from __future__ import annotations

from typing import TypeVar

from ..entries import Entry, WaitEntry

#: The entry subtype an add/look-up call works with, pinned by the caller.
E = TypeVar("E", bound=Entry)

#: Smallest batch a trim drops, so the list shift and the view rebuild that
#: follow a trim are paid once per several appends instead of per append. The
#: real batch is a share of the cap, so a large cap trims off more at a time.
MIN_TRIM_SLACK = 8

#: Share of the cap the list may grow past before a trim: 1/32 of it. Small caps
#: keep a proportionally small overrun, large caps trim fewer times.
TRIM_SLACK_SHARE = 32


class EntryLog:
    """An ordered list of entries that knows what changed in it since it was last read.

    Attributes:
        entries: The conversation, oldest first.
        version: Moves whenever anything in the list changed, which is what a view
            compares to know it has to look again.
        max_entries: How many entries are kept for display.
    """

    def __init__(self, *, max_entries: int) -> None:
        """Start an empty list that keeps at most ``max_entries`` entries on display.

        Args:
            max_entries: Conversation entries kept for display; older ones are
                dropped, while the session file keeps the whole tree. Must be
                positive.
        """
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.entries: list[Entry] = []
        self.max_entries = max_entries
        self._trim_threshold = max_entries + max(MIN_TRIM_SLACK, max_entries // TRIM_SLACK_SHARE)
        self.version = 0
        self._next_id = 1
        # Where the current request's own rows begin: the wait row is opened
        # against the content already there, and everything above it until the
        # next request is this request's work. The animation walks this range
        # and no further, so a step's cost follows the request, not the session.
        self._turn_from = 0
        # Earliest entry touched since the view last took the mark, so it can
        # re-measure only the changed suffix instead of the whole transcript.
        self._dirty_from: int | None = None

    # -- telling the view what moved ------------------------------------------
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

    def _changed(self, entry: Entry) -> None:
        """Say that an entry was edited in place: mark it, and move the version.

        Every verb that changes a row ends here, so the mark and the version cannot
        be updated one without the other.
        """
        self._touch_entry(entry)
        self.version += 1

    # -- where an entry goes --------------------------------------------------
    def _open_wait(self) -> WaitEntry | None:
        """Return the wait row while it is open, which is what keeps it pinned.

        The row is the last entry for as long as the request runs, so "open"
        and "at the tail" are the same thing: anything that lands below it would
        be something the reader is still waiting for.
        """
        last = self.entries[-1] if self.entries else None
        if isinstance(last, WaitEntry) and last.running:
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

    # -- finding and replacing ------------------------------------------------
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
