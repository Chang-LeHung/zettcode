"""Holding the cyclic garbage collector off while a burst of long-lived objects is built.

Reading a session creates hundreds of thousands of objects that will live as long as
the session does and that nothing will ever collect: parsed records, their envelopes,
the rows built from them. The collector cannot know that. Each time the allocation
count crosses its threshold it walks what was allocated since the last pass, and on a
burst this size it does so over and over — about a tenth of the whole resume, in a
measurement with the collector switched off for the same work.

Pausing it for the length of the burst costs nothing that matters here: none of those
objects is cyclic garbage, and the pause is a few hundred milliseconds. It is a count,
not a flag, because the command line's build and an in-app resume can overlap, and the
collector must come back on only when the last holder lets go — and only if it was on
to begin with.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Generator
from contextlib import contextmanager

_lock = threading.Lock()
_holders = 0
_was_enabled = False


@contextmanager
def collector_paused() -> Generator[None, None, None]:
    """Keep the cyclic collector off for the body, and restore it as it was afterwards."""
    global _holders, _was_enabled
    with _lock:
        if _holders == 0:
            _was_enabled = gc.isenabled()
            gc.disable()
        _holders += 1
    try:
        yield
    finally:
        with _lock:
            _holders -= 1
            if _holders == 0 and _was_enabled:
                gc.enable()
