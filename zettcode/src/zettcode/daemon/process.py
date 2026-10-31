"""Starting a daemon and stopping one: the process behind a :class:`~.state.Record`.

A daemon outlives the terminal that started it, so it is started detached: its own session on POSIX, its own
process group on Windows, no inherited standard input, and its output in a file rather than in whatever window
happened to run the command. :class:`Daemons` is the whole of it — ``start`` waits for the daemon to say it is
ready, so a start that returns is a session another agent can message; ``stop`` is SIGTERM, then SIGKILL, then the
record goes.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING

from . import PERMISSIONS
from .state import START_SECONDS, Record, Registry, pid_runs

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Callable

    from .run import Options
    from .state import State

#: How long a stop may take before the process is killed outright.
KILL_GRACE = 5.0

#: How often a start looks for the state file its child writes.
POLL_SECONDS = 0.05

__all__ = ["Daemons", "KILL_GRACE", "SpawnFailed", "UpdateFailed"]


class SpawnFailed(RuntimeError):
    """A daemon was started and never became reachable."""

    def __init__(self, said: str, log: Path | None = None) -> None:
        """Carry the reason, and the file the child's first words went to."""
        super().__init__(said)
        self.log = log


class UpdateFailed(RuntimeError):
    """What a reader asked to change about a daemon cannot be changed, and why."""


