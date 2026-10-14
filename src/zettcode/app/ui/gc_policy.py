"""When the cyclic garbage collector may run: while the program is working, never while the reader types.

A collection stops everything, and what it costs is the size of what it has to walk. With the model
SDKs loaded that is a heap of about 380,000 objects, and one full pass over it measured 90 ms
(115 ms at worst): six dropped frames, landing wherever it happened to fall. Two things take it out of
the reader's way.

* The long-lived heap is frozen once the runtime has warmed (:func:`freeze_long_lived`). Those
  objects — the SDKs, the widget tree — never die, so the collector has no reason to look at them
  again: the same full pass took 0 ms afterwards, and a collection that did fall in a long streaming
  turn went from 57 ms to 9 ms. Freezing only stops the *cyclic* collector from walking them; a frozen
  object is still freed the moment its last reference goes.
* The collector is switched on only while something is running, and off while the reader types
  (:class:`CollectorPolicy`). Raising the threshold (``cli.GC_YOUNG_THRESHOLD``) makes a collection
  rare; this makes it *impossible* at the one moment a pause is felt. A keystroke that lands on a
  collection is a stutter in the thing the reader is looking at, and nothing has to run then.

A restore of a large session already holds the collector off for its burst of long-lived objects
(:mod:`zettcode.collector`); the policy yields to that rather than undoing it.

Nothing is lost by leaving it off. CPython keeps counting allocations while the collector is
disabled, so the first allocation after it is switched back on collects whatever piled up in
between: garbage is delayed, never dropped, and what an idle shell and a few keystrokes leave behind
is small.
"""

from __future__ import annotations

import asyncio
import gc
from collections.abc import Callable
from time import monotonic

from ...collector import held

#: Seconds after the last keystroke before the collector may run again, while work is in flight. Long
#: enough to bridge the gap between two words, short enough that a reader who has stopped to think
#: does not leave garbage waiting.
TYPING_GRACE = 0.5


def freeze_long_lived() -> None:
    """Take everything that exists now out of the collector's reach.

    Called when the runtime has finished loading: from then on the SDKs and the interface are part of
    the permanent heap. Nothing is collected first. A pass costs the very pause being avoided, and
    what it would find is about a hundred unreachable objects from import time, which stay as they are.
    """
    gc.freeze()


class CollectorPolicy:
    """Switch the collector with what the program is doing.

    Three states, none of them held anywhere but in the collector itself:

    * **resting** — nothing is running. Off.
    * **working** — a turn, a command, or a restore is in flight. On.
    * **typing** — working, but the reader pressed a key less than ``grace`` seconds ago. Off, until
      they stop.

    Args:
        grace: Seconds of quiet that end *typing*.
        clock: Time source, for tests.
    """

    def __init__(self, *, grace: float = TYPING_GRACE, clock: Callable[[], float] = monotonic) -> None:
        self.grace = grace
        self.clock = clock
        self._working = False
        self._quiet_at = float("-inf")
        self._timer: asyncio.TimerHandle | None = None

    def rest(self) -> None:
        """Nothing is running: the collector goes off."""
        self._working = False
        self._apply()

    def work_started(self) -> None:
        """Something started running: the collector goes on, unless the reader is mid-word."""
        self._working = True
        self._apply()
        self._watch()

    def work_ended(self) -> None:
        """The work is over: the collector goes off, and any wait for the reader to stop is dropped."""
        self._working = False
        self._cancel()
        self._apply()

    def typed(self) -> None:
        """The reader pressed a key: the collector goes off now, and comes back once they pause.

        Cheap on purpose, because it runs on every keystroke: it only moves a deadline, and arms one
        timer when none is waiting. With nothing running the collector is already off and there is
        nothing to wait for.
        """
        if not self._working:
            return
        self._quiet_at = self.clock() + self.grace
        gc.disable()
        self._watch()

    def close(self) -> None:
        """The program is leaving: put the collector back on, so nothing after this runs without it."""
        self._working = False
        self._cancel()
        gc.enable()

    # -- internals ---------------------------------------------------------------------------
    def _apply(self) -> None:
        """Put the collector in the state the facts above call for.

        Never on while a burst holds it off (:func:`~zettcode.collector.collector_paused`, which
        restores what it found when the last holder lets go: a moment later, the busy state that
        called for the collector to be on has ended and this puts it right).
        """
        if self._working and self.clock() >= self._quiet_at and not held():
            gc.enable()
        else:
            gc.disable()

    def _watch(self) -> None:
        """Arm the timer that ends *typing*, when work is in flight and the reader is in the middle of it."""
        if not self._working or self._timer is not None or self.clock() >= self._quiet_at:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop to wake us: the collector stays off, which is the safe way to be wrong. The
            # next change of state puts it right.
            return
        self._timer = loop.call_later(max(0.0, self._quiet_at - self.clock()), self._wake)

    def _wake(self) -> None:
        """The timer fired: end *typing* if the reader has really stopped, otherwise wait for the rest."""
        self._timer = None
        if self.clock() < self._quiet_at:
            self._watch()
            return
        self._apply()

    def _cancel(self) -> None:
        """Drop the pending timer, if any."""
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
