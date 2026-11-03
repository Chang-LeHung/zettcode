"""An exclusive lock on a file, which the operating system lets go of when the holder dies.

It makes the session broker a singleton and marks a session as open in one terminal. Starting the broker is a
race — two sessions launched together both find nobody home and both start one — so the one that gets the lock
keeps running and the other exits. A lock on a file is what
makes that safe: unlike a pid written into a file, it cannot go stale. A holder that was killed
releases it with the rest of its descriptors, and the next one takes it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import IO

#: How often a caller that is willing to wait looks at the lock again.
POLL_SECONDS = 0.02


class SingletonLock:
    """An exclusive, non-blocking lock on one file, held until :meth:`release` or the process ends.

    The platform's own call is imported where it is used: ``fcntl`` exists only on POSIX and
    ``msvcrt`` only on Windows, and the module has to import on both.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        """Return whether this object holds the lock now."""
        return self._file is not None

    def acquire(self, wait: float = 0.0) -> bool:
        """Take the lock if nobody holds it, and say whether it was taken.

        Args:
            wait: Seconds to keep trying when somebody holds it. A client that is only *looking* (see
                :func:`is_held`) takes the lock for an instant, and a holder that arrives at that
                instant must not conclude that another holder exists; a short wait tells the two apart.
        """
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            if self._try():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_SECONDS)

    def _try(self) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115 - the handle is the lock, and outlives this call
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined,unused-ignore]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def still_ours(self) -> bool:
        """Return whether the file at this path is still the one this lock is held on.

        Somebody who deletes the directory by hand removes the lock file out from under a running holder, and
        the next one to start would create a new file and take a lock on *that*: two holders, each the only one
        holding its own lock. A holder that checks now and then can see it happened and step aside. Where a file that is open cannot be deleted (Windows), it is always true.
        """
        handle = self._file
        if handle is None:
            return False
        if os.name == "nt":
            return True
        try:
            here, there = os.stat(self.path), os.fstat(handle.fileno())
        except OSError:
            return False
        return (here.st_ino, here.st_dev) == (there.st_ino, there.st_dev)

    def release(self) -> None:
        """Let go of the lock; safe to call when it is not held, and safe to call twice."""
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined,unused-ignore]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


def is_held(path: Path) -> bool:
    """Return whether some process holds the lock at ``path`` right now.

    This is the one reliable way to ask whether a broker is alive: unlike a process id in a file (which
    outlives the process, and may be reused by another) or a port number (which may belong to anything
    by now), the lock is the operating system's own record, and it disappears with the holder however
    the holder died. The answer is a snapshot, and the lock is taken for an instant to find it out.
    """
    probe = SingletonLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True
