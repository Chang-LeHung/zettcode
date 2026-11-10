"""The harness a session borrowed from another session, if any.

The page lists harness folders; choosing one points this session at that folder instead of its own. The mapping is
kept here rather than in the frame, so the harness extension and the command read the same value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Service name under which the plugin provides the choices.
HARNESS_CHOICES = "harness-choices"


@dataclass(frozen=True, slots=True)
class HarnessChoice:
    """One borrowed harness: the session it belongs to and its directory."""

    session_id: str
    directory: Path


class HarnessChoices:
    """Map a session to another session's harness, and tell the extension when it changes."""

    def __init__(self) -> None:
        self._choices: dict[str, HarnessChoice] = {}
        self._listeners: list[Callable[[str], None]] = []

    def target(self, session_id: str) -> HarnessChoice | None:
        """Return the harness this session borrowed, or ``None`` for its own."""
        return self._choices.get(session_id)

    def directory(self, session_id: str) -> Path | None:
        """Return the borrowed harness directory, or ``None`` to use the session's own."""
        choice = self._choices.get(session_id)
        return None if choice is None else choice.directory

    def select(self, session_id: str, target: str, directory: Path) -> None:
        """Borrow ``target``'s harness for ``session_id``, unless it already is the choice."""
        current = self._choices.get(session_id)
        if current is not None and current.session_id == target and current.directory == directory:
            return
        self._choices[session_id] = HarnessChoice(target, directory)
        self._changed(session_id)

    def clear(self, session_id: str) -> None:
        """Return the session to its own harness, if it borrowed one."""
        if self._choices.pop(session_id, None) is not None:
            self._changed(session_id)

    def add_listener(self, listener: Callable[[str], None]) -> None:
        """Call ``listener`` after a session's choice changes; the harness uses it to forget the old host."""
        self._listeners.append(listener)

    def _changed(self, session_id: str) -> None:
        for listener in tuple(self._listeners):
            listener(session_id)
