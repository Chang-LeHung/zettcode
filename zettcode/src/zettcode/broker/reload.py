"""Noticing that the broker running on this machine is older than the code that is starting, and replacing it.

A broker outlives the session that started it, so after the package is upgraded the one still running speaks the old
protocol until something ends it. A session that connects does that for itself (see :mod:`.finder`), but a person may
start ``zettcode`` only to look at a configuration, or run the gateway, and leave the old broker in place for the next
session to trip over. So every start of ``zettcode`` asks :func:`check_in_background`, which reads the broker's note
and the lock it holds — a few bytes, no network — and only when the broker is older starts a process of its own to
replace it (``zettcode broker reload``), so the start itself is never made to wait.

Nothing here ends a *newer* broker (an older program must not undo an upgrade), and nothing here stops background
agents: a broker that has some on it is left for ``zettcode broker restart``, which says what it will stop and asks.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..filelock import is_held
from .files import Note, broker_dir, ensure_directory, lock_path, log_path, read_note
from .protocol import PROTOCOL_VERSION

#: The file in the broker's directory that remembers which broker was last tried and when.
TRIED_FILE = "reload.tried"

#: Seconds before the same old broker is tried again: a broker that cannot be replaced (agents are on it, or it would
#: not stop) must not cost a process at every start of ``zettcode``.
RETRY_AFTER = 600.0


def outdated(directory: Path) -> Note | None:
    """Return the note of the running broker when it speaks an older protocol than this code, otherwise ``None``.

    A broker that is not running (no lock held) is not outdated, whatever a stale note says; one with a newer
    protocol is not either, because this program is the older one. The note is read first and the lock only looked at
    when the note is old: taking the lock for a look creates its file, and this runs on the way into every command, on
    machines that have never had a broker.
    """
    note = read_note(directory)
    if note is None or note.version >= PROTOCOL_VERSION:
        return None
    return note if is_held(lock_path(directory)) else None


def _recently_tried(directory: Path, note: Note, now: float) -> bool:
    """Whether this very broker was already tried less than :data:`RETRY_AFTER` seconds ago (the file says ``pid time``)."""
    try:
        pid, when = (directory / TRIED_FILE).read_text(encoding="utf-8").split()
        return int(pid) == note.pid and 0 <= now - float(when) < RETRY_AFTER
    except (OSError, ValueError):
        return False


def check_in_background(directory: Path | None = None, *, now: float | None = None) -> bool:
    """Start ``zettcode broker reload`` as a process of its own when the running broker is older; say whether it did.

    Never raises and never waits: this runs on the way into every command, and a broker that cannot be looked at is
    no reason to stop one from starting.
    """
    try:
        where = broker_dir() if directory is None else directory
        note = outdated(where)
        moment = time.time() if now is None else now
        if note is None or _recently_tried(where, note, moment):
            return False
        ensure_directory(where)
        (where / TRIED_FILE).write_text(f"{note.pid} {moment}", encoding="utf-8")
        options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            options["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined,unused-ignore]
            )
        else:
            options["start_new_session"] = True
        code = "from zettcode.cli import main; main()"
        # What the command says ("left alone, because agents are on it") has nowhere to be read but the broker's own
        # log, which is where `zettcode broker` already points a person who wonders why.
        with open(log_path(where), "ab") as output:
            try:
                subprocess.Popen(  # noqa: S603
                    [sys.executable, "-c", code, "broker", "reload"],
                    stdout=output,
                    stderr=output,
                    **options,
                )
            except OSError:
                # Nothing was started, so there is nothing to wait ten minutes for: the next start tries again.
                (where / TRIED_FILE).unlink(missing_ok=True)
                raise
        return True
    except Exception:  # noqa: BLE001 - a check that fails is a check that did not happen
        return False
