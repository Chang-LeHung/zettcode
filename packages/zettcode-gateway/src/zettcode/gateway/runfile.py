"""The file that says a gateway is serving, so ``zettcode gateway stop`` and ``restart`` can find it.

A process id on its own is not a name: it outlives the process and the system reuses it. So the command that ends a
gateway checks the process it reads here against its command line before sending anything (see
:mod:`zettcode.processes`); this module only keeps the record — the pid and the settings the gateway is serving with,
so a restart keeps its host, port and token instead of quietly changing them.

The sign-in token is in the file because of that, which is why it is written in one replace into a folder only its
owner may list, as the broker's note is. A gateway that was killed cannot tidy up, so a record is only ever a hint:
the reader validates it, and a stale one is removed.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

from .settings import Settings

#: The record of the serving gateway, and the log a gateway started in the background writes.
RUN_FILE = "run.json"
LOG_FILE = "gateway.log"


@dataclass(frozen=True, slots=True)
class Running:
    """A gateway that left a record: the process serving, and what it was started with."""

    pid: int
    settings: Settings


def path(directory: Path) -> Path:
    """Return the record's path inside the gateway's folder."""
    return directory / RUN_FILE


def log_path(directory: Path) -> Path:
    """Return the path a gateway started in the background writes its output to."""
    return directory / LOG_FILE


def ensure_directory(directory: Path) -> None:
    """Make the gateway's folder, readable by its owner only."""
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created and os.name != "nt":
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass


def write(settings: Settings) -> None:
    """Record this process as the gateway serving ``settings``, in one replace so a reader never sees half a file."""
    ensure_directory(settings.directory)
    payload = {
        "pid": os.getpid(),
        "host": settings.host,
        "port": settings.port,
        "token": settings.token,
        "roots": [str(root) for root in settings.roots],
        "allow_full": settings.allow_full,
        "log_level": settings.log_level,
    }
    descriptor, temporary = tempfile.mkstemp(dir=settings.directory, prefix=".run-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path(settings.directory))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read(directory: Path) -> Running | None:
    """Return the recorded gateway, or ``None`` when there is no usable record.

    A missing file, one that is not JSON, one that is not an object, and one with a field of the wrong kind are all
    the same answer: nobody to stop. The pid is not checked here; whether that process is a gateway is the caller's
    question, and it is the one that must not be guessed at.
    """
    try:
        raw = json.loads(path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    pid, port = raw.get("pid"), raw.get("port")
    host, token, log_level = raw.get("host"), raw.get("token"), raw.get("log_level")
    roots, allow_full = raw.get("roots"), raw.get("allow_full")
    if not (_whole(pid) and pid > 0 and _whole(port) and 0 < port < 65536):
        return None
    if not (isinstance(host, str) and isinstance(token, str) and isinstance(log_level, str)):
        return None
    if not isinstance(allow_full, bool):
        return None
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        return None
    settings = Settings(
        token=token,
        host=host,
        port=port,
        roots=tuple(Path(root) for root in roots),
        allow_full=allow_full,
        # The folder the record was found in, not a path written inside it: a record cannot send a restart to another
        # folder.
        directory=directory,
        log_level=log_level,
    )
    return Running(pid, settings)


def clear(directory: Path, *, pid: int | None = None) -> bool:
    """Remove the record, unless it belongs to another process than ``pid``; say whether it was removed."""
    current = read(directory)
    if current is None:
        if pid is not None:
            return False
        try:
            path(directory).unlink()
            return True
        except OSError:
            return False
    if pid is not None and current.pid != pid:
        return False
    try:
        path(directory).unlink()
    except OSError:
        return False
    return True


def _whole(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["LOG_FILE", "RUN_FILE", "Running", "clear", "ensure_directory", "log_path", "path", "read", "write"]
