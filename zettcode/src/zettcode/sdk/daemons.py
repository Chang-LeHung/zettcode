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
    from ..daemon.state import Record

__all__ = ["PERMISSIONS", "daemon_log", "list_daemons", "spawn_daemon", "stop_daemon", "update_daemon"]

#: The shell levels a daemon can be given. There is no ``ask``: nobody is there to answer it.
PERMISSIONS = ("deny", "safe", "full")


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
    )


def list_daemons() -> list[DaemonInfo]:
    """Return every daemon recorded on this machine, whichever workspace it works in, newest first.

    A daemon whose process is gone is listed with the status ``dead`` until it is stopped, which removes the record.
    This reads a few small files per daemon, so it is cheap to call often.
    """
    from ..daemon.state import Registry

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
    permission: str = "safe",
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
            default is ``safe``, not the ``full`` the command line starts with: a program starting an agent that
            asks nobody should have to say so.

    Raises:
        ConfigurationError: The permission is not one of :data:`PERMISSIONS`, or the workspace is not a directory.
        DaemonStartError: The process exited, or never became reachable; the message is what it said.
    """
    if permission not in PERMISSIONS:
        raise ConfigurationError(f"A daemon's permission is one of {', '.join(PERMISSIONS)}, not {permission!r}")
    folder = Path(workspace).expanduser()
    if not folder.is_dir():
        raise ConfigurationError(f"No such directory: {folder}")
    from ..daemon.process import Daemons, SpawnFailed

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


async def stop_daemon(session_id: str) -> str:
    """Stop a daemon and remove its record, and say in one sentence what happened.

    The session itself stays, with everything the daemon did, so it can be opened afterwards. A daemon whose process
    was already gone only has its record removed.

    Raises:
        SessionNotFoundError: No daemon has that session.
    """
    from ..daemon.process import Daemons
    from ..daemon.state import Registry

    registry = Registry()
    record = registry.find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    return await asyncio.to_thread(Daemons(registry).stop, record)


async def update_daemon(session_id: str, *, title: str | None = None, name: str | None = None) -> DaemonInfo:
    """Change what is recorded about a daemon: its session's name, or its own label.

    The label may be changed while the daemon runs; it keeps what a reader put there. The title is the session's,
    and a session is written to only by the process holding its lock, so naming one waits until the daemon is
    stopped (a running daemon names its own session from the first answer, and ``name_it`` costs nothing once it
    has one).

    Args:
        session_id: The daemon, as :func:`list_daemons` gives it.
        title: The name to give its session, or ``None`` to leave it.
        name: The label to record, ``""`` to clear it, or ``None`` to leave it.

    Raises:
        SessionNotFoundError: No daemon has that session.
        ConfigurationError: The daemon still runs, its session is open in another process, or the title is blank
            or too long.
    """
    from ..daemon.process import Daemons, UpdateFailed
    from ..daemon.state import Registry

    registry = Registry()
    record = registry.find(session_id)
    if record is None:
        raise SessionNotFoundError(f"No daemon runs session {session_id!r}")
    try:
        updated = await asyncio.to_thread(Daemons(registry).update, record, title=title, name=name)
    except UpdateFailed as error:
        raise ConfigurationError(str(error)) from error
    return _info(updated)


def daemon_log(session_id: str, *, lines: int = 200) -> str:
    """Return the last ``lines`` lines a daemon wrote about itself: the tools it ran and the turns that failed.

    Raises:
        SessionNotFoundError: No daemon has that session.
    """
    from ..daemon.state import Registry

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
