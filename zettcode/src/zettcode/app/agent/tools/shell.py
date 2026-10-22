"""The shell tool: run one command in the working directory, bounded in time and in what comes back.

The command's two streams go to files and not into memory, so the volume of output costs nothing, and what is
returned is a preview of each (see :func:`~zettcode.app.agent.tools.output.stream_preview`). When a preview had to cut
something, the files are kept and the result ends with a note naming them, which the model can read; otherwise they
are removed. A command that fails or runs out of time is reported as an error that carries its output.

At the ``safe`` permission level the command is rewritten to run inside the sandbox (see
:class:`~zettcode.app.agent.tools.boundary.Boundary`).
"""

from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from pathlib import Path
from typing import Annotated

from pydantic import Field
from zett_agent.tools.base import AgentTool, tool

from .boundary import Boundary
from .output import Preview, stream_preview
from .workspace import Located

#: Where a command's kept output goes, inside the working directory. The extension that moves it out of the reader's
#: project (``ToolOutputExtension``) names the same folder.
OUTPUT_ROOT = ".zett-tool-output"

#: The runtime a command is given unless the model asks for another, and the most it may ask for.
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300

Command = Annotated[str, Field(min_length=1)]
TimeoutSeconds = Annotated[int, Field(ge=1, le=MAX_TIMEOUT_SECONDS)]


class CommandFailed(RuntimeError):
    """A command that exited with a code other than 0, or ran out of time. The message carries what it printed."""


def _compose(stdout: Preview, stderr: Preview, kept: tuple[Path, Path] | None, directory: Path) -> str:
    """Join the two previews into the text a result carries, with the note that names the kept files if there are any."""
    sections: list[str] = []
    if stdout.text:
        sections.append(stdout.text)
    if stderr.text:
        sections.append(f"[stderr]\n{stderr.text}")
    composed = "\n".join(sections)
    if kept is not None:
        first, second = (path.relative_to(directory).as_posix() for path in kept)
        composed += f"\n... [output truncated; full streams kept at {first} and {second}]"
    return composed


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Kill a command and every process it started, and wait for it to be gone."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


async def run_command(command: str, timeout_seconds: int) -> str:
    """Run ``command`` in the working directory and return what it printed.

    Raises:
        ValueError: The command is blank.
        CommandFailed: It exited with a code other than 0, or did not finish in ``timeout_seconds``; the message
            carries its output either way.
    """
    if not command.strip():
        raise ValueError("Shell command cannot be blank")
    root = Located.of(OUTPUT_ROOT)
    # No await between making the root and making the folder in it: the extension that tidies an empty root away
    # runs on this loop, so it can never see the one without the other.
    root.path.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="shell-", dir=root.path))
    stdout_file, stderr_file = folder / "stdout.txt", folder / "stderr.txt"
    timed_out = False
    # File descriptors rather than pipes keep memory bounded however much is printed. The two streams stay
    # separate: how they interleaved is not kept.
    with stdout_file.open("wb") as stdout_target, stderr_file.open("wb") as stderr_target:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=root.directory,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout_target,
            stderr=stderr_target,
            start_new_session=os.name == "posix",
        )
        try:
            await asyncio.wait_for(process.wait(), timeout_seconds)
        # ``asyncio.TimeoutError`` is the builtin from 3.11 on and a class of its own before.
        except (TimeoutError, asyncio.TimeoutError):
            await _stop(process)
            timed_out = True
        except asyncio.CancelledError:
            await _stop(process)
            raise
    stdout, stderr = stream_preview(stdout_file), stream_preview(stderr_file)
    truncated = stdout.truncated or stderr.truncated
    composed = _compose(stdout, stderr, (stdout_file, stderr_file) if truncated else None, root.directory)
    if not truncated:
        stdout_file.unlink()
        stderr_file.unlink()
        folder.rmdir()
    if timed_out:
        plural = "" if timeout_seconds == 1 else "s"
        raise CommandFailed(f"Command timed out after {timeout_seconds} second{plural}\n{composed}")
    code = process.returncode if process.returncode is not None else -1
    if code != 0:
        raise CommandFailed(f"Command exited with code {code}\n{composed}")
    return composed


def shell_tool(boundary: Boundary | None = None) -> AgentTool:
    """Return the ``bash`` tool.

    Args:
        boundary: What decides, at each command, whether it runs inside a sandbox. ``None`` runs every command
            as it was given. A command that fails inside a sandbox has a note appended that names the boundary,
            because "Operation not permitted" alone sends the model round the same wall again.
    """

    @tool
    async def bash(command: Command, timeout_seconds: TimeoutSeconds = DEFAULT_TIMEOUT_SECONDS) -> str:
        """Run a shell command with captured output from the current working directory.

        Args:
            command: Shell command to execute.
            timeout_seconds: Maximum command runtime in seconds; the default is 60.

        Snippet:
            bash(command="git status --short", timeout_seconds=60)

        Guidelines:
            - Use for builds, tests, git, and searching the code: rg or grep for text, find or ls for paths. Prefer the read, write_file and edit tools for reading and changing a file.
            - Search with a narrow pattern and a path, and pipe through head when the result may be long.
            - Use only for bounded commands in a trusted working directory.
            - A non-zero exit code or a timeout is reported as an error carrying the output.
            - Output previews keep startup and final results within byte and line limits.
            - When output is truncated, read the retained files named in the hint.
        """
        sandbox = boundary.sandbox_now() if boundary is not None else None
        if sandbox is None:
            return await run_command(command, timeout_seconds)
        if not command.strip():
            raise ValueError("Shell command cannot be blank")
        try:
            return await run_command(sandbox.wrap(command), timeout_seconds)
        except CommandFailed as error:
            raise CommandFailed(f"{error}\n{sandbox.hint()}") from error

    return bash


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "OUTPUT_ROOT",
    "CommandFailed",
    "run_command",
    "shell_tool",
]
