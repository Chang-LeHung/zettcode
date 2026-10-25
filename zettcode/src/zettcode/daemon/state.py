"""What one background agent leaves on disk: where it lives, and what it says about itself.

A daemon's conversation is an ordinary session, so it is stored where every session is
(``~/.zettcode/sessions/<workspace>/<session-id>/`` where the layout is that of the session store); nothing here
duplicates it. This module owns the other half — the process:

    ~/.zettcode/daemon/<workspace path, levels joined with ->/
    ├── workspace.txt                 <- the path the folder belongs to, as the session store writes it
    └── <session-id>/
        ├── state.json                <- pid, status, model, effort, when it started (see :class:`State`)
        ├── heartbeat                 <- touched every few seconds: a pid that lives but has stopped working
        └── log                       <- what the daemon had to say: a failed turn, a refused message

The folder is named after the session id, so the id is the one handle a reader needs: ``daemon kill``, ``list`` and
``send_message(to=...)`` all take it. A state file whose process is gone is a *dead* entry: it is reported, and
``daemon kill`` removes it, but nothing here starts or stops anything — :mod:`~.process` does that.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ..engine.storage.layout import claim_workspace, open_workspace

#: Bumped when the meaning of a field changes, so a file written by another version is not trusted blindly.
PROTOCOL = 1

#: How long a start may take before a state file that never appeared counts as a failed spawn.
START_SECONDS = 10.0

#: What a daemon is doing, as ``list`` words it. ``starting`` is a spawn the broker has not answered yet;
#: ``stopping`` is a kill that has been asked for and not yet landed.
STATUSES = ("starting", "idle", "working", "stopping")

#: How stale a heartbeat may be and still count as alive: three times the tick the daemon writes it on.
STALE_SECONDS = 30.0

#: The file in the daemon folder that says which workspace path the folder belongs to.
OWNER_FILE = "workspace.txt"


def daemon_root() -> Path:
    """Return the folder the daemons are recorded under: ``$ZETTCODE_DAEMON_DIR``, or ``~/.zettcode/daemon``."""
    override = os.getenv("ZETTCODE_DAEMON_DIR")
    return Path(override).expanduser() if override else Path.home() / ".zettcode" / "daemon"


@dataclass(frozen=True, slots=True)
class State:
    """What one daemon says about itself, as its ``state.json`` holds it.

    Attributes:
        session_id: The session the daemon runs; its folder name, and the id a reader passes to ``kill``.
        workspace: The directory it works in, absolute.
        pid: The process id, so a live one can be found and a dead one noticed.
        status: One of :data:`STATUSES`.
        token: The word the process that spawned it waits for, so a spawn can tell its own child from an old one.
        started_at: Seconds since the epoch, for the "for 8m" column.
        model: The model it was started on, as the entry is shown; ``None`` until it has one.
        effort: The reasoning level it was started on, or ``None`` for the model's own default.
        title: The session's name, once it has one: what a reader recognises it by.
    """

    session_id: str
    workspace: str
    pid: int
    status: str
    token: str
    started_at: float
    model: str | None = None
    effort: str | None = None
    title: str | None = None
    protocol: int = PROTOCOL

    def write(self, folder: Path) -> None:
        """Write this state into ``folder`` atomically, so a reader never sees half of it."""
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "state.json"
        temporary = folder / f".state.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def read(cls, folder: Path) -> State | None:
        """Return the state recorded in ``folder``, or ``None`` when there is none to believe.

        A file that does not parse, or that names another protocol, is no answer: the entry is then reported by
        the folder name alone with an empty state, which is enough to kill it and see it is not one of ours.
        """
        try:
            data = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("protocol") != PROTOCOL:
            return None
        known = {item.name for item in fields(cls)}
        try:
            return cls(**{key: value for key, value in data.items() if key in known})
        except TypeError:
            return None


@dataclass(frozen=True, slots=True)
class Entry:
    """One folder under the daemon root: its state (when readable), and whether its process is still there.

    Attributes:
        folder: The ``<session-id>`` folder the daemon records itself in.
        state: What it wrote, or ``None`` when nothing usable is there.
        alive: Whether its process is running and has written a heartbeat recently.
    """

    folder: Path
    state: State | None
    alive: bool

    @property
    def session_id(self) -> str:
        """Return the session the folder belongs to: the recorded one, or the folder's name."""
        return self.state.session_id if self.state is not None else self.folder.name

    @property
    def dead(self) -> bool:
        """Return whether the entry is one whose process is gone."""
        return not self.alive

    @property
    def status(self) -> str:
        """Return what to show as its status: ``dead`` when the process is gone, else the state it wrote."""
        if not self.alive:
            return "dead"
        return self.state.status if self.state is not None else "unknown"

    def seconds(self, now: float | None = None) -> float:
        """Return how long it has been running, or zero when it never said."""
        if self.state is None:
            return 0.0
        return max(0.0, (now if now is not None else time.time()) - self.state.started_at)


