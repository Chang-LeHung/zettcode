"""Reading a running process's command line, so one of this program's own can be told from another program.

A process id in a file anyone could have written is not a name: it can be stale, and the operating system reuses ids.
So a process is acted on only after its command line has been read and recognised as ``python -m <module>`` — the one
shape that makes it ours. This module is the part of that which does not know what a broker or a gateway is, shared by
both so there is one spelling of it.

It imports the standard library only (and not ``psutil``: the command line is readable with the tools the system
already has), and it is a leaf, so a package that owns a process may use it without reaching into another's.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any


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


def is_module_command(text: str, module: str) -> bool:
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
    return text is not None and is_module_command(text, module)


def still_there(pid: int) -> bool:
    """Return whether a process with that id exists, without signalling it.

    This is the question that is left when a command line cannot be read: a process that is there but unreadable is
    not the same as one that is gone, and ending (or replacing) the wrong one is worse than reporting the doubt.
    On Windows ``os.kill(pid, 0)`` is not a probe — it terminates the process — so the process table is asked through
    ``OpenProcess`` instead. Only ``ERROR_INVALID_PARAMETER`` means "no such process"; a refusal for lack of rights,
    and any other failure, still counts as it being there.
    """
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return int(ctypes.get_last_error()) != 87  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


#: Bound the first time a Windows process is asked about; ``None`` everywhere else.
_KERNEL32: Any = None


def _kernel32() -> Any:
    """Return the one kernel32 binding, with the process calls typed once rather than per question."""
    global _KERNEL32
    if _KERNEL32 is None:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        _KERNEL32 = kernel32
    return _KERNEL32


__all__ = ["command_line", "is_module_command", "runs_module", "still_there"]
