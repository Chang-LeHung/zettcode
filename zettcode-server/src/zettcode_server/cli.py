"""The ``zettcode-server`` program: parse the command line, then serve until stopped.

Nothing heavy is imported until a server is actually started: ``--help`` and ``--version`` answer without loading
FastAPI, the agent, or the SDK, which is what keeps the command that explains the program the fastest one it has.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .settings import DEFAULT_HOST, DEFAULT_PERMISSION, DEFAULT_PORT, TOKEN_VARIABLE, Settings


def build_parser() -> argparse.ArgumentParser:
    """Return the parser: the workspace, the socket, the token, and how a run starts."""
    parser = argparse.ArgumentParser(
        prog="zettcode-server",
        description=(
            "Serve the ZettCode coding agent over HTTP, for one workspace. Prompts stream as server-sent events; "
            "sessions, models, settings, usage and the context report are plain JSON."
        ),
    )
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="directory the agent works in (default: the current directory)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"interface to bind (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to bind (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--token",
        default=None,
        help=f"bearer token every endpoint but /health requires (default: ${TOKEN_VARIABLE}, or none)",
    )
    parser.add_argument(
        "--permission",
        choices=("deny", "ask", "safe", "auto"),
        default=DEFAULT_PERMISSION,
        help=f"shell permission a run starts at (default: {DEFAULT_PERMISSION})",
    )
    parser.add_argument("--model", default=None, help="model to start on, by name (default: the first configured)")
    parser.add_argument("--effort", default=None, help="reasoning effort to start on (default: the model's own)")
    parser.add_argument("--config", metavar="FILE", type=Path, default=None, help="configuration file to read")
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="uvicorn's log level (default: info)",
    )
    parser.add_argument("--version", action="version", version=version_text())
    return parser


def version_text() -> str:
    """Return the line ``--version`` prints: the server, and the agent it serves."""
    from zettcode import __version__ as agent

    return f"zettcode-server {__version__} (zettcode {agent})"


def settings_from(argv: list[str] | None = None) -> Settings:
    """Return the settings the arguments name; ``--help`` and ``--version`` exit here, before any import."""
    args = build_parser().parse_args(argv)
    if not 0 < args.port < 65536:
        raise SystemExit(f"zettcode-server: --port must be between 1 and 65535, not {args.port}")
    workspace = args.workspace.expanduser()
    if not workspace.is_dir():
        raise SystemExit(f"zettcode-server: no such directory: {workspace}")
    return Settings(
        workspace=workspace.resolve(),
        host=args.host,
        port=args.port,
        token=args.token or os.environ.get(TOKEN_VARIABLE) or None,
        permission=args.permission,
        model=args.model,
        effort=args.effort,
        config_path=args.config.expanduser() if args.config is not None else None,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> None:
    """Installed console-script entry point: serve until interrupted."""
    settings = settings_from(sys.argv[1:] if argv is None else argv)
    from .app import create_app

    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - the wheel declares it
        raise SystemExit(f"zettcode-server: uvicorn is not installed: {error}") from error

    token = "on" if settings.token else "off"
    print(
        f"{version_text()} · {settings.url} · workspace {settings.workspace} · permission {settings.permission} "
        f"· token {token}",
        flush=True,
    )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
