"""Opening and closing the rows that can be opened: reasoning and tool output.

This is the one thing the reader does to the transcript rather than the agent. It
changes how a row looks without changing what happened, so it only edits an entry
in place and tells the log it did.
"""

from __future__ import annotations

from ..entries import ThinkingEntry, ToolEntry
from .log import EntryLog


class FoldMixin(EntryLog):
    """Expand and collapse the reasoning and tool rows."""

    def toggle(self, entry_id: int) -> bool:
        """Expand or collapse one collapsible entry and report whether it changed.

        Args:
            entry_id: Id from the click or key that triggered the toggle; a
                running tool row, or one with no body, refuses to expand.
        """
        entry = self.entry(entry_id)
        if not isinstance(entry, (ThinkingEntry, ToolEntry)):
            return False
        if isinstance(entry, ToolEntry) and not entry.foldable:
            return False
        entry.expanded = not entry.expanded
        self._changed(entry)
        return True

    def toggle_latest_thinking(self) -> bool:
        """Expand or collapse the newest thinking block."""
        entry = self._last(ThinkingEntry)
        if entry is None:
            return False
        entry.expanded = not entry.expanded
        self._changed(entry)
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
