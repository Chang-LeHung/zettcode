"""The ``zettcode gateway`` command: serve the page, or start, stop and restart it in the background.

Run through the ``zettcode`` console script, so ``zettcode gateway --help`` answers before anything heavy is
imported.

    zettcode gateway                 # serve in this terminal until interrupted
    zettcode gateway start [flags]   # serve in the background and return
    zettcode gateway stop            # stop the one that is running
    zettcode gateway restart [flags]  # stop it, then start again with these settings (or the ones it had)
    zettcode gateway serve [flags]   # the same as the bare command

A gateway writes down the pid and settings it is serving with once it is a session (:mod:`.runfile`); ``stop`` and
``restart`` read that record, check the process is really a gateway before signalling it, and a restart with no flags
reuses the recorded settings, so a token or port is not lost by restarting.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from zettcode import __version__, logging_setup
from zettcode.processes import command_line, is_module_command, still_there

from . import runfile
from .settings import DEFAULT_HOST, DEFAULT_PORT, TOKEN_VARIABLE, Settings, default_directory

logger = logging.getLogger("zettcode.gateway")

LOOPBACK = ("127.0.0.1", "::1", "localhost")

#: The module the background gateway runs as, so the process can be recognised before it is stopped.
GATEWAY_MODULE = "zettcode.gateway.cli"

#: Seconds a gateway that was just started has to become a session and open its port.
START_WAIT = 12.0

#: Seconds a gateway is given to leave after it was asked, and after it was made to.
STOP_GRACE = 10.0
STOP_FORCE = 2.0

#: How often a port, a record or a process is looked at while waiting.
POLL = 0.2

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    """Return the parser: the action, where to listen, who may sign in, and where agents may be started."""
    parser = argparse.ArgumentParser(
        prog="zettcode gateway",
        description=(
            "A web page for the background agents on this machine: list the daemons and the sessions that are "
            "running, start and stop daemons, and talk to any of them. It works from a phone as well. With no "
            "action it serves in this terminal; start, stop and restart manage one in the background."
        ),
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("serve", "start", "stop", "restart"),
        default="serve",
        help="serve here (the default), or start, stop or restart a background gateway",
    )
    # The defaults are suppressed so that `restart` can tell which settings were given from the ones it should keep
    # from the running gateway; the help text says what each default is.
    parser.add_argument("--host", default=argparse.SUPPRESS, help=f"interface to listen on (default: {DEFAULT_HOST})")
    parser.add_argument(
        "--port", type=int, default=argparse.SUPPRESS, help=f"port to listen on (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--token",
        default=argparse.SUPPRESS,
        help=(
            f"what to type to sign in (default: ${TOKEN_VARIABLE}). With none there is no sign-in, which is only "
            "allowed while listening on this machine alone"
        ),
    )
    parser.add_argument(
        "-r",
        "--root",
        metavar="DIR",
        action="append",
        type=Path,
        default=argparse.SUPPRESS,
        help=(
            "limit daemons to this directory and below (repeatable). By default any directory may be chosen; "
            "with -r, nothing outside the roots can"
        ),
    )
    parser.add_argument(
        "--no-full",
        action="store_true",
        default=argparse.SUPPRESS,
        help="do not let the page start daemons with the full shell level (no sandbox, no approval)",
    )
    parser.add_argument(
        "--full",
        dest="no_full",
        action="store_false",
        default=argparse.SUPPRESS,
        help="let the page start daemons with the full shell level again, undoing a recorded --no-full",
    )
    parser.add_argument(
        "--directory",
        metavar="DIR",
        type=Path,
        default=argparse.SUPPRESS,
        help="where the gateway keeps its own session and what the page remembers (default: ~/.zettcode/gateway)",
    )
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default=argparse.SUPPRESS,
        help="uvicorn's log level (default: info)",
    )
    parser.add_argument("--version", action="version", version=version_text())
    return parser


def version_text() -> str:
    """Return the line ``--version`` prints: the gateway and the agent are one package, so one version."""
    return f"zettcode gateway {__version__}"


def settings_from(argv: list[str] | None = None, *, base: Settings | None = None) -> Settings:
    """Return the settings the arguments name; ``--help`` exits here, and so does an unsafe combination.

    Args:
        argv: The arguments to read; the process's own when ``None``.
        base: Settings to keep where the arguments say nothing, which is how a restart keeps the host, port and
            token the running gateway was started with. ``None`` uses the defaults.
    """
    args = build_parser().parse_args(argv)
    host = getattr(args, "host", None) or (base.host if base is not None else DEFAULT_HOST)
    port = getattr(args, "port", None)
    if port is None:
        port = base.port if base is not None else DEFAULT_PORT
    token = getattr(args, "token", None)
    if token is None:
        # A restart keeps the token the gateway was started with before the environment is consulted: a stale
        # exported token must not silently change the sign-in of the page that is already open.
        if base is not None:
            token = base.token
        else:
            token = os.environ.get(TOKEN_VARIABLE) or ""
    roots_given = getattr(args, "root", None)
    if roots_given is None:
        roots = base.roots if base is not None and base.roots else (Path(Path.home().anchor or "/"),)
    else:
        roots = tuple(root.expanduser().resolve() for root in roots_given)
    no_full = getattr(args, "no_full", None)
    if no_full is None:
        allow_full = base.allow_full if base is not None else True
    else:
        allow_full = not no_full
    directory_given = getattr(args, "directory", None)
    if directory_given is not None:
        directory = directory_given.expanduser()
    else:
        directory = base.directory if base is not None else default_directory()
    log_level = getattr(args, "log_level", None) or (base.log_level if base is not None else "info")

    if not 0 < port < 65536:
        raise SystemExit(f"zettcode gateway: --port must be between 1 and 65535, not {port}")
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        raise SystemExit(f"zettcode gateway: no such directory: {', '.join(missing)}")
    if not token and host not in LOOPBACK:
        raise SystemExit(
            f"zettcode gateway: listening on {host} needs a token (--token or ${TOKEN_VARIABLE}): "
            "without one anybody on the network could run commands as you"
        )
    return Settings(
        token=token,
        host=host,
        port=port,
        roots=roots,
        allow_full=allow_full,
        directory=directory,
        log_level=log_level,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point of ``zettcode gateway``: serve, or start, stop, restart one in the background."""
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    action = args.action
    if action == "stop":
        raise SystemExit(stop(_directory_from(args)))
    if action == "restart":
        recorded = runfile.read(_directory_from(args))
        base = recorded.settings if recorded is not None else None
        raise SystemExit(restart(settings_from(raw, base=base)))
    settings = settings_from(raw)
    if action == "start":
        raise SystemExit(start(settings))
    serve(settings)


