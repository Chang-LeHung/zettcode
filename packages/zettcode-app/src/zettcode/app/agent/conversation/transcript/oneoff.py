"""One-off rows: a banner, a notice, an error, an announcement, a block of Markdown.

None of these is part of a request. They are written once, land where the log puts
them, and never change — so they need nothing from the wait row or the clock, only
the log's ``_add``.
"""

from __future__ import annotations

from ..entries import EntryKind, MarkdownEntry, NoticeLevel, TextEntry
from .log import EntryLog


class OneOffMixin(EntryLog):
    """Append the rows that say one thing and stay as they are."""

    def welcome(self, text: str) -> None:
        """Append the banner shown once at startup."""
        self._add(TextEntry(id=self._next_id, kind=EntryKind.WELCOME, text=text))

    def notice(self, text: str) -> None:
        """Append a muted one-off status line."""
        self._add(TextEntry(id=self._next_id, kind=EntryKind.NOTICE, text=text))

    def error(self, text: str) -> None:
        """Append a one-off failure line, painted as an error."""
        self._add(TextEntry(id=self._next_id, kind=EntryKind.NOTICE, text=text, level=NoticeLevel.ERROR))

    def announce(self, text: str) -> None:
        """Announce a change as one centered line between horizontal rules."""
        self._add(TextEntry(id=self._next_id, kind=EntryKind.ANNOUNCEMENT, text=text))

    def model_changed(self, previous: str, current: str) -> None:
        """Announce a model change in the conversation; an empty previous is the first model there has been."""
        self.announce(f"Model changed from {previous} to {current}." if previous else f"Model set to {current}.")

    def permission_changed(self, previous: str, current: str) -> None:
        """Announce a shell-permission change the way a model change is shown."""
        self.announce(f"Shell permission changed from {previous} to {current}.")

    def effort_changed(self, previous: str, current: str) -> None:
        """Announce a reasoning-effort change the way a model change is shown."""
        self.announce(f"Reasoning effort changed from {previous} to {current}.")

    def markdown(self, text: str) -> None:
        """Append a Markdown block, parsed and rendered like an answer.

        Use it for command output, which is usually a list or a table; a notice
        is the terse alternative for one-line status such as ``stopped``.
        """
        entry = MarkdownEntry(id=self._next_id, kind=EntryKind.MESSAGE)
        entry.markdown.append(text)
        entry.text = text
        self._add(entry)
