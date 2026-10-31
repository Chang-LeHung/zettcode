"""``zettcode daemon``: the background agents this machine is running, and how they are started and stopped.

The command is a management surface only. Nothing is ever sent through it — a daemon is reached the way any other
session is, with ``send_message``, using its session id. What is here is the life around that:

    zettcode daemon list
    zettcode daemon spawn
    zettcode daemon update <session-id>
    zettcode daemon prompt <session-id> TEXT...
    zettcode daemon log <session-id>
    zettcode daemon kill <session-id>

A daemon runs at the shell level it was started with and with nobody to ask, which is why nothing here asks:
starting one is the decision, and it is taken by whoever runs ``spawn``.

The handlers are thin on purpose: they build a :class:`~.state.Registry` or a :class:`~.process.Daemons` and
print what it answers. What to run, how to wait for it and what to do when it dies is in those classes, not here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..table import block, table
from . import PERMISSIONS

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Sequence

    from .state import Record, State

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

    models = commands.add_parser(
        "model",
        help="show the models a daemon can run on, and which one it would pick",
        description=(
            "Show every model the configuration lists, as `spawn --model` takes them: the first is what a daemon "
            "runs on when no model is given."
        ),
    )
    models.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="directory whose configuration is read (default: the current directory)",
    )
    models.add_argument("--json", action="store_true", help="print the models as JSON, for a program to read")

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
        choices=PERMISSIONS,
        default="full",
        help=(
            "shell level it runs at: safe puts every command in a sandbox, deny allows none (default: full). "
            "There is no ask: nobody is there to answer"
        ),
    )
    spawn.add_argument(
        "--title",
        metavar="TEXT",
        default=None,
        help="what to call its session (default: it names itself from its first answer)",
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

    update = commands.add_parser(
        "update",
        help="change what is recorded about a daemon: its label, or its session's name",
        description=(
            "Change a daemon's label, and name its session. A running daemon's session is its own, so `--title` is "
            "refused while it runs — stop it first; `--name` may be changed at any time."
        ),
    )
    update.add_argument("session", metavar="SESSION", help="the session id `daemon list` shows")
    update.add_argument(
        "--title",
        metavar="TEXT",
        default=None,
        help="the session's name, shown by `list` and by `zettcode resume`",
    )
    update.add_argument(
        "--name",
        metavar="LABEL",
        default=None,
        help="what the daemon is for, shown by `list` (an empty label clears it)",
    )
    update.add_argument(
        "--model",
        metavar="NAME",
        default=None,
        help="the model it runs from the next turn on (a running daemon; the conversation is kept)",
    )
    update.add_argument(
        "--effort",
        metavar="LEVEL",
        default=None,
        help="the reasoning level it runs from the next turn on (a running daemon)",
    )
    update.add_argument("--json", action="store_true", help="print the daemon as JSON, for a program to read")

    prompt = commands.add_parser(
        "prompt",
        help="send a prompt to a daemon through the session broker",
        description=(
            "Send a daemon a message through the session broker, as a program outside every session would. Its turn "
            "runs and the answer is stored in its session: `zettcode resume <id>` reads it, or `daemon log` shows "
            "what it did. The sender is named, not a session, so the daemon does not answer back."
        ),
    )
    prompt.add_argument("session", metavar="SESSION", help="the session id `daemon list` shows")
    prompt.add_argument("text", metavar="TEXT", nargs="+", help="what to ask it")
    prompt.add_argument("--json", action="store_true", help="print the receipt as JSON, for a program to read")

    log = commands.add_parser(
        "log",
        help="show what a daemon wrote about itself",
        description=(
            "Print the last lines a daemon wrote: the tools it ran, the turns that failed, the settings it took up. "
            "The conversation itself is not here — `zettcode resume <id>` reads that."
        ),
    )
    log.add_argument("session", metavar="SESSION", help="the session id `daemon list` shows")
    log.add_argument(
        "-n", "--lines", type=_positive, default=200, metavar="N", help="how many last lines (default 200)"
    )

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
    run.add_argument("--title", default=None, help=argparse.SUPPRESS)
    run.add_argument("--permission", default="full", choices=PERMISSIONS, help=argparse.SUPPRESS)
    return parser


def daemon_program(argv: Sequence[str] | None = None) -> int:
    """Run ``zettcode daemon`` for these arguments and return the exit status."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "list":
        return _list(args.json)
    if args.command == "model":
        return _models(args.workspace, args.json)
    if args.command == "spawn":
        return _spawn(args)
    if args.command == "update":
        return _update(args)
    if args.command == "prompt":
        return _prompt(args)
    if args.command == "log":
        return _log(args.session, args.lines)
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
    for index, record in enumerate(found):
        if index:
            print()
        for line in _entry(record):
            print(line)
    if any(record.dead for record in found):
        print("\nA dead record is one whose process is gone; `zettcode daemon kill <id>` removes it.")
    return EXIT_OK


