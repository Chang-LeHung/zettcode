"""Ending a broker that is in the way: only one of ours, and only once it has let go of its lock.

A session that finds a broker speaking an older protocol cannot talk to it and cannot start a second one beside
it (the lock is held), and the old one stays until its last session leaves, which may be hours. The way out is to
end it. That is a process id read from a file anyone could have written, or one that was reused by something
else since, so nothing is ended that is not recognised first: the command line has to be ``python -m <module>``
for the broker's module, and a process whose command line cannot be read is left alone.
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable

from ..processes import runs_module

#: Seconds an asked-nicely broker has to finish before it is made to.
GRACE = 3.0

#: Seconds a broker that was made to stop has to let go of its lock.
FORCE = 2.0

#: How often the lock is looked at while waiting.
POLL = 0.05


def end(pid: int, module: str, *, released: Callable[[], bool], grace: float = GRACE, force: float = FORCE) -> bool:
    """End a broker that runs ``python -m module`` and wait until it has let go of its lock.

    It is asked to stop first (SIGTERM), which it answers by closing its connections, so that its sessions look for
    the next broker at once; only one that has not let go within ``grace`` seconds is killed.

    Args:
        pid: The process the broker's note names.
        module: The module it runs as.
        released: Whether the broker's lock is free; the one answer that cannot be wrong about whether it has gone.
        grace: Seconds to give it to leave.
        force: Seconds to give it after it was killed.

    Returns:
        Whether the lock is free now. ``False`` also covers a process that was not recognised, which is not touched.
    """
    if released():
        return True
    if not runs_module(pid, module):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return released()
    if _wait(released, grace):
        return True
    if runs_module(pid, module):  # still the same process: it did not listen
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    return _wait(released, force)


def _wait(released: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if released():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL)
