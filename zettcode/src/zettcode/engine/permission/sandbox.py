"""The operating-system sandbox a shell command runs in at the ``safe`` level.

``safe`` is the middle rung between asking about everything and running everything: a command runs without a
question, and what it can do is bounded by the kernel and not by anybody's reading of the command line. The
boundary is the one Codex draws for its workspace-write mode:

* it may write the workspace, and the system temporary directory (``/tmp`` and ``$TMPDIR``), and nothing else;
* it may read the rest of the machine, except the places credentials live (``~/.ssh``, ``~/.aws`` and the like);
* it has no network, unless the configuration says ``[shell] network = true``;
* the files that run code later outside it (``.git/hooks``, ``.git/config``, shell start-up files) stay read-only
  even inside the workspace.

The enforcement is ``zett-agent``'s: Seatbelt (``sandbox-exec``) on macOS and bubblewrap on Linux. Windows has
none, and neither has a Linux machine without ``bwrap``; there :attr:`ShellSandbox.available` is false and the
policy falls back to what ``safe`` was before the sandbox existed (read-only commands run, the rest ask), so the
word never promises a boundary the machine cannot draw.

The sandbox does not run the command. It rewrites it into one that starts under the sandbox's launcher, which the
shell tool then runs the way it runs any command, so the output handling, the timeout and the process-group kill
stay the framework's.
"""

from __future__ import annotations

import shlex
import sys
import tempfile
from pathlib import Path

from zett_agent.sandbox import NetworkMode, SandboxPolicy, SandboxUnavailableError, create_sandbox
from zett_agent.sandbox.base import Sandbox

from ..tools.boundary import Sandboxer

__all__ = ["ShellSandbox", "SANDBOX_HINT", "temporary_roots"]

#: Appended to the failure of a command that ran sandboxed, so the model learns the boundary instead of
#: retrying the same call: a denied write and a missing network look like a bare "Operation not permitted".
SANDBOX_HINT = (
    "[sandbox] This command ran in the `safe` sandbox: it can write only the workspace and the temporary "
    "directory{network}. If it failed for that reason, tell the user which command needs more and let them "
    "choose /permission full."
)


def temporary_roots() -> tuple[Path, ...]:
    """Return the temporary directories a sandboxed command may write: ``/tmp`` and the process's own.

    On macOS these are different places (``/tmp`` is ``/private/tmp``, and ``$TMPDIR`` is under
    ``/var/folders``); on Linux they usually coincide. Only directories that exist are returned.
    """
    candidates = [Path("/tmp"), Path(tempfile.gettempdir())]
    found: list[Path] = []
    for path in candidates:
        if path.is_dir() and path not in found:
            found.append(path)
    return tuple(found)


class ShellSandbox(Sandboxer):
    """The sandbox for one workspace: whether this machine has one, and a command rewritten to run in it."""

    def __init__(self, workspace: Path, *, network: bool = False) -> None:
        """Describe the boundary; nothing is probed until :attr:`available` is first read.

        Args:
            workspace: The directory commands run in, which they may write.
            network: Whether a sandboxed command may use the network.
        """
        self.workspace = workspace
        self.network = network
        self._sandbox: Sandbox | None = None
        self._reason: str | None = None
        self._probed = False

    def _probe(self) -> None:
        """Build the sandbox once and remember why not when the machine cannot."""
        if self._probed:
            return
        self._probed = True
        if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
            self._reason = "this platform has no sandbox; commands at `safe` are limited to read-only ones"
            return
        policy = SandboxPolicy.workspace_write(
            self.workspace,
            *temporary_roots(),
            network=NetworkMode.FULL if self.network else NetworkMode.NONE,
        )
        try:
            self._sandbox = create_sandbox(policy, require_isolation=True)
        except SandboxUnavailableError as error:
            self._reason = str(error)

    @property
    def available(self) -> bool:
        """Return whether this machine can sandbox a command."""
        self._probe()
        return self._sandbox is not None

    @property
    def boundary(self) -> Sandbox | None:
        """Return the sandbox itself, or ``None`` when this machine has none.

        For a caller that runs code *inside* one rather than rewriting a command into it: the harness starts a
        child process for the model's own tools, and at `safe` that child runs in this boundary.
        """
        self._probe()
        return self._sandbox

    @property
    def unavailable_reason(self) -> str | None:
        """Return why there is no sandbox, or ``None`` when there is one."""
        self._probe()
        return self._reason

    def wrap(self, command: str) -> str:
        """Return ``command`` as a shell line that runs it inside the sandbox.

        The environment the sandbox allows (no API keys or tokens) is spelled out with ``env -i``, because the
        shell tool starts the line with the host's own environment.

        Raises:
            RuntimeError: The machine has no sandbox; check :attr:`available` first.
        """
        self._probe()
        if self._sandbox is None:
            raise RuntimeError(self._reason or "no sandbox")
        wrapped = self._sandbox.wrap(command, cwd=Path.cwd())
        assignments = [f"{name}={value}" for name, value in wrapped.env.items()]
        return shlex.join(["env", "-i", *assignments, *wrapped.argv])

    def hint(self) -> str:
        """Return the note that goes after a failed sandboxed command."""
        return SANDBOX_HINT.format(network="" if self.network else " and has no network")
