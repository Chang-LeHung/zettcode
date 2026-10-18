"""Ending a broker that is in the way: only one of ours, and only once it has let go of its lock.

A session that finds a broker speaking an older protocol cannot talk to it and cannot start a second one beside
it (the lock is held), and the old one stays until its last session leaves, which may be hours. The way out is to
end it. That is a process id read from a file anyone could have written, or one that was reused by something
else since, so nothing is ended that is not recognised first: the command line has to be ``python -m <module>``
for the broker's module, and a process whose command line cannot be read is left alone.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable

#: Seconds an asked-nicely broker has to finish before it is made to.
GRACE = 3.0

#: Seconds a broker that was made to stop has to let go of its lock.
FORCE = 2.0

#: How often the lock is looked at while waiting.
POLL = 0.05


def command_line(pid: int) -> str | None:
    """Return the command line of a running process, or ``None`` when it is gone or cannot be read.

    Asked of the operating system, because a process id is not a name: ``ps`` on POSIX, PowerShell's process
    table on Windows. Neither is guaranteed to exist, and not finding out is an answer the caller handles by
    doing nothing.
    """
    if pid <= 0 or pid == os.getpid():
        return None
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
        ]
    else:
        command = ["ps", "-ww", "-o", "command=", "-p", str(int(pid))]  # -ww: no cut at the width of a terminal
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    return text if done.returncode == 0 and text else None


def _is_module_command(text: str, module: str) -> bool:
    """Return whether a command line is a Python interpreter started with ``-m module`` and nothing else in the way.

    The ``-m`` has to follow the interpreter directly (single-letter options such as ``-u`` may sit between), so
    ``python -c "..." -m module`` and ``python script.py -m module`` — a different program with a flag that
    happens to read the same — are not taken for it. The path to the interpreter may hold spaces, and on Windows
    it is quoted.
    """
    # Before the interpreter there is only its path: a space followed by a dash would be an option of some other
    # program (``sh -c python -m module`` is a shell, not the module).
    pattern = rf"^(?:\S|\s(?!-))*?python[\d.]*(?:\.exe)?\"?\s+(?:-[A-Za-z]\s+)*-m\s+{re.escape(module)}(?:\s|$)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def runs_module(pid: int, module: str) -> bool:
    """Return whether the process is ``python -m module``: the one thing that makes it ours to end."""
    text = command_line(pid)
    return text is not None and _is_module_command(text, module)


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
