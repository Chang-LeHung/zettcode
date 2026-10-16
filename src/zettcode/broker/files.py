"""Where the broker keeps its files, and the note a session reads to find it.

``broker.json`` says which port the broker picked, the credential for it and the protocol it speaks,
``broker.lock`` is what makes it a singleton (see :mod:`zettcode.filelock`) and ``broker.log`` is where a broker
started in the background writes.

The broker picks its own port, so something has to say which. The token is the credential — a connection that
cannot say it is dropped — so the note is readable by its owner only, inside a directory only its owner lists,
and it is replaced in one step so a reader never sees half of it. A note can outlive its broker (a process that
was killed cannot tidy up), so finding one is only a hint: the session connects, and a refusal means there is no
broker and a new one is started.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

#: Names inside the broker's directory.
NOTE_FILE = "broker.json"
LOCK_FILE = "broker.lock"
LOG_FILE = "broker.log"

#: The module the broker runs as (``python -m zettcode.broker``): how a process is recognised as one before it is
#: ended, and what a session starts.
MODULE = "zettcode.broker"

#: Overrides where the broker lives; how a test gives each run a directory of its own.
DIRECTORY_VARIABLE = "ZETTCODE_BROKER_DIR"


@dataclass(frozen=True, slots=True)
class Note:
    """Where the broker is and the credential for it."""

    pid: int
    port: int
    token: str
    version: int


def broker_dir() -> Path:
    """Return the broker's directory: ``$ZETTCODE_BROKER_DIR``, or ``~/.zettcode/broker``.

    Looked up when asked rather than when the module is imported, so a change of home or of the variable is
    honoured.
    """
    override = os.getenv(DIRECTORY_VARIABLE)
    return Path(override).expanduser() if override else Path.home() / ".zettcode" / "broker"


def note_path(directory: Path) -> Path:
    return directory / NOTE_FILE


def lock_path(directory: Path) -> Path:
    return directory / LOCK_FILE


def log_path(directory: Path) -> Path:
    return directory / LOG_FILE


def ensure_directory(directory: Path) -> None:
    """Make the broker's directory, readable by its owner only."""
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created and os.name != "nt":
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass


def _whole(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def read_note(directory: Path) -> Note | None:
    """Return what the broker left, or ``None`` when there is nothing usable.

    A missing file, one that is not JSON, one that is not an object, and one with a field of the wrong type are
    all the same answer: nobody to talk to.
    """
    try:
        raw = json.loads(note_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    pid, port, token, version = raw.get("pid"), raw.get("port"), raw.get("token"), raw.get("version")
    if not (_whole(pid) and _whole(port) and _whole(version)):
        return None
    if not isinstance(token, str) or not token or not 0 < port < 65536 or pid <= 0:
        return None
    return Note(pid, port, token, version)


def write_note(directory: Path, note: Note) -> None:
    """Write the note in one replace. ``mkstemp`` makes its file 0600, so the token is never on disk with wider rights."""
    ensure_directory(directory)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".broker-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": note.pid, "port": note.port, "token": note.token, "version": note.version}, handle)
        os.replace(temporary, note_path(directory))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def remove_note(directory: Path, token: str) -> bool:
    """Remove the note if it is still this broker's, and say whether it was removed.

    A broker that is slow to exit must not delete the note of the one that replaced it.
    """
    current = read_note(directory)
    if current is None or current.token != token:
        return False
    try:
        note_path(directory).unlink()
    except OSError:
        return False
    return True
