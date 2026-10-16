"""The lock on a session: only the process that holds it may open the session to write.

A session's file is an append-only tree that "the caller is the single process owning the session" (see
:mod:`.store`) — an assumption nothing enforced. Two terminals resumed on one session each appended to it, each
holding a different idea of where the conversation had got to, and the tree forked behind both of them.

So a session is **locked** by the process that has it open. The lock is an operating-system file lock on a file
in the session's own folder (:data:`LOCK_FILE`), taken when a session becomes the active one and given up when
another does, and it goes with the process however the process ends: a crashed or killed ZettCode leaves no lock
behind to clear by hand, which a pid in a file could not promise. A process that cannot take it still shows the
session — reading is harmless — and does nothing that would write to it.

One process holds at most one session lock: the active one. Starting a new session, resuming or forking moves it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ....filelock import SingletonLock
from .records import STORE_FILE

#: The file in a session's folder the lock is taken on.
LOCK_FILE = "session.lock"

#: What a process that cannot write to a session says, for the one reader who asks why.
LOCKED_MESSAGE = "This session is open in another ZettCode process, so it is read-only here."


class SessionLocked(ValueError):
    """An attempt to write to a session that another process has open.

    A ``ValueError`` because the shell already turns one into a line in the conversation, which is what a command
    refused for this reason should be.
    """

    def __init__(self, message: str = LOCKED_MESSAGE) -> None:
        super().__init__(message)


class SessionGuard(Protocol):
    """What the runtime asks of a session lock: take it for a session, ask whether it is held, give it up."""

    def claim(self, session_id: str) -> bool:
        """Take the lock for ``session_id``, letting go of any other, and say whether it is held now."""
        ...

    def holds(self, session_id: str) -> bool:
        """Return whether this process holds the lock for ``session_id``."""
        ...

    def release(self) -> None:
        """Let go of the lock this process holds, if it holds one."""
        ...


class NoLocks:
    """The guard of a runtime with no store on disk: every claim succeeds, because nothing is shared."""

    def claim(self, session_id: str) -> bool:
        """Say that the session is held; there is nobody to hold it against."""
        return True

    def holds(self, session_id: str) -> bool:
        """Say that the session is held."""
        return True

    def release(self) -> None:
        """Hold nothing, so there is nothing to let go of."""


class SessionLocks:
    """The lock of the one session a process has open.

    Args:
        directory_of: Returns the folder of a session (the store's own ``session_dir``), which refuses an id
            that would leave the store.
    """

    def __init__(self, directory_of: Callable[[str], Path]) -> None:
        self._directory_of = directory_of
        self._lock: SingletonLock | None = None
        self._session_id: str | None = None

    @property
    def held(self) -> str | None:
        """The id of the session this process holds, or ``None``."""
        return self._session_id if self._lock is not None and self._lock.held else None

    def holds(self, session_id: str) -> bool:
        """Return whether this process holds the lock for ``session_id`` now."""
        return self.held == session_id

    def claim(self, session_id: str) -> bool:
        """Take the lock for a session and let go of the one held before, whichever way it goes.

        Asking again for the session already held is a yes and changes nothing. The session being left is
        released even when the new one cannot be had: the process is no longer working in it.

        Raises:
            ValueError: ``session_id`` is not one the store could have written.
        """
        if self.holds(session_id):
            return True
        lock = SingletonLock(self._directory_of(session_id) / LOCK_FILE)
        taken = lock.acquire()
        self.release()
        if taken:
            self._lock, self._session_id = lock, session_id
        return taken

    def release(self) -> None:
        """Let go of the lock; a session that was never written leaves no folder behind."""
        lock, session_id = self._lock, self._session_id
        self._lock = self._session_id = None
        if lock is None or session_id is None:
            return
        path = lock.path
        lock.release()
        # A new session that was left before its first message has a folder with nothing in it but this file;
        # tidying it keeps every launch that was closed unused from leaving one. A session that has data keeps
        # its lock file: the file is how the next process asks, and it is empty.
        if not (path.parent / STORE_FILE).exists():
            try:
                path.unlink()
                path.parent.rmdir()
            except OSError:
                pass