def workspace_folder(workspace: str | Path, *, create: bool = False) -> Path:
    """Return the folder this workspace's daemons are recorded in.

    Args:
        workspace: The directory the daemons work in.
        create: Make the folder and write the note saying whose it is, when it is not there yet.
    """
    root = daemon_root()
    folder = open_workspace(root, workspace)
    if create:
        claim_workspace(folder, workspace)
    return folder


def session_folder(workspace: str | Path, session_id: str, *, create: bool = False) -> Path:
    """Return the folder one daemon records itself in; created when ``create`` is set."""
    folder = workspace_folder(workspace, create=create) / session_id
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def entries() -> tuple[Entry, ...]:
    """Return every daemon recorded under the root, whichever workspace it works in, in no particular order.

    A folder with no readable state is still an entry: its process may be there (a crash halfway through a start),
    and a reader who wants it gone can kill it by the name of the folder.
    """
    root = daemon_root()
    found: list[Entry] = []
    try:
        workspaces = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return ()
    for workspace in workspaces:
        try:
            folders = sorted(path for path in workspace.iterdir() if path.is_dir())
        except OSError:
            continue
        for folder in folders:
            state = State.read(folder)
            if state is None and not _looks_like_a_daemon(folder):
                continue
            found.append(Entry(folder, state, alive(folder, state)))
    return tuple(found)


def _looks_like_a_daemon(folder: Path) -> bool:
    """Return whether a folder holds a daemon that never managed to write its state: a log, or a heartbeat."""
    return any((folder / name).exists() for name in ("log", "heartbeat", "state.json"))


def alive(folder: Path, state: State | None) -> bool:
    """Return whether the process the state names is running and keeping its heartbeat.

    A pid alone is not enough: pids are reused, and a daemon that wedged before it could write anything still holds
    a file. The heartbeat is the part a wedged process stops writing, so both have to say yes.
    """
    if state is None or state.pid <= 0:
        return False
    if not pid_runs(state.pid):
        return False
    beat = folder / "heartbeat"
    try:
        age = time.time() - beat.stat().st_mtime
    except OSError:
        return False
    return age <= STALE_SECONDS


def pid_runs(pid: int) -> bool:
    """Return whether a process with this id exists on this machine."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's process, so it is there
    except OSError:
        return False
    return True


def beat(folder: Path) -> None:
    """Write the heartbeat: proof that this process is still doing its rounds."""
    try:
        (folder / "heartbeat").write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def log_line(folder: Path, text: str) -> None:
    """Append one line to the daemon's log; a log that cannot be written is not worth failing a daemon over."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with (folder / "log").open("a", encoding="utf-8") as log:
            log.write(f"{stamp} {text}\n")
    except OSError:
        pass


def remove(folder: Path) -> None:
    """Remove a daemon's folder and everything in it, leaving its session where it is."""
    import shutil

    shutil.rmtree(folder, ignore_errors=True)
    parent = folder.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