class Daemons:
    """The running daemons of one registry: start one, stop one, and keep the directories between the two.

    The registry is all the state there is; this class is only what a process does to it, so a command holding one
    can start, stop and list without passing a folder around.
    """

    def __init__(self, registry: Registry | None = None) -> None:
        """Work on ``registry``, or on the machine's own."""
        self.registry = registry if registry is not None else Registry()

    # -- starting ----------------------------------------------------------------------------------
    def start(
        self,
        workspace: Path,
        *,
        model: str | None = None,
        effort: str | None = None,
        resume: str | None = None,
        name: str | None = None,
        title: str | None = None,
        permission: str = "full",
    ) -> Record:
        """Start one daemon in ``workspace`` and return the record it wrote once it was reachable.

        Args:
            workspace: The directory the session works in.
            model: The model to run on, or ``None`` for the first configured.
            effort: The reasoning level, or ``None`` for the model's own default.
            resume: A stored session to continue, or ``None`` for a fresh one.
            name: A label to record beside the session, so ``daemon list`` says what it is for.
            title: What to call the session. ``None`` lets it name itself from its first answer.
            permission: The shell level it runs at: ``deny``, ``safe`` or ``full``.

        Raises:
            SpawnFailed: The permission is not one of :data:`~zettcode.daemon.PERMISSIONS`, the workspace is not a
                directory, the process exited, or it never became reachable in :data:`~.state.START_SECONDS`.
        """
        workspace = workspace.expanduser().resolve()
        if permission not in PERMISSIONS:
            # Refused here rather than by the child: a process that cannot be started is not worth starting, and
            # its failure would have to be read out of a log file.
            raise SpawnFailed(f"a daemon's permission is one of {', '.join(PERMISSIONS)}, not {permission!r}")
        if not workspace.is_dir():
            # Popen's own refusal for a missing cwd is a FileNotFoundError that says nothing about the argument.
            raise SpawnFailed(f"{workspace} is not a directory, so a daemon has nowhere to work")
        if title is not None and not title.strip():
            # The daemon would be started and then fail to name itself; refusing here says which argument it was.
            raise SpawnFailed("a session's title needs at least one character")
        token = secrets.token_hex(8)
        early = self.registry.workspace(workspace, create=True) / ".spawn"
        early.mkdir(parents=True, exist_ok=True)
        log_path = early / f"{token}.log"
        with log_path.open("wb") as log:
            child = _Child(
                self._command(_options(workspace, token, model, effort, resume, name, title, permission)),
                workspace,
                log,
            )
        record = self._await(child, token, START_SECONDS)
        if record is None:
            child.abandon()
            self._forget(token)
            _clear(early, log_path)
            raise SpawnFailed(_tail(log_path), log_path)
        _clear(early, log_path)
        return record

    def _command(self, options: Options) -> list[str]:
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
        if options.name is not None:
            argv += ["--name", options.name]
        if options.title is not None:
            argv += ["--title", options.title]
        argv += ["--permission", options.permission]
        return argv

    def _await(self, child: _Child, token: str, timeout: float) -> Record | None:
        """Poll the records until one says it is this start's, and reachable; ``None`` when it never did."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self._ours(token)
            if record is not None and record.status in ("idle", "working"):
                return record
            if child.exited():
                # One last look: it may have said hello and then gone, and that is the truth to report.
                return self._ours(token)
            time.sleep(POLL_SECONDS)
        return None

    def _ours(self, token: str) -> Record | None:
        """Return the record of the daemon holding ``token``, if it has written one."""
        return next(
            (record for record in self.registry.all() if record.state is not None and record.state.token == token),
            None,
        )

    def _forget(self, token: str) -> None:
        """Remove the record a failed start left behind, so it is not listed as a daemon that once ran."""
        record = self._ours(token)
        if record is not None:
            record.remove()

    # -- stopping ----------------------------------------------------------------------------------
    def stop(self, record: Record, *, grace: float = KILL_GRACE) -> str:
        """Stop the daemon ``record`` describes, remove its record, and say what happened in one sentence.

        A dead record is only removed: the process it described is gone already. The session is never touched — it
        is a conversation like any other, and ``zettcode resume <id>`` opens it afterwards.
        """
        state = record.state
        if state is None:
            record.remove()
            return "removed: it never recorded what it was"
        if not record.alive:
            record.remove()
            return "was already gone; its record was removed"
        pid = state.pid
        try:
            record.change(lambda current: dataclasses.replace(current or state, status="stopping"))
        except OSError as error:
            # The status is a courtesy to a reader looking while the signal lands; a state another writer holds
            # must not keep `kill` from sending it.
            record.log(f"the state file could not be written: {error}")
        if not _signal(pid, signal.SIGTERM):
            record.remove()
            return "was already gone; its record was removed"
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            # The daemon removes its own record on the way out, so the folder going is the proof it stopped — a pid
            # can outlive the process it named, as a zombie its parent has not reaped.
            if not record.folder.exists() or not pid_runs(pid):
                record.remove()
                return "stopped"
            time.sleep(POLL_SECONDS)
        _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        record.remove()
        return "did not stop in time, so it was killed"

    # -- what a reader may change afterwards --------------------------------------------------------
    def update(self, record: Record, *, title: str | None = None, name: str | None = None) -> Record:
        """Change what is recorded about one daemon: the session's title, or the daemon's own label.

        The label is the daemon's, so it may be changed while it runs; the daemon keeps a name a reader put there
        (see ``Daemon._label``). The title is the *session's*, and a session is written to only by the process that
        holds its lock: while the daemon runs it holds it, and when it is gone the session is free. A blank title is
        refused here rather than written as one. Given together, a label is written even when the title cannot be,
        and the error says so.

        This blocks while it writes the session's metadata, so it is called where no event loop runs — the CLI
        calls it directly and the SDK from a worker thread.

        Raises:
            UpdateFailed: There is no state to change, the daemon still runs, its session is open in another
                process, its record cannot be written, or the title is not one a session can carry.
        """
        if title is None and name is None:
            return record
        state = record.state
        if state is None:
            raise UpdateFailed("this daemon never recorded what it was, so there is nothing to change")
        cleaned = None if title is None else title.strip()
        label = None if name is None else (name.strip() or None)

        def named(current: State | None) -> State:
            base = current or state
            return dataclasses.replace(base, name=label)

        def with_title(current: State | None) -> State:
            # Only the title changes when no label was named: a name of ``None`` is "clear the label" only when the
            # caller asked for one, which is what the ``name is None`` branch says.
            base = named(current) if name is not None else (current or state)
            return dataclasses.replace(base, title=cleaned)

        if title is not None and not cleaned:
            if name is not None:
                self._write(record, named)
                raise UpdateFailed("a title needs at least one character; the label was changed")
            raise UpdateFailed("a title needs at least one character")
        if cleaned is None:
            return self._write(record, named)
        if record.alive:
            message = "the daemon is running, and its session is its own; stop it before naming it"
            if name is not None:
                self._write(record, named)
                message += "; the label was changed"
            raise UpdateFailed(message)
        try:
            self._rename(record.session_id, state.workspace, cleaned)
        except UpdateFailed as error:
            if name is not None:
                self._write(record, named)
                raise UpdateFailed(f"{error}; the label was changed") from error
            raise
        try:
            return self._write(record, with_title)
        except UpdateFailed as error:
            raise UpdateFailed(f"{error}; the session was renamed, so its record still says the old title") from error

    @staticmethod
    def _write(record: Record, produce: Callable[[State | None], State]) -> Record:
        """Write the record through the lock that keeps a daemon's refresh and a reader's change apart."""
        try:
            record.change(produce)
        except OSError as error:
            raise UpdateFailed(f"the daemon's record could not be written: {error}") from error
        return record

    @staticmethod
    def _rename(session_id: str, workspace: str, title: str) -> None:
        """Write the session's title into its metadata, holding the session's lock while it is written.

        The lock is what S16/H27 mean by "written only by the process holding it": asking whether it is held and
        then writing without it is a check-then-act a terminal can slip into between the two steps.
        """
        from zettcode.engine.storage import SessionLocks, SessionStore

        store = SessionStore(workspace=workspace)
        locks = SessionLocks(store.session_dir)
        try:
            taken = locks.claim(session_id)
        except ValueError as error:
            raise UpdateFailed(str(error)) from error
        if not taken:
            raise UpdateFailed("the session is open in another process, so its name is not ours to write")
        try:
            asyncio.run(store.set_title(session_id, title))
        except (OSError, ValueError) as error:
            raise UpdateFailed(str(error)) from error
        finally:
            locks.release()


class _Child:
    """The process a start made, kept just long enough to know whether it worked."""

    def __init__(self, argv: list[str], workspace: Path, log: IO[bytes]) -> None:
        if os.name == "nt":  # pragma: no cover - exercised on Windows only
            self.process = subprocess.Popen(  # noqa: S603 - the argv is ours, not a caller's string
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=workspace,
                creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            )
        else:
            self.process = subprocess.Popen(  # noqa: S603 - the argv is ours, not a caller's string
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=workspace,
                start_new_session=True,
            )

    def exited(self) -> bool:
        """Return whether it has already ended."""
        return self.process.poll() is not None

    def abandon(self) -> None:
        """Stop a child that never became reachable, so a failed start leaves nothing running."""
        if self.process.poll() is None:
            self.process.terminate()
        deadline = time.monotonic() + KILL_GRACE
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(POLL_SECONDS)
        with contextlib.suppress(OSError):
            self.process.kill()


def _options(
    workspace: Path,
    token: str,
    model: str | None,
    effort: str | None,
    resume: str | None,
    name: str | None,
    title: str | None,
    permission: str,
) -> Options:
    """Build what ``daemon run`` should be told, without importing its module until it is needed."""
    from .run import Options

    return Options(
        workspace=workspace,
        token=token,
        session=resume,
        model=model,
        effort=effort,
        name=name,
        title=title,
        permission=permission,
    )


def _clear(early: Path, log_path: Path) -> None:
    """Remove the start's early log when it said nothing, and the folder when it is empty."""
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


def _signal(pid: int, number: int) -> bool:
    """Send one signal; ``False`` when the process is not there to take it."""
    try:
        os.kill(pid, number)
    except OSError:
        return False
    return True
