"""The background process, and the files that say whether it is there.

Three files live in the bridge's directory:

- ``worker.lock`` — held by the running process for as long as it runs. The operating system drops it when the
  process dies, so this is what "is a bridge running" means; a pid in a file cannot answer that, because a pid
  outlives its process while the system hands it to somebody else.
- ``worker.pid`` — the number to signal. Read only while the lock says somebody is there.
- ``worker.log`` — everything the process printed, appended across restarts so a reason is still there after
  the restart that hid it.

Starting is a handover: the new process takes the lock, and the parent waits for that before it says the bridge
is up, so a process that dies on its first line is reported instead of announced.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: How long a starting process has to take the lock, and how long it has to let go of it when told to stop.
READY_TIMEOUT = 40.0
STOP_TIMEOUT = 15.0

#: Seconds between looks at the lock while waiting for a start or a stop.
POLL = 0.1


@dataclass
class Worker:
    """The background process of one bridge, in one directory."""

    directory: Path

    @property
    def lock(self) -> Path:
        """The file the running process holds."""
        return self.directory / "worker.lock"

    @property
    def pid_file(self) -> Path:
        """The file naming the process to signal."""
        return self.directory / "worker.pid"

    @property
    def log(self) -> Path:
        """Where the process writes what it prints."""
        return self.directory / "worker.log"

    # -- what a reader asks ---------------------------------------------------------------------------
    def running(self) -> bool:
        """Return whether a bridge process is alive now."""
        from zettcode.filelock import is_held

        return is_held(self.lock)

    def pid(self) -> int | None:
        """Return the pid of the running bridge, or ``None`` when there is none."""
        if not self.running():
            return None
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def tail(self, lines: int = 40) -> str:
        """Return the end of the log, for a reader who asks why nothing happened."""
        try:
            text = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    # -- what a reader does ---------------------------------------------------------------------------
    def start(self, argv: list[str], *, timeout: float = READY_TIMEOUT) -> int:
        """Start the process and return its pid once it has taken the lock.

        Raises:
            RuntimeError: A bridge is already running, or the new process exited before it was ready; the
                message carries the end of its log, which is where the reason is.
        """
        if self.running():
            raise RuntimeError(f"a bridge is already running (pid {self.pid()}); stop it first")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.log, "a", encoding="utf-8") as log:
            log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting\n")
            log.flush()
            # Unbuffered, so what the process says before it is killed is in the log: a file is block-buffered,
            # and a start that fails early is exactly the case this log exists for.
            environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
            if os.name == "nt":  # pragma: no cover - the platform's own way of saying "not in this console's group"
                process = subprocess.Popen(  # noqa: S603 - the arguments are this program's own module and flags
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    env=environment,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            else:
                process = subprocess.Popen(  # noqa: S603 - as above
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    env=environment,
                    start_new_session=True,
                )
        self.pid_file.write_text(str(process.pid), encoding="utf-8")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.running():
                return process.pid
            code = process.poll()
            if code is not None:
                reason = self.tail(20) or f"it exited with status {code} and said nothing"
                raise RuntimeError(f"the bridge exited before it was ready:\n{reason}")
            time.sleep(POLL)
        raise RuntimeError(f"the bridge did not start within {int(timeout)} seconds; see {self.log}")

    def stop(self, *, timeout: float = STOP_TIMEOUT) -> str:
        """Stop the process and return a sentence saying what happened."""
        if not self.running():
            return "no bridge is running"
        pid = self.pid()
        if pid is None:
            return f"a bridge holds {self.lock} but left no pid to signal"
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as error:
            return f"could not signal the bridge (pid {pid}): {error}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running():
                return f"stopped the bridge (pid {pid})"
            time.sleep(POLL)
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            return f"the bridge (pid {pid}) did not stop and could not be killed"
        for _ in range(int(5 / POLL)):
            if not self.running():
                break
            time.sleep(POLL)
        return f"the bridge (pid {pid}) did not stop in {int(timeout)} seconds; it was killed"


def command(*flags: str) -> list[str]:
    """Return the command line that runs the worker: this interpreter, this program, ``run`` and ``flags``."""
    return [sys.executable, "-m", "zettcode.im.weixin.cli", "run", *flags]


__all__ = ["READY_TIMEOUT", "STOP_TIMEOUT", "Worker", "command"]
