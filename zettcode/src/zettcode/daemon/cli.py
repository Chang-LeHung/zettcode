"""``zettcode daemon``: the background agents this machine is running, and how they are started and stopped.

The command is a management surface only. Nothing is ever sent through it — a daemon is reached the way any other
session is, with ``send_message``, using its session id. What is here is the life around that:

    zettcode daemon list
    zettcode daemon spawn
    zettcode daemon kill <session-id>

A daemon runs at the shell level it was started with and with nobody to ask, which is why nothing here asks:
starting one is the decision, and it is taken by whoever runs ``spawn``.

The three handlers are thin on purpose: they build a :class:`~.state.Registry` or a :class:`~.process.Daemons` and
print what it answers. What to run, how to wait for it and what to do when it dies is in those classes, not here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Sequence

    from .state import Record

__all__ = ["daemon_program"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    """Return the parser for ``zettcode daemon`` and its subcommands."""
    parser = argparse.ArgumentParser(
        prog="zettcode daemon",
        description="Run and manage background agents: a session another session can message.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    listing = commands.add_parser(
        "list",
        help="show every daemon on this machine, alive or dead",
        description="Show every daemon recorded under ~/.zettcode/daemon, whichever workspace it works in.",
    )
    listing.add_argument("--json", action="store_true", help="print the daemons as JSON, for a program to read")

    spawn = commands.add_parser(
        "spawn",
        help="start a daemon and print its session id",
        description=(
            "Start a background agent in a workspace and print the session id other sessions message it by. "
            "It runs without asking anyone; its shell level is the one given."
        ),
    )
    spawn.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="directory the daemon works in (default: the current directory)",
    )
    spawn.add_argument(
        "--model", metavar="NAME", default=None, help="the model to run on (default: the first configured)"
    )
    spawn.add_argument("--effort", metavar="LEVEL", default=None, help="the reasoning level (default: the model's own)")
    spawn.add_argument(
        "-n",
        "--name",
        metavar="LABEL",
        default=None,
        help="a label for this daemon, shown by `daemon list` (default: none)",
    )
    spawn.add_argument(
        "--permission",
        metavar="LEVEL",
        choices=("deny", "safe", "full"),
        default="full",
        help=(
            "shell level it runs at: safe puts every command in a sandbox, deny allows none (default: full). "
            "There is no ask: nobody is there to answer"
        ),
    )
    spawn.add_argument(
        "--resume",
        metavar="SESSION",
        default=None,
        help="continue a stored session instead of starting an empty one",
    )
    spawn.add_argument("--json", action="store_true", help="print the new daemon as JSON, for a program to read")

    kill = commands.add_parser(
        "kill",
        help="stop daemons by session id, and remove their records",
        description=(
            "Stop each daemon named and remove its record; the session itself stays, so `zettcode resume ID` "
            "opens the conversation afterwards."
        ),
    )
    kill.add_argument("session", metavar="SESSION", nargs="+", help="the session id `daemon list` shows")
    kill.add_argument("--json", action="store_true", help="print the outcome as JSON, for a program to read")

    # Started by `spawn`, never by hand: it is the process a reader's shell would otherwise own.
    run = commands.add_parser(
        "run",
        help="the process `spawn` starts; not meant to be run by hand",
        description="Run one daemon in this process. `spawn` starts it detached, with the arguments below.",
    )
    run.add_argument("--token", required=True, help=argparse.SUPPRESS)
    run.add_argument("--workspace", required=True, type=Path, help=argparse.SUPPRESS)
    run.add_argument("--session", default=None, help=argparse.SUPPRESS)
    run.add_argument("--model", default=None, help=argparse.SUPPRESS)
    run.add_argument("--effort", default=None, help=argparse.SUPPRESS)
    run.add_argument("--name", default=None, help=argparse.SUPPRESS)
    run.add_argument("--permission", default="full", help=argparse.SUPPRESS)
    return parser


def daemon_program(argv: Sequence[str] | None = None) -> int:
    """Run ``zettcode daemon`` for these arguments and return the exit status."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "list":
        return _list(args.json)
    if args.command == "spawn":
        return _spawn(args)
    if args.command == "kill":
        return _kill(args.session, args.json)
    return _run(args)


