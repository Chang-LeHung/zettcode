"""Import modules ahead of the code that needs them, on a thread nobody awaits.

A launch is often abandoned before its first turn — read the screen, quit — and
the imports a turn would need must not hold that exit open. What decides that is
the kind of thread they run on: the default executor's threads are joined while
the interpreter shuts down, so an import still in flight delays the process by
its whole duration (about a second for the two model SDKs), while a daemon thread
is left behind and the same exit takes milliseconds. Neither leaves anything on
stderr on the versions this project runs.

Nothing is wasted either way. What the thread finished is a cache hit for the
turn that comes later, and what it did not is what that turn would have paid
anyway: the import happens while the reader is reading the first screen, which is
a pipeline filling behind an instruction.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable, Sequence


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
