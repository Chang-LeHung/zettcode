"""Starting a daemon and stopping one: the process behind a folder under ``~/.zettcode/daemon``.

A daemon outlives the terminal that started it, so it is started detached: its own session on POSIX, its own
process group on Windows, no inherited standard input, and its output in a file rather than in whatever window
happened to run the command. The process that starts one waits for the daemon to say it is ready — a spawn that
returns is a session another agent can message — and takes it back when it does not.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .state import (
    START_SECONDS,
    Entry,
    State,
    alive,
    entries,
    pid_runs,
    remove,
    workspace_folder,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .run import Options

#: How long a stop may take before the process is killed outright.
KILL_GRACE = 5.0

#: How often a spawn looks for the state file its child writes.
POLL_SECONDS = 0.05

__all__ = ["KILL_GRACE", "SpawnFailed", "find", "is_alive", "kill", "spawn"]


class SpawnFailed(RuntimeError):
    """A daemon was started and never became reachable."""

    def __init__(self, said: str, log: Path | None = None) -> None:
        """Carry the reason, and the file the child's first words went to."""
        super().__init__(said)
        self.log = log


def command(options: Options) -> list[str]:
    """Return the argv that runs one daemon, as this interpreter would run it."""
    argv = [
        sys.executable,
        "-m",
        "zettcode.daemon",
        "run",
        "--token",
        options.token,
        "--workspace",
        str(options.workspace),
    ]
    if options.session is not None:
        argv += ["--session", options.session]
    if options.model is not None:
        argv += ["--model", options.model]
    if options.effort is not None:
        argv += ["--effort", options.effort]
    return argv


def spawn(
    workspace: Path,
    *,
    token: str,
    model: str | None = None,
    effort: str | None = None,
    resume: str | None = None,
) -> State:
    """Start one daemon for ``workspace`` and return the state it wrote once it was reachable.

    Args:
        workspace: The directory the session works in.
        token: The word this spawn waits for, so it cannot mistake an older daemon for its own.
        model: The model to run on, or ``None`` for the first configured.
        effort: The reasoning level, or ``None`` for the model's own default.
        resume: A stored session to continue, or ``None`` for a fresh one.

    Raises:
        SpawnFailed: The process exited, or never became reachable in :data:`~.state.START_SECONDS`.
    """
    from .run import Options

    workspace = workspace.expanduser().resolve()
    root = workspace_folder(workspace, create=True)
    early = root / ".spawn"
    early.mkdir(parents=True, exist_ok=True)
    log_path = early / f"{token}.log"
    argv = command(Options(workspace=workspace, token=token, session=resume, model=model, effort=effort))
    with log_path.open("wb") as log:
        if os.name == "nt":  # pragma: no cover - exercised on Windows only
            process = subprocess.Popen(  # noqa: S603 - the argv is ours, not a caller's string
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=workspace,
                creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(  # noqa: S603 - the argv is ours, not a caller's string
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=workspace,
                start_new_session=True,
            )
    state = _wait_for(root, token, process)
    if state is None:
        if process.poll() is None:
            process.terminate()
        _wait_dead(process)
        _drop(root, token)
        _clear(early, log_path)
        raise SpawnFailed(_tail(log_path), log_path)
    _clear(early, log_path)
    return state


def _wait_for(root: Path, token: str, process: subprocess.Popen[bytes]) -> State | None:
    """Poll the daemon folders until one says it is this spawn's, and reachable; ``None`` when it never did."""
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        state = _ours(root, token)
        if state is not None and state.status in ("idle", "working"):
            return state
        if process.poll() is not None:
            # One last look: it may have said hello and then gone, and that is the truth to report.
            state = _ours(root, token)
            return state if state is not None else None
        time.sleep(POLL_SECONDS)
    return None


def _ours(root: Path, token: str) -> State | None:
    """Return the state written by the daemon holding ``token``, if it has written one."""
    try:
        folders = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return None
    for folder in folders:
        state = State.read(folder)
        if state is not None and state.token == token:
            return state
    return None


def _drop(root: Path, token: str) -> None:
    """Remove the record a failed start left behind, so it is not listed as a daemon that once ran."""
    try:
        folders = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return
    for folder in folders:
        state = State.read(folder)
        if state is not None and state.token == token:
            remove(folder)


def _clear(early: Path, log_path: Path) -> None:
    """Remove the spawn's early log when it said nothing, and the folder when it is empty."""
    try:
        if log_path.exists() and log_path.stat().st_size == 0:
            log_path.unlink()
        if early.is_dir() and not any(early.iterdir()):
            early.rmdir()
    except OSError:
        pass


def _tail(path: Path, lines: int = 12) -> str:
    """Return the last lines the child wrote before it gave up."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "the daemon did not say why it could not start"
    if not text:
        return "the daemon stopped before it could say anything"
    return "\n".join(text.splitlines()[-lines:])


def _wait_dead(process: subprocess.Popen[bytes], grace: float = KILL_GRACE) -> None:
    """Wait for the process to go, then kill it: a spawn that failed must not leave it running."""
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        time.sleep(POLL_SECONDS)
    with contextlib.suppress(OSError):
        process.kill()


def kill(entry: Entry, *, grace: float = KILL_GRACE) -> str:
    """Stop the daemon an entry describes, and remove its record; return what happened, in one sentence.

    A dead entry is only removed: the process it described is gone already. The session is never touched — it is a
    conversation like any other, and ``zettcode resume <id>`` opens it afterwards.
    """
    if entry.state is None:
        remove(entry.folder)
        return "removed: it never recorded what it was"
    if not entry.alive:
        remove(entry.folder)
        return "was already gone; its record was removed"
    pid = entry.state.pid
    _write_stopping(entry)
    if not _signal(pid, signal.SIGTERM):
        remove(entry.folder)
        return "was already gone; its record was removed"
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        # The daemon removes its own record on the way out, so the folder going is the proof it stopped — a pid can
        # outlive the process it named, as a zombie its parent has not reaped.
        if not entry.folder.exists() or not pid_runs(pid):
            remove(entry.folder)
            return "stopped"
        time.sleep(POLL_SECONDS)
    _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    remove(entry.folder)
    return "did not stop in time, so it was killed"


def _write_stopping(entry: Entry) -> None:
    """Say in the record that this daemon is on its way out, so a reader does not see it as idle while it dies."""
    if entry.state is None:
        return
    with contextlib.suppress(OSError):
        dataclasses.replace(entry.state, status="stopping").write(entry.folder)


def _signal(pid: int, number: int) -> bool:
    """Send one signal; ``False`` when the process is not there to take it."""
    try:
        os.kill(pid, number)
    except OSError:
        return False
    return True


def find(session_id: str) -> Entry | None:
    """Return the daemon whose session is ``session_id``, whichever workspace it works in."""
    return next((entry for entry in entries() if entry.session_id == session_id), None)


def is_alive(folder: Path) -> bool:
    """Return whether the daemon recorded in ``folder`` is running."""
    return alive(folder, State.read(folder))
