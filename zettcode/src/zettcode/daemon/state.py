"""What the daemons leave on disk: the folder each one records itself in, and the registry of those folders.

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
``send_message(to=...)`` all take it. A :class:`Record` is one such folder; :class:`Registry` is all of them, and
:meth:`Registry.record` is the only way to a folder, created or not.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: Bumped when the meaning of a field changes, so a file written by another version is not trusted blindly.
PROTOCOL = 1

#: How long a start may take before a state file that never appeared counts as a failed spawn.
START_SECONDS = 10.0

#: What a daemon is doing, as ``list`` words it. ``starting`` is a spawn the broker has not answered yet;
#: ``stopping`` is a kill that has been asked for and not yet landed.
STATUSES = ("starting", "idle", "working", "stopping")

#: How stale a heartbeat may be and still count as alive: three times the tick the daemon writes it on.
STALE_SECONDS = 30.0

#: The names of the files one daemon's folder holds.
STATE_FILE = "state.json"
BEAT_FILE = "heartbeat"
LOG_FILE = "log"

#: The file in the daemon folder that says which workspace path the folder belongs to.
OWNER_FILE = "workspace.txt"


def pid_runs(pid: int) -> bool:
    """Return whether a process with this id exists on this machine.

    POSIX asks with signal zero. Windows cannot: ``os.kill(pid, 0)`` there *is* ``CTRL_C_EVENT``, so it would send a
    Ctrl+C rather than ask anything. It goes through the kernel's own handle instead.
    """
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        return _windows_pid_runs(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's process, so it is there
    except OSError:
        return False
    return True


def _windows_pid_runs(pid: int) -> bool:  # pragma: no cover - exercised on Windows only
    """Return whether a process with this id exists, by asking the kernel rather than signalling it."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


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
        name: The label the reader gave this daemon when starting it, if any: what it is *for*.
        permission: The shell level it runs at: ``deny``, ``safe`` or ``full``.
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
    name: str | None = None
    permission: str | None = None
    protocol: int = PROTOCOL

    @classmethod
    def load(cls, folder: Path) -> State | None:
        """Return the state recorded in ``folder``, or ``None`` when there is none to believe.

        A file that does not parse, or that names another protocol, is no answer: the folder is then reported by its
        name alone, which is enough to kill it and see it is not one of ours.
        """
        try:
            data = json.loads((folder / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("protocol") != PROTOCOL:
            return None
        known = {item.name for item in fields(cls)}
        try:
            return cls(**{key: value for key, value in data.items() if key in known})
        except TypeError:
            return None

    def save(self, folder: Path) -> None:
        """Write this state into ``folder`` atomically, so a reader never sees half of it."""
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f".state.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, folder / STATE_FILE)


class Record:
    """One daemon's folder: what it said about itself, and the proofs of life around it.

    Reading a record reads its state once, at construction, and whether the process is there: a command that lists
    ten daemons asks the disk ten times, and nothing between two reads of one record can change the answer without
    the file changing too.
    """

    def __init__(self, folder: Path) -> None:
        """Take the folder, read what is in it, and decide whether its process is still there."""
        self.folder = folder
        self.state: State | None = State.load(folder)
        self.alive = self._alive()

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Record({str(self.folder)!r}, {self.status})"

    @property
    def session_id(self) -> str:
        """Return the session the folder belongs to: the recorded one, or the folder's name."""
        return self.state.session_id if self.state is not None else self.folder.name

    @property
    def status(self) -> str:
        """Return what to show as its status: ``dead`` when the process is gone, else the state it wrote."""
        if not self.alive:
            return "dead"
        return self.state.status if self.state is not None else "unknown"

    @property
    def dead(self) -> bool:
        """Return whether this is an entry whose process is gone."""
        return not self.alive

    @property
    def log_path(self) -> Path:
        """Return the file the daemon writes its own account into."""
        return self.folder / LOG_FILE

    def seconds(self, now: float | None = None) -> float:
        """Return how long it has been running, or zero when it never said."""
        if self.state is None:
            return 0.0
        return max(0.0, (now if now is not None else time.time()) - self.state.started_at)

    def _alive(self) -> bool:
        """Return whether the process the state names is running and keeping its heartbeat.

        A pid alone is not enough: pids are reused, and a daemon that wedged now holds a file forever. The heartbeat
        is the part a wedged process stops writing, so both have to say yes.
        """
        if self.state is None or self.state.pid <= 0 or not pid_runs(self.state.pid):
            return False
        try:
            age = time.time() - (self.folder / BEAT_FILE).stat().st_mtime
        except OSError:
            return False
        return age <= STALE_SECONDS

    def save(self, state: State) -> None:
        """Write this record's state, and believe what was written."""
        state.save(self.folder)
        self.state = state

    def beat(self) -> None:
        """Write the heartbeat: proof that this process is still doing its rounds."""
        try:
            (self.folder / BEAT_FILE).write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass

    def log(self, text: str) -> None:
        """Append one line to the daemon's log; a log that cannot be written is not worth failing a daemon over."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(f"{stamp} {text}\n")
        except OSError:
            pass

    def remove(self) -> None:
        """Remove this record and the folder it lives in, leaving its session where it is."""
        shutil.rmtree(self.folder, ignore_errors=True)
        parent = self.folder.parent
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


class Registry:
    """Every daemon recorded under one root: the folders, and the workspace each folder belongs to.

    The root is ``$ZETTCODE_DAEMON_DIR`` or ``~/.zettcode/daemon``. A workspace's folders sit under a name derived
    from its path by the session store's own helper, so the two trees say the same thing about the same project.
    """

    def __init__(self, root: Path | None = None) -> None:
        """Point at a root, or at the default one."""
        self.root = root if root is not None else _default_root()

    def workspace(self, workspace: str | Path, *, create: bool = False) -> Path:
        """Return the folder this workspace's daemons are recorded in.

        Args:
            workspace: The directory the daemons work in.
            create: Make the folder and write the note saying whose it is, when it is not there yet.
        """
        # Imported here, not at the top: `engine.storage` is the session store's package, and loading it would make
        # `daemon --help` pay for the whole store. Only two path helpers are wanted, and only when a folder is.
        from ..engine.storage.layout import claim_workspace, open_workspace

        folder = open_workspace(self.root, workspace)
        if create:
            claim_workspace(folder, workspace)
        return folder

    def record(self, workspace: str | Path, session_id: str, *, create: bool = False) -> Record:
        """Return the record one daemon keeps itself in, made when ``create`` is set."""
        folder = self.workspace(workspace, create=create) / session_id
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        return Record(folder)

    def all(self) -> tuple[Record, ...]:
        """Return every daemon recorded under the root, whichever workspace it works in, in no particular order.

        A folder with no readable state is still a record: its process may be there (a crash halfway through a
        start), and a reader who wants it gone can kill it by the name of the folder.
        """
        found: list[Record] = []
        for workspace in self._folders(self.root):
            for folder in self._folders(workspace):
                if any((folder / name).exists() for name in (STATE_FILE, BEAT_FILE, LOG_FILE)):
                    found.append(Record(folder))
        return tuple(found)

    def find(self, session_id: str) -> Record | None:
        """Return the daemon whose session is ``session_id``, whichever workspace it works in."""
        return next((record for record in self.all() if record.session_id == session_id), None)

    @staticmethod
    def _folders(path: Path) -> tuple[Path, ...]:
        """Return the directories directly under ``path``, or nothing when it cannot be read."""
        try:
            return tuple(sorted(item for item in path.iterdir() if item.is_dir()))
        except OSError:
            return ()


def _default_root() -> Path:
    """Return the folder the daemons are recorded under: ``$ZETTCODE_DAEMON_DIR``, or ``~/.zettcode/daemon``."""
    override = os.getenv("ZETTCODE_DAEMON_DIR")
    return Path(override).expanduser() if override else Path.home() / ".zettcode" / "daemon"