def _list(as_json: bool) -> int:
    """Print every daemon recorded, with what it is doing and whether its process is still there."""
    from .state import Registry

    found = sorted(Registry().all(), key=lambda record: record.state.started_at if record.state else 0.0, reverse=True)
    if as_json:
        print(json.dumps([_record_json(record) for record in found], indent=2))
        return EXIT_OK
    if not found:
        print("No daemons. Start one with: zettcode daemon spawn")
        return EXIT_OK
    rows: list[tuple[str, ...]] = [
        ("SESSION", "NAME", "WORKSPACE", "MODEL", "EFFORT", "PERMISSION", "STATUS", "FOR", "TITLE")
    ]
    rows.extend(_row(record) for record in found)
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    if any(record.dead for record in found):
        print("\nA dead record is one whose process is gone; `zettcode daemon kill <id>` removes it.")
    return EXIT_OK


def _row(record: Record) -> tuple[str, ...]:
    """Return one daemon as the columns ``list`` prints."""
    state = record.state
    if state is None:
        return (record.session_id, "-", "?", "?", "?", "?", record.status, _age(record.seconds()), "-")
    return (
        record.session_id,
        state.name or "-",
        _short_path(state.workspace),
        state.model or "?",
        state.effort or "-",
        state.permission or "?",
        record.status,
        _age(record.seconds()),
        state.title or "-",
    )


def _record_json(record: Record) -> dict[str, object]:
    """Return one daemon as plain data."""
    state = record.state
    return {
        "session": record.session_id,
        "name": state.name if state is not None else None,
        "workspace": state.workspace if state is not None else None,
        "model": state.model if state is not None else None,
        "effort": state.effort if state is not None else None,
        "permission": state.permission if state is not None else None,
        "status": record.status,
        "pid": state.pid if state is not None else None,
        "seconds": round(record.seconds(), 1),
        "title": state.title if state is not None else None,
        "folder": str(record.folder),
    }


def _spawn(args: argparse.Namespace) -> int:
    """Start one daemon, wait until it can be messaged, and print what to do with it."""
    from .process import Daemons, SpawnFailed

    try:
        record = Daemons().start(
            args.workspace,
            model=args.model,
            effort=args.effort,
            resume=args.resume,
            name=args.name,
            permission=args.permission,
        )
    except SpawnFailed as error:
        sys.stderr.write(f"zettcode daemon: could not start: {error}\n")
        if error.log is not None:
            sys.stderr.write(f"the daemon's first words are in {error.log}\n")
        return EXIT_FAILED
    state = record.state
    if args.json:
        print(
            json.dumps(
                {
                    "session": record.session_id,
                    "name": state.name if state is not None else None,
                    "workspace": state.workspace if state is not None else None,
                    "model": state.model if state is not None else None,
                    "effort": state.effort if state is not None else None,
                    "permission": state.permission if state is not None else None,
                    "pid": state.pid if state is not None else None,
                },
                indent=2,
            )
        )
        return EXIT_OK
    print(f"session  {record.session_id}")
    if state is not None:
        if state.name:
            print(f"name     {state.name}")
        print(f"workspace {state.workspace}")
        print(f"model    {state.model or '?'}" + (f" · effort {state.effort}" if state.effort else ""))
        print(f"shell    {state.permission or '?'}")
    print()
    print(f'send_message(to="{record.session_id}", message="...")')
    return EXIT_OK


def _kill(sessions: Sequence[str], as_json: bool) -> int:
    """Stop each daemon named and remove its record; report one line per session."""
    from .process import Daemons
    from .state import Registry

    registry = Registry()
    daemons = Daemons(registry)
    outcomes: list[dict[str, str]] = []
    missing = False
    for session in sessions:
        record = registry.find(session)
        if record is None:
            missing = True
            outcomes.append({"session": session, "result": "no daemon with that session"})
            continue
        outcomes.append({"session": session, "result": daemons.stop(record)})
    if as_json:
        print(json.dumps(outcomes, indent=2))
    else:
        for outcome in outcomes:
            print(f"{outcome['session']}  {outcome['result']}")
    return EXIT_FAILED if missing else EXIT_OK


def _run(args: argparse.Namespace) -> int:
    """Run the daemon process itself; this is what ``spawn`` starts."""
    import asyncio

    from .run import Options, serve

    options = Options(
        workspace=args.workspace,
        token=args.token,
        session=args.session,
        model=args.model,
        effort=args.effort,
        name=args.name,
        permission=args.permission,
    )
    try:
        return asyncio.run(serve(options))
    except KeyboardInterrupt:
        return EXIT_OK


def _age(seconds: float) -> str:
    """Say how long a daemon has been running, in the short form a table has room for."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _short_path(path: str) -> str:
    """Shorten an absolute path for a table cell: ``~`` for the home directory."""
    try:
        home = str(Path.home())
    except RuntimeError:  # pragma: no cover - no home directory
        return path
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


if __name__ == "__main__":
    raise SystemExit(daemon_program())
