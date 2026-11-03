"""Work that must not hold the process, on threads nobody joins.

A launch is often abandoned before its first turn — read the screen, quit — and
what it was warming must not hold that exit open. What decides that is the kind
of thread the work runs on: the default executor's threads are joined while the
interpreter shuts down, so anything still in flight delays the process by its
whole duration — about a second for the model SDKs, seconds for a download —
while a daemon thread is left behind and the same exit takes milliseconds.
Neither leaves anything on stderr on the versions this project runs.

Two shapes of it live here: :class:`ImportPipeline`, for the modules a launch
wants before the first turn, and :class:`DaemonCall`, for one callable whose
answer may arrive after whoever asked for it has gone. Nothing is wasted either
way: what finished is a cache hit for the work that comes later, and what did not
is what that work would have paid anyway, done while the reader is reading the
first screen — a pipeline filling behind an instruction.
"""

from __future__ import annotations

import asyncio
import importlib
import threading
from collections.abc import Callable, Sequence
from typing import Generic, TypeVar


class ImportPipeline:
    """Import a list of modules, in order, on a daemon thread.

    Args:
        names: Dotted module names, imported in this order. A name that cannot be
            imported is recorded in :attr:`failures` and the list carries on: a
            module that is missing here is reported where it is actually used,
            which is where a reader can act on it.

    Note:
        :meth:`start` returns without waiting for anything, and nothing else
        waits for the thread either — a process that ends mid-list ends at once.
        :meth:`wait` is for the code that needs the modules now, on the thread
        that needs them.
    """

    def __init__(self, names: Sequence[str]) -> None:
        """Hold the list; nothing starts until :meth:`start`."""
        self._names = tuple(names)
        self._finished = threading.Event()
        self._stopped = threading.Event()
        self._on_finish: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        #: Modules that could not be imported, and why, keyed by module name.
        self.failures: dict[str, BaseException] = {}

    @property
    def names(self) -> tuple[str, ...]:
        """Return the modules this pipeline imports, in order."""
        return self._names

    @property
    def done(self) -> bool:
        """Return whether the list was worked through, or given up on."""
        return self._finished.is_set()

    def start(self, *, on_finish: Callable[[], None] | None = None) -> None:
        """Begin importing, and return without waiting for any of it.

        Args:
            on_finish: Called on the pipeline's thread once the list is done or
                given up on, so a caller can release whoever is waiting. It runs
                off the event loop and must not touch it directly; a loop that
                has closed in the meantime is not an error.
        """
        if self._thread is not None:
            return
        self._on_finish = on_finish
        self._thread = threading.Thread(target=self._run, name="zettcode-imports", daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the list is done, and report whether it finished in time."""
        return self._finished.wait(timeout)

    def stop(self) -> None:
        """Ask the thread to give up at the next module boundary, and release waiters.

        Called when the work is no longer wanted — the shell is going away and
        the imports were for a turn that will not happen. The module being
        imported is not interrupted, so the thread is never cut in half by this;
        it notices between one module and the next.
        """
        self._stopped.set()
        self._finished.set()
        self._notify()

    def _run(self) -> None:
        try:
            for name in self._names:
                if self._stopped.is_set():
                    break
                try:
                    importlib.import_module(name)
                except Exception as error:
                    # A failure here has no reader: the module is reported by
                    # whatever needed it, which can say what it was doing.
                    self.failures[name] = error
        finally:
            self._finished.set()
            self._notify()

    def _notify(self) -> None:
        """Tell the caller the list is over, from the pipeline's own thread."""
        if self._on_finish is None:
            return
        try:
            self._on_finish()
        except RuntimeError:
            # The loop this was reporting to closed while the imports ran: the
            # shell that asked for them has already gone, and nobody is waiting.
            pass


#: The value a callable hands back, of whatever type it is.
T = TypeVar("T")


class DaemonCall(Generic[T]):
    """Run one callable on a daemon thread, and wait for it without owning it.

    ``asyncio.to_thread`` does the same work, but its thread belongs to the
    interpreter's default executor, which is joined while the process shuts down:
    a call still running when the shell leaves delays the exit by its whole
    duration. Here the thread is a daemon and the signal is an event, so
    abandoning the call costs nothing — the answer is simply dropped, or picked
    up later by :meth:`peek` if it arrived after all.

    Args:
        action: Called on the thread; its return value is what :meth:`wait`
            answers.
    """

    def __init__(self, action: Callable[[], T]) -> None:
        """Hold the callable; nothing runs until :meth:`start`."""
        self._action = action
        self._thread: threading.Thread | None = None
        self._done: asyncio.Event | None = None
        self._result: T | None = None
        self._error: BaseException | None = None

    @property
    def started(self) -> bool:
        """Return whether the call is on a thread."""
        return self._thread is not None

    def start(self) -> None:
        """Begin the call and return at once, with the work on another thread."""
        if self._thread is not None:
            return
        loop = asyncio.get_running_loop()
        self._done = asyncio.Event()
        self._thread = threading.Thread(target=self._run, args=(loop, self._done), name="zettcode-call", daemon=True)
        self._thread.start()

    def _run(self, loop: asyncio.AbstractEventLoop, done: asyncio.Event) -> None:
        """Do the work, then release whoever waits, from this thread."""
        try:
            self._result = self._action()
        except BaseException as error:  # noqa: BLE001 - an answer of None covers every failure
            self._error = error
        finally:
            try:
                loop.call_soon_threadsafe(done.set)
            except RuntimeError:
                # The loop this was reporting to has closed: the shell that asked
                # for the call has already gone, and nobody is waiting.
                pass

    async def wait(self, timeout: float | None = None) -> T | None:
        """Wait for the answer, and return ``None`` if it failed or came too late."""
        if self._done is None:
            raise RuntimeError("DaemonCall.start() has not been called")
        try:
            await asyncio.wait_for(self._done.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return None if self._error is not None else self._result

    def peek(self) -> T | None:
        """Return the answer if the call has finished, without waiting for it."""
        if self._done is None or not self._done.is_set() or self._error is not None:
            return None
        return self._result