def serve(settings: Settings) -> None:
    """Serve in this terminal until interrupted. The record is written by the application once it is a session."""
    from .app import create_app

    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - the wheel declares it
        raise SystemExit(f"zettcode gateway: uvicorn is not installed: {error}") from error

    _say(settings)
    logging_setup.setup("gateway")
    logging_setup.rotate_text(runfile.log_path(settings.directory))
    try:
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level=settings.log_level)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        logger.exception("serve.failed", extra={"host": settings.host, "port": settings.port})
        raise


def start(settings: Settings) -> int:
    """Start a gateway in the background unless one is serving, and say where it is."""
    record = runfile.read(settings.directory)
    if record is not None:
        state = _state(record)
        if state == "gateway":
            _say(record.settings)
            if settings != record.settings:
                print("the settings given were not applied; stop the gateway first to change them")
            print(f"the gateway is already running (pid {record.pid})")
            return EXIT_OK
        if state == "unknown":
            print(
                f"a process (pid {record.pid}) may be the gateway at {record.settings.url} but its command line "
                f"could not be read; not starting another. Its record is {runfile.path(settings.directory)}; remove "
                "it once nothing is serving there",
                file=sys.stderr,
            )
            return EXIT_FAILED
        runfile.clear(settings.directory)
    try:
        process = spawn(settings)
    except OSError as error:
        logger.exception("spawn.failed", extra={"host": settings.host, "port": settings.port})
        print(f"the gateway could not be started: {error}", file=sys.stderr)
        return EXIT_FAILED
    if not wait_serving(settings, process):
        print(f"the gateway did not start; the log is {runfile.log_path(settings.directory)}", file=sys.stderr)
        runfile.clear(settings.directory, pid=process.pid)
        return EXIT_FAILED
    _say(settings)
    print(f"the gateway is running in the background (pid {process.pid})")
    return EXIT_OK