def _entry(record: Record) -> list[str]:
    """Return one daemon as ``list`` prints it: its id and state first, then one field per line."""
    state = record.state
    head = f"{record.session_id}  {record.status}  {_age(record.seconds())}"
    if state is None:
        return [head, *block([("name", "-"), ("workspace", "not recorded")])]
    fields = [
        ("name", state.name or "-"),
        ("title", state.title or "-"),
        ("workspace", _short_path(state.workspace)),
        ("model", f"{state.model or '?'}" + (f" · effort {state.effort}" if state.effort else "")),
        ("context", _context_cell(state)),
        ("input", _tokens_cell(state.input_tokens)),
        ("output", _tokens_cell(state.output_tokens)),
        ("shell", state.permission or "?"),
    ]
    if state.requested_model is not None or state.requested_effort is not None:
        wanted = state.requested_model or state.model or "?"
        level = f" · effort {state.requested_effort}" if state.requested_effort is not None else ""
        fields.append(("next", f"{wanted}{level}"))
    if state.requested_error is not None:
        fields.append(("error", state.requested_error))
    if state.broker is False and not record.dead:
        fields.append(("broker", "offline: not reachable, and it keeps trying"))
    return [head, *block(fields)]


def _tokens_cell(count: int | None) -> str:
    """Return a token count in the short form a line has room for; ``None`` is a daemon that has counted none."""
    if count is None:
        return "-"
    if count < 1_000:
        return str(count)
    # The thresholds are where rounding would carry into the next unit: 999_950 tokens is 1M, not 1000k.
    if count < 999_950:
        return _short(count / 1_000, "k")
    if count < 999_950_000:
        return _short(count / 1_000_000, "M")
    return _short(count / 1_000_000_000, "G")


def _short(value: float, unit: str) -> str:
    """Return one decimal of ``value`` with ``unit``, dropping a ``.0`` that says nothing."""
    return f"{value:.1f}{unit}".replace(f".0{unit}", unit)


def _context_cell(state: State) -> str:
    """Return how full the context was, of what window and as a share of it, when the daemon recorded both."""
    if not state.context_tokens:
        return "-"
    if not state.context_window or state.context_tokens >= state.context_window:
        # At or past the window this is not a share of it: the shell refuses such a figure for the same reason.
        return _tokens_cell(state.context_tokens)
    share = round(100 * state.context_tokens / state.context_window)
    return f"{_tokens_cell(state.context_tokens)} of {_tokens_cell(state.context_window)} · {share}%"


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
        "requested_model": state.requested_model if state is not None else None,
        "requested_effort": state.requested_effort if state is not None else None,
        "requested_error": state.requested_error if state is not None else None,
        "broker": state.broker if state is not None else None,
        "input_tokens": state.input_tokens if state is not None else None,
        "output_tokens": state.output_tokens if state is not None else None,
        "context_tokens": state.context_tokens if state is not None else None,
        "context_window": state.context_window if state is not None else None,
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
            title=args.title,
            permission=args.permission,
        )
    except SpawnFailed as error:
        sys.stderr.write(f"zettcode daemon: could not start: {error}\n")
        if error.log is not None:
            sys.stderr.write(f"the daemon's first words are in {error.log}\n")
        return EXIT_FAILED
    state = record.state
    if args.json:
        print(json.dumps(_record_json(record), indent=2))
        return EXIT_OK
    print(f"session  {record.session_id}")
    if state is not None:
        if state.name:
            print(f"name     {state.name}")
        if state.title:
            print(f"title    {state.title}")
        print(f"workspace {state.workspace}")
        print(f"model    {state.model or '?'}" + (f" · effort {state.effort}" if state.effort else ""))
        print(f"shell    {state.permission or '?'}")
    print()
    print(f'send_message(to="{record.session_id}", message="...")')
    return EXIT_OK


def _models(workspace: Path, as_json: bool) -> int:
    """Print the models `spawn --model` can name, marking the one a daemon would run on by default.

    Read with the SDK's file reader, so no client is built and no session is touched: the names are the ones
    `spawn --model` matches, which is what the reader needs to choose.
    """
    from ..sdk.models import list_models

    try:
        found = list_models()
    except ValueError as error:
        sys.stderr.write(f"zettcode daemon: {error}\n")
        return EXIT_FAILED
    if not found:
        sys.stderr.write(
            f"zettcode daemon: no models configured for {workspace}; add one with /config, or in the file\n"
        )
        return EXIT_FAILED
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": model.name,
                        "model": model.model,
                        "default": index == 0,
                        "context_window": model.context_window,
                        "multimodal": model.multimodal,
                        "api": model.api,
                        "efforts": list(model.efforts),
                    }
                    for index, model in enumerate(found)
                ],
                indent=2,
            )
        )
        return EXIT_OK
    rows: list[tuple[str, ...]] = [("NAME", "MODEL", "API", "IMAGES", "CONTEXT", "EFFORTS")]
    for index, model in enumerate(found):
        rows.append(
            (
                model.name + (" (default)" if index == 0 else ""),
                model.model,
                model.api,
                "yes" if model.multimodal else "no",
                f"{model.context_window:,}",
                ", ".join(model.efforts),
            )
        )
    for line in table(rows):
        print(line)
    print("\nPick one with: zettcode daemon spawn --model <name>")
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


