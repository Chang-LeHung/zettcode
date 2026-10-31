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
    def update(
        self,
        record: Record,
        *,
        title: str | None = None,
        name: str | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> Record:
        """Change what is recorded about one daemon: its label, its session's title, or what it runs on.

        The label is the daemon's, so it may be changed while it runs; the daemon keeps a name a reader put there
        (see ``Daemon._label``). The title is the *session's*, and a session is written to only by the process that
        holds its lock: while the daemon runs it holds it, and when it is gone the session is free. A blank title is
        refused here rather than written as one. Given together, a label is written even when the title cannot be,
        and the error says so.

        A model or an effort is a request for a daemon that is running: it is written into the record and the daemon
        puts it in force before its next turn (or within a beat), keeping the conversation. A daemon that is gone
        cannot be moved to another model — it has no process to move.

        This blocks while it writes the session's metadata, so it is called where no event loop runs — the CLI
        calls it directly and the SDK from a worker thread.

        Raises:
            UpdateFailed: There is no state to change, the daemon still runs, its session is open in another
                process, its record cannot be written, the title is not one a session can carry, or the model or
                the effort is not one this machine has configured.
        """
        if title is None and name is None and model is None and effort is None:
            return record
        state = record.state
        if state is None:
            raise UpdateFailed("this daemon never recorded what it was, so there is nothing to change")
        cleaned = None if title is None else title.strip()
        label = None if name is None else (name.strip() or None)
        wanted_model = None if model is None else model.strip()
        wanted_effort = None if effort is None else effort.strip()
        if model is not None and not wanted_model:
            raise UpdateFailed("a model needs a name")
        if effort is not None and not wanted_effort:
            raise UpdateFailed("an effort needs a name")
        if wanted_model is not None or wanted_effort is not None:
            # A level is checked against the model the daemon would end on: its own, a model a previous request
            # already asked for, or the one this command names.
            pending_effort = wanted_effort if wanted_effort is not None else state.requested_effort
            try:
                if not record.alive:
                    raise UpdateFailed("the daemon is not running, so it cannot be moved to another model")
                self._check_runnable(state, wanted_model, pending_effort)
            except UpdateFailed as error:
                said = str(error)
                if (
                    record.alive
                    and wanted_model is not None
                    and wanted_effort is None
                    and state.requested_effort is not None
                    and " takes " in said
                ):
                    # The level that blocked it is not the daemon's own but one an earlier command asked for.
                    said += f"; the level {state.requested_effort!r} was already requested, so set one it takes first"
                # A label or a title is allowed whatever the settings are; write them and say what happened,
                # rather than refusing the whole command for the one argument that could not be taken.
                if title is None and name is None:
                    raise UpdateFailed(said) from error
                try:
                    self.update(record, title=title, name=name)
                except UpdateFailed as secondary:
                    raise UpdateFailed(f"{said}; and {secondary}") from error
                raise UpdateFailed(f"{said}; the other changes were written") from error
        other = name is not None or wanted_model is not None or wanted_effort is not None

        def applied(current: State | None, *, title: str | None) -> State:
            base = current or state
            if name is not None:
                base = dataclasses.replace(base, name=label)
            if wanted_model is not None:
                base = dataclasses.replace(base, requested_model=wanted_model)
            if wanted_effort is not None:
                base = dataclasses.replace(base, requested_effort=wanted_effort)
            if wanted_model is not None or wanted_effort is not None:
                # A new request has not failed yet; an error left by an older one is about that one.
                base = dataclasses.replace(base, requested_error=None)
            if title is not None:
                base = dataclasses.replace(base, title=title)
            return base

        if title is not None and not cleaned:
            if other:
                self._write(record, lambda current: applied(current, title=None))
                raise UpdateFailed("a title needs at least one character; the other changes were written")
            raise UpdateFailed("a title needs at least one character")
        if cleaned is None:
            return self._write(record, lambda current: applied(current, title=None))
        if record.alive:
            message = "the daemon is running, and its session is its own; stop it before naming it"
            if other:
                self._write(record, lambda current: applied(current, title=None))
                message += "; the other changes were written"
            raise UpdateFailed(message)
        try:
            self._rename(record.session_id, state.workspace, cleaned)
        except UpdateFailed as error:
            if other:
                self._write(record, lambda current: applied(current, title=None))
                raise UpdateFailed(f"{error}; the other changes were written") from error
            raise
        try:
            return self._write(record, lambda current: applied(current, title=cleaned))
        except UpdateFailed as error:
            raise UpdateFailed(f"{error}; the session was renamed, so its record still says the old title") from error

    @staticmethod
    def _check_runnable(state: State, model: str | None, effort: str | None) -> None:
        """Refuse a model or a level this machine cannot run, naming the ones it can.

        A model is resolved the way every layer resolves one (H26): its display name first, its id only when no
        display name answers, and a name two entries share is refused rather than guessed. A level belongs to a
        model, so it is checked against the one the request would end on — the daemon's own when only a level is
        asked for, and that one must be findable, or there is nothing to check the level against.
        """
        from zettcode.sdk import list_models

        try:
            models = list_models()
        except ValueError as error:
            raise UpdateFailed(str(error)) from error
        chosen = None
        if model is not None or effort is not None:
            wanted = model if model is not None else (state.requested_model or state.model or "")
            shown = [entry for entry in models if entry.name == wanted]
            matches = shown or [entry for entry in models if entry.model == wanted]
            if len(matches) > 1:
                raise UpdateFailed(f"Ambiguous model: {wanted}; give one a display_model")
            chosen = matches[0] if matches else None
        if model is not None and chosen is None:
            raise UpdateFailed(f"No model called {model!r}; configured: {', '.join(entry.name for entry in models)}")
        if effort is not None:
            if chosen is None:
                if state.requested_model is None and state.model is None:
                    raise UpdateFailed("this daemon has not recorded a model, so its levels cannot be checked")
                raise UpdateFailed(
                    f"the daemon's model {state.requested_model or state.model!r} is not in this configuration, "
                    "so its levels cannot be checked"
                )
            if effort not in chosen.efforts:
                raise UpdateFailed(f"{chosen.name} takes {', '.join(chosen.efforts)}, not {effort!r}")

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