def stop(directory: Path, *, quiet: bool = False) -> int:
    """Stop the gateway serving from ``directory``, and say what happened.

    A record whose process is gone or is not a gateway any more is removed rather than acted on: a pinned process
    can be reused, and ending the wrong one would be worse than not ending the right one. A process that exists but
    whose command line cannot be read is neither: the record is kept and the command fails, because a gateway that
    may be serving would otherwise be left with no way to stop it.

    Args:
        directory: The gateway folder whose record is read.
        quiet: Say nothing; a restart that reports the start it made does not also report the stop it made.
    """

    def say(text: str, *, err: bool = False, always: bool = False) -> None:
        if quiet and not always:
            return
        print(text, file=sys.stderr if err else sys.stdout)

    record = runfile.read(directory)
    if record is None:
        say("the gateway is not running")
        return EXIT_OK
    state = _state(record)
    if state in ("gone", "other"):
        runfile.clear(directory, pid=record.pid)
        say("the gateway is not running")
        return EXIT_OK
    if state == "unknown":
        say(
            f"a process (pid {record.pid}) may be the gateway at {record.settings.url} but its command line could "
            f"not be read; it was not stopped. Its record is {runfile.path(directory)}; remove it once nothing is "
            "serving there",
            err=True,
            always=True,
        )
        return EXIT_FAILED
    pid = record.pid
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        runfile.clear(directory, pid=pid)
        say("the gateway is not running")
        return EXIT_OK
    if _wait_gone(pid, STOP_GRACE) or _force(pid, STOP_FORCE):
        runfile.clear(directory, pid=pid)
        say(f"stopped the gateway ({pid})")
        return EXIT_OK
    say(f"the gateway ({pid}) did not stop", err=True, always=True)
    return EXIT_FAILED


def restart(settings: Settings) -> int:
    """Stop the gateway serving from this directory if one is, then start one with ``settings``."""
    stopped = stop(settings.directory, quiet=True)
    if stopped != EXIT_OK:
        return stopped
    return start(settings)


def spawn(settings: Settings) -> subprocess.Popen[bytes]:
    """Start a gateway as a process of its own, detached, writing to the gateway's log; the token goes in its environment.

    The sign-in token is not put on the command line: a background process's arguments are visible to the whole
    machine, and the token is what keeps others out. The child inherits it through :data:`TOKEN_VARIABLE`, and it
    writes its own record once it is serving.
    """
    runfile.ensure_directory(settings.directory)
    arguments = [
        sys.executable,
        "-m",
        GATEWAY_MODULE,
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--directory",
        str(settings.directory),
        "--log-level",
        settings.log_level,
    ]
    if not settings.allow_full:
        arguments.append("--no-full")
    for root in settings.roots:
        arguments.extend(("--root", str(root)))
    environment = {**os.environ, TOKEN_VARIABLE: settings.token}
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "cwd": str(settings.directory),
        "close_fds": True,
        "env": environment,
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined,unused-ignore]
        )
    else:
        options["start_new_session"] = True
    with open(runfile.log_path(settings.directory), "ab") as output:
        return subprocess.Popen(arguments, stdout=output, stderr=output, **options)  # noqa: S603


