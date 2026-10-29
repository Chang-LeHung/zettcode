"""What the shell tool asks of the permission level, and what it asks of a sandbox.

Both are abstract base classes, and the permission package subclasses them: the tools sit below it in the import
order, so the contract has to live down here, and a subclass that forgets a method fails when it is built instead of
when a command first runs. Nothing in this module imports the framework or a model library, so the permission
package can import it at start-up for free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Sandboxer(ABC):
    """A sandbox that rewrites a shell command so it runs inside it."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Return whether this machine can sandbox a command at all."""

    @abstractmethod
    def wrap(self, command: str, cwd: Path | None = None) -> str:
        """Return ``command`` as a shell line that runs sandboxed, in ``cwd`` or in the working directory.

        The directory is not a detail: the policy a sandbox writes allows one directory, and a Linux sandbox
        moves the process there itself, so a wrapper that is given the working directory runs the command where
        it is not meant to run.

        Raises:
            RuntimeError: The machine has no sandbox; check :attr:`available` first.
        """

    @abstractmethod
    def hint(self) -> str:
        """Return the note that goes after a failed sandboxed command, naming the boundary it hit."""


class Boundary(ABC):
    """The decision the shell tool defers to at every command: run it sandboxed, or as it was given.

    ``ShellPolicy`` is the implementation. The decision is read at each call and not when the tool is built, so
    ``/permission`` takes effect on the next command of a request that is already running.
    """

    @abstractmethod
    def sandbox_now(self) -> Sandboxer | None:
        """Return the sandbox the next command has to run in, or ``None`` to run it as given.

        One answer, not a flag and a sandbox read separately: a level changed between the two reads could otherwise
        hand back a flag for one and a sandbox for the other.
        """


__all__ = ["Boundary", "Sandboxer"]