def _update(args: argparse.Namespace) -> int:
    """Change a daemon's label, its session's name, or what it runs on, and print what is recorded now."""
    from .process import Daemons, UpdateFailed
    from .state import Registry

    if args.title is None and args.name is None and args.model is None and args.effort is None:
        sys.stderr.write("nothing to change: give --title, --name, --model or --effort\n")
        return EXIT_USAGE
    registry = Registry()
    record = registry.find(args.session)
    if record is None:
        sys.stderr.write(f"no daemon with that session: {args.session}\n")
        return EXIT_FAILED
    try:
        updated = Daemons(registry).update(
            record, title=args.title, name=args.name, model=args.model, effort=args.effort
        )
    except UpdateFailed as error:
        sys.stderr.write(f"zettcode daemon: {error}\n")
        return EXIT_FAILED
    if args.json:
        print(json.dumps(_record_json(updated), indent=2))
        return EXIT_OK
    state = updated.state
    print(f"session  {updated.session_id}")
    if state is not None:
        print(f"name     {state.name or '-'}")
        print(f"title    {state.title or '-'}")
        print(f"model    {state.model or '?'}" + (f" · effort {state.effort}" if state.effort else ""))
        if state.requested_model is not None or state.requested_effort is not None:
            wanted = state.requested_model or state.model or "?"
            level = f" · effort {state.requested_effort}" if state.requested_effort is not None else ""
            print(f"next     {wanted}{level}")
        if state.requested_error is not None:
            print(f"error    {state.requested_error}")
        if state.broker is False and not updated.dead:
            print("broker   offline: not reachable, and it keeps trying")
    return EXIT_OK


def _prompt(args: argparse.Namespace) -> int:
    """Send a daemon a prompt through the session broker, and say what the broker did with it."""
    import httpx

    from ..broker.files import broker_dir, read_note
    from ..broker.protocol import PROTOCOL_VERSION, Refused
    from .state import Registry

    record = Registry().find(args.session)
    if record is None:
        sys.stderr.write(f"no daemon with that session: {args.session}\n")
        return EXIT_FAILED
    note = read_note(broker_dir())
    if note is None:
        sys.stderr.write("no session broker is running, so a daemon cannot be reached\n")
        return EXIT_FAILED
    if note.version != PROTOCOL_VERSION:
        sys.stderr.write(f"the session broker speaks protocol {note.version}, not {PROTOCOL_VERSION}; restart it\n")
        return EXIT_FAILED
    text = " ".join(args.text).strip()
    if not text:
        sys.stderr.write("a prompt needs some text\n")
        return EXIT_USAGE
    body = {
        "to": record.session_id,
        "text": text,
        "via": "external",
        "from": {"name": "zettcode daemon prompt"},
    }
    try:
        response = httpx.post(
            f"http://127.0.0.1:{note.port}/messages",
            json=body,
            headers={"Authorization": f"Bearer {note.token}"},
            # The broker waits for the recipient's ack (ten seconds by default) and only then answers; a timeout
            # as short as that would turn "it may still be delivered" into "the broker is unreachable".
            timeout=15.0,
            trust_env=False,
        )
    except httpx.HTTPError as error:
        sys.stderr.write(f"zettcode daemon: the broker could not be reached: {error}\n")
        return EXIT_FAILED
    try:
        answer = response.json()
    except ValueError:
        answer = None
    if response.status_code != 200 or not isinstance(answer, dict):
        refused = Refused.from_wire(answer.get("error") if isinstance(answer, dict) else None)
        sys.stderr.write(f"zettcode daemon: {refused}\n")
        return EXIT_FAILED
    disposition = answer.get("disposition")
    disposition = disposition if isinstance(disposition, str) and disposition else "sent"
    if args.json:
        print(json.dumps({"session": record.session_id, "disposition": disposition}, indent=2))
    else:
        print(f"{record.session_id}  {disposition}")
    return EXIT_OK


def _log(session: str, lines: int) -> int:
    """Print the last lines a daemon wrote about itself."""
    from ..sdk.daemons import daemon_log
    from ..sdk.errors import SessionNotFoundError

    try:
        text = daemon_log(session, lines=lines)
    except SessionNotFoundError:
        sys.stderr.write(f"no daemon with that session: {session}\n")
        return EXIT_FAILED
    print(text or "(nothing logged)")
    return EXIT_OK


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
        title=args.title,
        permission=args.permission,
    )
    try:
        return asyncio.run(serve(options))
    except KeyboardInterrupt:
        return EXIT_OK


def _positive(text: str) -> int:
    """Parse a count of lines for ``daemon log``: one at least, refused rather than quietly changed."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("at least one line")
    return value


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
