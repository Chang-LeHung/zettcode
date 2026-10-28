"""The ``zettcode-gateway`` program: parse the command line, then serve until stopped.

``--help`` and ``--version`` answer before anything heavy is imported.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from zettcode import __version__

from .settings import DEFAULT_HOST, DEFAULT_PORT, TOKEN_VARIABLE, Settings, default_directory

LOOPBACK = ("127.0.0.1", "::1", "localhost")


def build_parser() -> argparse.ArgumentParser:
    """Return the parser: where to listen, who may sign in, and where agents may be started."""
    parser = argparse.ArgumentParser(
        prog="zettcode-gateway",
        description=(
            "A web page for the background agents on this machine: list the daemons and the sessions that are "
            "running, start and stop daemons, and talk to any of them. It works from a phone as well."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"interface to listen on (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--token",
        default=None,
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
        default=None,
        help=(
            "limit daemons to this directory and below (repeatable). By default any directory may be chosen; "
            "with -r, nothing outside the roots can"
        ),
    )
    parser.add_argument(
        "--no-full",
        action="store_true",
        help="do not let the page start daemons with the full shell level (no sandbox, no approval)",
    )
    parser.add_argument(
        "--directory",
        metavar="DIR",
        type=Path,
        default=None,
        help="where the gateway keeps its own session and what the page remembers (default: ~/.zettcode/gateway)",
    )
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="uvicorn's log level (default: info)",
    )
    parser.add_argument("--version", action="version", version=version_text())
    return parser


def version_text() -> str:
    """Return the line ``--version`` prints: the gateway and the agent are one package, so one version."""
    return f"zettcode-gateway {__version__}"


def settings_from(argv: list[str] | None = None) -> Settings:
    """Return the settings the arguments name; ``--help`` exits here, and so does an unsafe combination."""
    args = build_parser().parse_args(argv)
    if not 0 < args.port < 65536:
        raise SystemExit(f"zettcode-gateway: --port must be between 1 and 65535, not {args.port}")
    roots = tuple((root.expanduser()).resolve() for root in (args.root or [Path(Path.home().anchor or "/")]))
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        raise SystemExit(f"zettcode-gateway: no such directory: {', '.join(missing)}")
    token = args.token or os.environ.get(TOKEN_VARIABLE) or ""
    if not token and args.host not in LOOPBACK:
        raise SystemExit(
            f"zettcode-gateway: listening on {args.host} needs a token (--token or ${TOKEN_VARIABLE}): "
            "without one anybody on the network could run commands as you"
        )
    directory = args.directory.expanduser() if args.directory is not None else default_directory()
    settings = Settings(
        token=token,
        host=args.host,
        port=args.port,
        roots=roots,
        allow_full=not args.no_full,
        directory=directory,
        log_level=args.log_level,
    )
    return settings


def main(argv: list[str] | None = None) -> None:
    """Installed console-script entry point: serve until interrupted."""
    settings = settings_from(sys.argv[1:] if argv is None else argv)
    from .app import create_app

    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - the wheel declares it
        raise SystemExit(f"zettcode-gateway: uvicorn is not installed: {error}") from error

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
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
