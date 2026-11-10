"""Background agents, from code: start one, list them, read what one logged, stop one.

A daemon is a session with nobody at the keyboard (see ``docs/guide/daemons.md``). ``zettcode daemon`` is its
command line; this module is the same thing for a program, so a front end that manages daemons does not parse the
output of a command or reach into the folders the daemons keep their records in::

    from zettcode.sdk.daemons import list_daemons, spawn_daemon, stop_daemon

    daemon = await spawn_daemon("~/project", name="reviewer", permission="safe")
    print(daemon.session_id)             # message it with ``Client.send`` or the ``send_message`` tool
    for item in list_daemons():
        print(item.session_id, item.status)
    await stop_daemon(daemon.session_id)

A daemon is a separate process, so none of this is bound by the one-workspace-per-process rule of a
:class:`~zettcode.sdk.client.Client`. Nothing here imports the daemon's own code until it is used.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import ConfigurationError, DaemonStartError, SessionNotFoundError
from .types import DaemonInfo

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.daemon.state import Record

__all__ = [
    "PERMISSIONS",
    "daemon_log",
    "default_effort",
    "delete_daemon",
    "list_daemons",
    "spawn_daemon",
    "stop_daemon",
    "update_daemon",
]

#: The shell levels a daemon can be given. There is no ``ask``: nobody is there to answer it.
PERMISSIONS = ("deny", "safe", "full")


def default_effort(model: str | None = None, *, path: str | Path | None = None) -> str:
    """Return the reasoning level a daemon runs at when nobody names one: the middle of what its model accepts.

    Providers do not all take every level, and a model's own default is not always in the middle of them, so the
    middle is the one answer that means "as much as the model is willing to do by default" whatever it lists.
    A list with an even number of levels takes the higher of the two middles: of ``low, medium, high`` that is
    ``medium``, and of ``off … ultra`` (eight) it is ``high``.

    Args:
        model: The model by the name :func:`~zettcode.sdk.models.list_models` gives, or ``None`` for the first
            configured.
        path: The configuration file, or the default one.

    Returns:
        The level's name, or an empty string when the configuration lists no model to ask.
    """
    from .models import list_models

    try:
        listed = list_models(path)
    except ValueError:
        return ""
    if not listed:
        return ""
    chosen = listed[0]
    if model:
        chosen = next((info for info in listed if info.name == model or info.model == model), chosen)
    levels = [str(level) for level in chosen.efforts]
    return levels[len(levels) // 2] if levels else ""


def _info(record: Record) -> DaemonInfo:
    """Return the SDK's value for a daemon's record."""
    state = record.state
    if state is None:
        return DaemonInfo(session_id=record.session_id, status=record.status)
    return DaemonInfo(
        session_id=record.session_id,
        workspace=state.workspace,
        status=record.status,
        name=state.name,
        title=state.title,
        model=state.model,
        effort=state.effort,
        permission=state.permission,
        pid=state.pid,
        started_at=state.started_at,
        input_tokens=state.input_tokens,
        output_tokens=state.output_tokens,
        context_tokens=state.context_tokens,
        context_window=state.context_window,
        requested_model=state.requested_model,
        requested_effort=state.requested_effort,
        requested_error=state.requested_error,
        broker=state.broker,
    )


def list_daemons() -> list[DaemonInfo]:
    """Return every daemon recorded on this machine, whichever workspace it works in, newest first.

    A daemon whose process is gone is listed with the status ``dead`` until it is stopped, which removes the record.
    This reads a few small files per daemon, so it is cheap to call often.
    """
    from zettcode.daemon.state import Registry

    found = sorted(Registry().all(), key=lambda record: record.state.started_at if record.state else 0.0, reverse=True)
    return [_info(record) for record in found]


async def spawn_daemon(
    workspace: str | Path,
    *,
    model: str | None = None,
    effort: str | None = None,
    resume: str | None = None,
    name: str | None = None,
    title: str | None = None,
    permission: str = "full",
) -> DaemonInfo:
    """Start a background agent and return it once it can be messaged.

    Args:
        workspace: The directory it works in; it has to exist.
        model: The model to run on, by the name :func:`~zettcode.sdk.models.list_models` gives, or ``None`` for the
            first configured.
        effort: The reasoning level, or ``None`` for the model's own.
        resume: A stored session of that workspace to continue instead of starting an empty one.
        name: A label saying what the daemon is for, recorded beside it.
        title: What to call the session. ``None`` lets it name itself from its first answer.
        permission: Its shell level: ``deny`` (no shell), ``safe`` (every command in a sandbox) or ``full``. The
            default is ``full``, the same one the command line starts with: a daemon nobody is watching has no one
            to answer a sandbox's questions, and a start that silently changes what it may do is worse than one
            that says so. ``safe`` and ``deny`` are asked for, not assumed.

    Raises:
        ConfigurationError: The permission is not one of :data:`PERMISSIONS`, or the workspace is not a directory.
        DaemonStartError: The process exited, or never became reachable; the message is what it said.
    """
    if permission not in PERMISSIONS:
        raise ConfigurationError(f"A daemon's permission is one of {', '.join(PERMISSIONS)}, not {permission!r}")
    folder = Path(workspace).expanduser()
    if not folder.is_dir():
        raise ConfigurationError(f"No such directory: {folder}")
    from zettcode.daemon.process import Daemons, SpawnFailed

    def start() -> Record:
        return Daemons().start(
            folder,
            model=model,
            effort=effort,
            resume=resume,
            name=name or None,
            title=title or None,
            permission=permission,
        )

    try:
        record = await asyncio.to_thread(start)
    except SpawnFailed as error:
        raise DaemonStartError(str(error), str(error.log) if error.log is not None else None) from error
    return _info(record)


async def stop_daemon(session_id: str, *, force: bool = False, keep: bool = False) -> str:
    """Stop a daemon and say in one sentence what happened.

    The session itself stays, with everything the daemon did, so it can be opened afterwards. By default the
    daemon's record is removed too; with ``keep`` it stays, listed as ``dead``, so the daemon can be started again
    (``spawn_daemon(..., resume=session_id)``) or removed for good with :func:`delete_daemon`. A daemon whose
    process was already gone only has its record removed (or kept).

    Args:
        session_id: The daemon, as :func:`list_daemons` gives it.
        force: Stop it even in the middle of a turn, which throws that turn away.
        keep: Leave the record, as a dead one, instead of removing it.

    Raises:
        SessionNotFoundError: No daemon has that session.
        ConfigurationError: It is working on a turn and ``force`` was not given.
    """
    from zettcode.daemon.process import Daemons, StillWorking
    from zettcode.daemon.state import Registry

    registry = Registry()
    record = registry.find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    try:
        return await asyncio.to_thread(lambda: Daemons(registry).stop(record, force=force, keep=keep))
    except StillWorking as error:
        raise ConfigurationError(str(error)) from error


async def delete_daemon(session_id: str) -> str:
    """Remove a daemon for good: its record and its conversation. This cannot be undone.

    Raises:
        SessionNotFoundError: No daemon has that session.
        ConfigurationError: Its process is still running (stop it first), or its session is open in another process.
    """
    from zettcode.daemon.process import Daemons, StillRunning, UpdateFailed
    from zettcode.daemon.state import Registry

    registry = Registry()
    record = registry.find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    try:
        return await asyncio.to_thread(Daemons(registry).delete, record)
    except (StillRunning, UpdateFailed) as error:
        raise ConfigurationError(str(error)) from error


async def update_daemon(
    session_id: str,
    *,
    title: str | None = None,
    name: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    permission: str | None = None,
) -> DaemonInfo:
    """Change what is recorded about a daemon: its session's name, its own label, or what it runs on.

    The label may be changed while the daemon runs; it keeps what a reader put there. The title is the session's,
    and a session is written to only by the process holding its lock, so naming one waits until the daemon is
    stopped (a running daemon names its own session from the first answer, and ``name_it`` costs nothing once it
    has one). A model or an effort is a request the running daemon puts in force before its next turn; a daemon
    that is not running cannot be moved to another model. A permission is a restart, not a request: the level is
    handed to the process when it starts, so a running daemon is stopped and started again on the same session —
    the conversation survives, a turn in flight does not, and a daemon in the middle of one is refused.

    Args:
        session_id: The daemon, as :func:`list_daemons` gives it.
        title: The name to give its session, or ``None`` to leave it.
        name: The label to record, ``""`` to clear it, or ``None`` to leave it.
        model: The model it should run from the next turn on, by display name or id, or ``None`` to leave it.
        effort: The reasoning level it should run from the next turn on, or ``None`` to leave it.
        permission: Its shell level — ``deny``, ``safe`` or ``full`` — or ``None`` to leave it.

    Raises:
        SessionNotFoundError: No daemon has that session.
        ConfigurationError: The daemon still runs, its session is open in another process, the title is blank or
            too long, the model or effort is not one this machine has configured, or the permission is not one of
            :data:`PERMISSIONS`.
    """
    from zettcode.daemon.process import Daemons, UpdateFailed
    from zettcode.daemon.state import Registry

    registry = Registry()
    record = registry.find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    try:
        updated = await asyncio.to_thread(
            Daemons(registry).update,
            record,
            title=title,
            name=name,
            model=model,
            effort=effort,
            permission=permission,
        )
    except UpdateFailed as error:
        raise ConfigurationError(str(error)) from error
    return _info(updated)


def daemon_log(session_id: str, *, lines: int = 200) -> str:
    """Return the last ``lines`` lines a daemon wrote about itself: the tools it ran and the turns that failed.

    Raises:
        SessionNotFoundError: No daemon has that session.
    """
    from zettcode.daemon.state import Registry

    record = Registry().find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    wanted = max(1, lines)
    try:
        with record.log_path.open("rb") as handle:
            # The end of the file is enough: a log that has grown for weeks is not read whole for its last lines.
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - wanted * 400))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(tail.splitlines()[-wanted:])
