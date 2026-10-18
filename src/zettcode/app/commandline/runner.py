"""Run one command at a time in the reader's shell and stream what it prints.

A command is run by the reader's own shell (``$SHELL -c``, PowerShell on Windows), in the directory the panel is in,
with no input — a program that asks a question gets the end of its input, and says so, instead of waiting for a
key nobody can press. Each command is a process of its own; the environment does not carry from one to the next,
except where the directory does: a bare ``cd`` is the panel's to do, because a ``cd`` in a process that is about to
exit changes nothing.

:class:`ShellLauncher` is how a shell is asked to run a string, and there is one per family: the strategy that
differs between a Unix shell, PowerShell and ``cmd`` is the arguments, and nothing else here knows which is in use.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from zettcode.tui import SEPARATOR

#: Seconds a command is given to end after Ctrl-C before it is killed.
KILL_AFTER = 3.0

#: Bytes read from the command at once, and the pause after a read that filled it. A program that prints without
#: end is slowed by a full pipe rather than by the interface: the panel keeps answering keys.
CHUNK = 16384
PAUSE = 0.01

#: Shells that take ``-c <command>`` and are worth running the reader's commands with.
POSIX_SHELLS = frozenset({"bash", "zsh", "fish", "sh", "dash", "ksh", "ash"})


class ShellLauncher(ABC):
    """How one family of shells is asked to run a string.

    Attributes:
        name: What the shell is called, shown in the panel.
        prompt: The glyph before the line the commands are typed on.
    """

    name = ""
    prompt = "$"

    @abstractmethod
    def argv(self, command: str) -> list[str]:
        """Return the program and arguments that run ``command``."""

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        """Return the environment to run in: the reader's, plus what makes programs print the way a terminal shows.

        Programs colour their output only when it goes to a terminal, and a pipe is not one, so they are told to:
        ``FORCE_COLOR`` and ``CLICOLOR_FORCE`` for the many that read them, ``CLICOLOR`` for BSD and macOS ``ls``,
        ``PY_COLORS`` for pytest and ``CARGO_TERM_COLOR`` for cargo. git reads none of those, so it is given
        ``color.ui=always`` through ``GIT_CONFIG_*``, which takes effect for the one process and leaves the reader's
        gitconfig alone (and, being ahead of it in git's order, still loses to a ``color.status = false`` of theirs).
        All of it is skipped when ``NO_COLOR`` is set, and a variable the reader already set keeps their value.
        Pager defaults assume a person at a terminal; the panel is a screen, but not one a pager can be driven from.
        """
        env = dict(base)
        env.update({"TERM": "xterm-256color", "PYTHONUNBUFFERED": "1"})
        env.setdefault("PAGER", "cat")
        env.setdefault("GIT_PAGER", "cat")
        if "NO_COLOR" in env:
            return env
        for name, value in (
            ("FORCE_COLOR", "1"),
            ("CLICOLOR", "1"),
            ("CLICOLOR_FORCE", "1"),
            ("PY_COLORS", "1"),
            ("CARGO_TERM_COLOR", "always"),
        ):
            env.setdefault(name, value)
        # git's own settings can already be coming in this way; this one goes after them.
        raw = env.get("GIT_CONFIG_COUNT", "0")
        count = int(raw) if raw.isdigit() else 0
        env[f"GIT_CONFIG_KEY_{count}"] = "color.ui"
        env[f"GIT_CONFIG_VALUE_{count}"] = "always"
        env["GIT_CONFIG_COUNT"] = str(count + 1)
        return env


class PosixLauncher(ShellLauncher):
    """bash, zsh, fish, sh and the like: ``<shell> -c <command>``.

    fish is started without its configuration. ``fish -c`` reads ``config.fish`` every time, and a configuration with
    a version manager or a prompt in it takes half a second to a second — for every command, measured at 0.6-0.9 s
    against 4 ms without. bash, zsh and sh do not read their rc files for ``-c``, so they are not slow and are not
    changed. What this costs is a fish user's own aliases and functions; the environment, ``PATH`` included, is
    inherited from the shell that started the program and is not affected.
    """

    def __init__(self, shell: str) -> None:
        self.shell = shell
        self.name = Path(shell).name

    def argv(self, command: str) -> list[str]:
        """Return ``[shell, "-c", command]``, with fish's ``--no-config`` before it."""
        if self.name == "fish":
            return [self.shell, "--no-config", "-c", command]
        return [self.shell, "-c", command]


class PowerShellLauncher(ShellLauncher):
    """Windows PowerShell and PowerShell 7: output as UTF-8, no profile, no prompts."""

    prompt = ">"

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.name = PureWindowsPath(executable).stem

    def argv(self, command: str) -> list[str]:
        """Return the arguments that run ``command`` with its output encoded as UTF-8."""
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$OutputEncoding=[Console]::OutputEncoding;" + command
        return [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]


class CommandPromptLauncher(ShellLauncher):
    """``cmd.exe``, for a machine with no PowerShell."""

    name = "cmd"
    prompt = ">"

    def __init__(self, executable: str = "cmd.exe") -> None:
        self.executable = executable

    def argv(self, command: str) -> list[str]:
        """Return ``cmd /d /c <command>``."""
        return [self.executable, "/d", "/c", command]


def detect_launcher(env: Mapping[str, str] | None = None, platform: str = sys.platform) -> ShellLauncher:
    """Return the launcher for the shell this reader has.

    On Unix that is the shell in ``$SHELL`` when it is one that takes ``-c``, so a command is read the way the
    reader writes it (a fish user's ``set -x`` is not a syntax error), otherwise bash, otherwise ``/bin/sh``. On
    Windows it is PowerShell 7, Windows PowerShell, or ``cmd``, whichever is found first.
    """
    env = os.environ if env is None else env
    if platform == "win32":
        for candidate in ("pwsh", "powershell"):
            found = shutil.which(candidate)
            if found:
                return PowerShellLauncher(found)
        return CommandPromptLauncher(env.get("COMSPEC", "cmd.exe"))
    shell = env.get("SHELL", "")
    if shell and Path(shell).name in POSIX_SHELLS and os.access(shell, os.X_OK):
        return PosixLauncher(shell)
    return PosixLauncher(shutil.which("bash") or "/bin/sh")


@dataclass(frozen=True, slots=True)
class RunResult:
    """How a command ended.

    Attributes:
        code: The exit status, or ``None`` when the command could not be started.
        seconds: How long it ran.
        stopped: It ended because the reader stopped it.
    """

    code: int | None
    seconds: float
    stopped: bool = False

    @property
    def text(self) -> str:
        """Return the outcome in a few words, for the panel's heading."""
        if self.code is None:
            return "not started"
        how = "stopped" if self.stopped else f"exit {self.code}"
        return f"{how} {SEPARATOR} {self.seconds:.1f}s"


class CommandRunner:
    """Run commands one after another in a directory, and tell the panel what each prints.

    Args:
        cwd: The directory commands run in; ``cd`` changes it.
        launcher: How the shell is asked to run a string; the reader's own shell by default.
        env: The environment commands inherit; the real one by default.
        home: What ``cd`` with no argument goes to, and ``~`` stands for.
        kill_after: Seconds a command has to end after being stopped before it is killed.
    """

    def __init__(
        self,
        cwd: Path,
        launcher: ShellLauncher | None = None,
        *,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
        kill_after: float = KILL_AFTER,
    ) -> None:
        self.cwd = cwd
        self.previous = cwd
        self.env = os.environ if env is None else env
        self.launcher = launcher or detect_launcher(self.env)
        self.home = Path.home() if home is None else home
        self.kill_after = kill_after
        self._process: asyncio.subprocess.Process | None = None
        self._stops = 0
        self._starting = False
        self._early_stop = False
        self._killer: asyncio.TimerHandle | None = None

    @property
    def running(self) -> bool:
        """Return whether a command is running now."""
        return self._process is not None and self._process.returncode is None

    # -- cd -----------------------------------------------------------------
    def change_directory(self, argument: str) -> str | None:
        """Move to a directory as ``cd`` does; return the complaint, or ``None`` when it worked."""
        try:
            words = shlex.split(argument, posix=os.name != "nt")
        except ValueError as error:
            return f"cd: {error}"
        if os.name == "nt" and words[:1] == ["/d"]:
            words = words[1:]
        if len(words) > 1:
            return "cd: too many arguments"
        target = words[0] if words else "~"
        if target == "-":
            destination = self.previous
        else:
            if target == "~" or target.startswith(("~/", "~\\")):
                target = str(self.home) + target[1:]
            destination = Path(target)
            if not destination.is_absolute():
                destination = self.cwd / destination
        try:
            destination = destination.resolve()
        except OSError as error:
            return f"cd: {target}: {error.strerror or error}"
        if not destination.is_dir():
            return f"cd: no such directory: {target}"
        self.previous, self.cwd = self.cwd, destination
        return None

    # -- running ------------------------------------------------------------
    async def run(self, command: str, write: Callable[[str], None]) -> RunResult:
        """Run ``command`` to its end, calling ``write`` with what it prints as it prints it."""
        started = time.monotonic()
        stripped = command.strip()
        if stripped == "cd" or stripped.startswith(("cd ", "cd\t")):
            error = self.change_directory(stripped[2:])
            if error is not None:
                write(error + "\n")
            return RunResult(1 if error else 0, time.monotonic() - started)
        self._stops = 0
        self._starting, self._early_stop = True, False
        try:
            process = self._process = await asyncio.create_subprocess_exec(
                *self.launcher.argv(command),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.cwd,
                env=self.launcher.environment(self.env),
                creationflags=self._flags(),
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            self._starting = False
            write(f"{self.launcher.name}: {error.strerror or error}\n")
            return RunResult(None, time.monotonic() - started)
        self._starting = False
        if self._early_stop:
            # Stopped in the moment between Enter and the process existing: it is interrupted as soon as it does.
            self.stop()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        assert process.stdout is not None
        try:
            while True:
                data = await process.stdout.read(CHUNK)
                if not data:
                    break
                write(decoder.decode(data))
                await asyncio.sleep(PAUSE if len(data) >= CHUNK // 2 else 0)
            tail = decoder.decode(b"", final=True)
            if tail:
                write(tail)
            code = await process.wait()
        finally:
            await self._reap(process)
            if self._killer is not None:
                self._killer.cancel()
                self._killer = None
        return RunResult(code, time.monotonic() - started, stopped=self._stops > 0)

    @staticmethod
    def _flags() -> int:
        """Return the Windows creation flags that put the command in a process group of its own (zero elsewhere).

        Elsewhere ``start_new_session`` does it; either way Ctrl-C can reach the command and all it started.
        """
        return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0

    # -- stopping -----------------------------------------------------------
    def stop(self) -> bool:
        """Interrupt the running command; a second call, or a command that ignores the first, kills it.

        Returns:
            Whether there was a command to stop.
        """
        process = self._process
        if process is None and self._starting:
            self._early_stop = True
            return True
        if process is None or process.returncode is not None:
            return False
        self._stops += 1
        if self._stops == 1:
            self._send(process, interrupt=True)
            with contextlib.suppress(RuntimeError):
                self._killer = asyncio.get_running_loop().call_later(self.kill_after, self._kill, process)
        else:
            self._kill(process)
        return True

    def _kill(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            self._send(process, interrupt=False)

    @staticmethod
    def _send(process: asyncio.subprocess.Process, *, interrupt: bool) -> None:
        """Signal the command's whole process group: SIGINT to ask, SIGKILL to insist."""
        try:
            if os.name == "nt":
                if interrupt:
                    process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined,unused-ignore]
                else:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False, timeout=10
                    )
            else:
                os.killpg(process.pid, signal.SIGINT if interrupt else signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            with contextlib.suppress(OSError):
                process.kill()

    async def _reap(self, process: asyncio.subprocess.Process) -> None:
        """Make sure the command is gone when :meth:`run` leaves, however it left (the panel closing, say)."""
        if process.returncode is None:
            self._send(process, interrupt=False)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), 5)
        self._process = None