def wait_serving(settings: Settings, process: subprocess.Popen[bytes]) -> bool:
    """Wait for the child to record itself and open its port; ``False`` when it exited or never got there."""
    deadline = time.monotonic() + START_WAIT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        record = runfile.read(settings.directory)
        if record is not None and record.pid == process.pid and _connectable(settings):
            # A port that accepted one connection may still be a server that fails on start-up; give it a moment.
            time.sleep(0.2)
            return process.poll() is None
        time.sleep(POLL)
    return False


def _state(record: runfile.Running) -> Literal["gateway", "other", "unknown", "gone"]:
    """Return what the recorded pid is now: ``"gateway"``, ``"other"`` (reused), ``"unknown"`` (alive, unreadable) or ``"gone"``.

    The two unclear answers are kept apart on purpose: a pid that exists but whose command line cannot be read may be
    the gateway, and neither starting a second one nor ending it on a guess is right.
    """
    text = command_line(record.pid)
    if text is not None:
        return "gateway" if _is_gateway(text) else "other"
    return "unknown" if still_there(record.pid) else "gone"


def _is_gateway(text: str) -> bool:
    """Return whether a command line is this gateway: ``python -m zettcode.gateway.cli``, or the console script."""
    if is_module_command(text, GATEWAY_MODULE):
        return True
    # The console script: `python /…/bin/zettcode gateway …` on POSIX, `"…\zettcode.exe" gateway …` on Windows.
    return re.search(r"(?:^|[\s/\\\"])zettcode(?:\.exe)?\"?\s+gateway(?:\s|$)", text, re.IGNORECASE) is not None


def _connectable(settings: Settings) -> bool:
    """Return whether something accepts a connection at the gateway's address."""
    host = settings.host
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    try:
        with socket.create_connection((host, settings.port), timeout=0.25):
            return True
    except OSError:
        return False


def _wait_gone(pid: int, seconds: float) -> bool:
    """Wait until the process is no longer there: its command line cannot be read *and* it does not exist."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _gone(pid):
            return True
        time.sleep(POLL)
    return _gone(pid)


def _gone(pid: int) -> bool:
    """Return whether the process is gone, not merely unreadable."""
    return command_line(pid) is None and not still_there(pid)


def _force(pid: int, seconds: float) -> bool:
    """Make the process stop, after it ignored the signal to leave — but only while it is still this gateway."""
    if _wait_gone(pid, 0.0):
        return True
    text = command_line(pid)
    if text is None:
        return False  # it cannot be identified any more: report that rather than kill on a guess
    if not _is_gateway(text):
        return True  # the pid now belongs to something else; leave it alone
    try:
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except OSError:
        return True
    return _wait_gone(pid, seconds)


def _directory_from(args: argparse.Namespace) -> Path:
    """Return the gateway folder the arguments name, without building (and validating) every other setting."""
    given = getattr(args, "directory", None)
    return given.expanduser() if given is not None else default_directory()


def _say(settings: Settings) -> None:
    """Print where the page is, how to sign in, and what its agents may do."""
    print(version_text(), flush=True)
    if settings.open:
        print(f"  open     {settings.url}", flush=True)
        print("  sign-in  none: anybody on this machine can use it (give --token to ask for one)", flush=True)
    else:
        print(f"  open     {settings.url}/#token={settings.token}", flush=True)
    anywhere = len(settings.roots) == 1 and settings.roots[0] == settings.roots[0].parent
    print(
        "  agents   may be started in: " + ("any directory" if anywhere else ", ".join(map(str, settings.roots))),
        flush=True,
    )
    print(f"  shell    full level {'allowed' if settings.allow_full else 'not allowed (--no-full)'}", flush=True)
    if settings.host not in LOOPBACK:
        print(
            f"  warning  listening on {settings.host}: anyone who can reach this port and has the token can run "
            "commands as you. This page is plain HTTP; put it behind TLS.",
            flush=True,
        )


__all__ = [
    "GATEWAY_MODULE",
    "build_parser",
    "main",
    "restart",
    "serve",
    "settings_from",
    "spawn",
    "start",
    "stop",
    "version_text",
    "wait_serving",
]


if __name__ == "__main__":
    main()
