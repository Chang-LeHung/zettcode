"""``zettcode daemon``: the background agents this machine is running, and how they are started and stopped.

The command is a management surface only. Nothing is ever sent through it — a daemon is reached the way any other
session is, with ``send_message``, using its session id. What is here is the life around that:

    zettcode daemon list
    zettcode daemon spawn
    zettcode daemon kill <session-id>

A daemon runs with full shell permission and nobody to ask, which is why nothing here asks: starting one is the
decision, and it is taken by whoever runs ``spawn``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .state import Entry, entries

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Sequence

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
            "It runs with full shell permission and without asking anyone."
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
    found = sorted(entries(), key=lambda entry: entry.state.started_at if entry.state else 0.0, reverse=True)
    if as_json:
        print(json.dumps([_entry_json(entry) for entry in found], indent=2))
        return EXIT_OK
    if not found:
        print("No daemons. Start one with: zettcode daemon spawn")
        return EXIT_OK
    rows: list[tuple[str, ...]] = [("SESSION", "WORKSPACE", "MODEL", "EFFORT", "STATUS", "FOR", "TITLE")]
    for entry in found:
        rows.append(_row(entry))
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        line = "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()
        print(line)
    dead = [entry for entry in found if entry.dead]
    if dead:
        print("\nA dead entry is one whose process is gone; `zettcode daemon kill <id>` removes it.")
    return EXIT_OK


def _row(entry: Entry) -> tuple[str, ...]:
    """Return one daemon as the columns ``list`` prints."""
    state = entry.state
    if state is None:
        return (entry.session_id, "?", "?", "?", entry.status, _age(entry.seconds()), "-")
    return (
        entry.session_id,
        _short_path(state.workspace),
        state.model or "?",
        state.effort or "-",
        entry.status,
        _age(entry.seconds()),
        state.title or "-",
    )


def _entry_json(entry: Entry) -> dict[str, object]:
    """Return one daemon as plain data."""
    state = entry.state
    return {
        "session": entry.session_id,
        "workspace": state.workspace if state is not None else None,
        "model": state.model if state is not None else None,
        "effort": state.effort if state is not None else None,
        "status": entry.status,
        "pid": state.pid if state is not None else None,
        "seconds": round(entry.seconds(), 1),
        "title": state.title if state is not None else None,
        "folder": str(entry.folder),
    }


def _spawn(args: argparse.Namespace) -> int:
    """Start one daemon, wait until it can be messaged, and print what to do with it."""
    from .process import SpawnFailed, spawn

    token = secrets.token_hex(8)
    try:
        state = spawn(
            args.workspace,
            token=token,
            model=args.model,
            effort=args.effort,
            resume=args.resume,
        )
    except SpawnFailed as error:
        sys.stderr.write(f"zettcode daemon: could not start: {error}\n")
        if error.log is not None:
            sys.stderr.write(f"the daemon's first words are in {error.log}\n")
        return EXIT_FAILED
    if args.json:
        print(
            json.dumps(
                {
                    "session": state.session_id,
                    "workspace": state.workspace,
                    "model": state.model,
                    "effort": state.effort,
                    "pid": state.pid,
                },
                indent=2,
            )
        )
        return EXIT_OK
    print(f"session  {state.session_id}")
    print(f"workspace {state.workspace}")
    print(f"model    {state.model or '?'}" + (f" · effort {state.effort}" if state.effort else ""))
    print()
    print(f'send_message(to="{state.session_id}", message="...")')
    return EXIT_OK


def _kill(sessions: Sequence[str], as_json: bool) -> int:
    """Stop each daemon named and remove its record; report one line per session."""
    from .process import kill

    outcomes: list[dict[str, str]] = []
    missing: list[str] = []
    for session in sessions:
        entry = next((found for found in entries() if found.session_id == session), None)
        if entry is None:
            missing.append(session)
            outcomes.append({"session": session, "result": "no daemon with that session"})
            continue
        outcomes.append({"session": session, "result": kill(entry)})
    if as_json:
        print(json.dumps(outcomes, indent=2))
    else:
        for outcome in outcomes:
            print(f"{outcome['session']}  {outcome['result']}")
    return EXIT_FAILED if missing else EXIT_OK


def _run(args: argparse.Namespace) -> int:
    """Run the daemon process itself; this is what ``spawn`` starts."""
    from .run import Options, serve

    try:
        return asyncio.run(
            serve(
                Options(
                    workspace=args.workspace,
                    token=args.token,
                    session=args.session,
                    model=args.model,
                    effort=args.effort,
                )
            )
        )
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
    """Shorten an absolute path for a table cell: ``~`` for the home directory, and only the last part beyond that."""
    from pathlib import Path as _Path

    try:
        home = str(_Path.home())
    except RuntimeError:  # pragma: no cover - no home directory
        return path
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


if __name__ == "__main__":
    raise SystemExit(daemon_program())
