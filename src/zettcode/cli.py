"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line: ``-w``/``--workspace`` picks
the directory to work in, ``-r``/``--resume`` picks the stored session to open
instead of a fresh one, and ``$ZETTCODE_CONFIG`` can point at a different
config file.

Nothing beyond the standard library is imported at module level: ``zettcode
--help`` prints and exits, and paying for the agent runtime, the widget
library, or the theme loader before the user has asked for a session would make
the one command that needs none of them the slowest.
"""

from __future__ import annotations

import argparse
import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ZettCodeConfig


def parse_args(argv: list[str] | None = None) -> tuple[Path, str | None]:
    """Return the workspace to run in and the session to resume, if any.

    Args:
        argv: Arguments to parse; ``None`` reads the process's own.
    """
    parser = argparse.ArgumentParser(
        prog="zettcode",
        description="Run the ZettCode terminal coding agent",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="directory to work in (default: the current directory)",
    )
    parser.add_argument(
        "-r",
        "--resume",
        metavar="SESSION",
        default=None,
        help="open a stored session by id instead of starting a new one",
    )
    args = parser.parse_args(argv)
    return args.workspace, args.resume


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace positional, defaulting to the current directory."""
    return parse_args(argv)[0]


def resume_command(session_id: str, workspace: Path) -> str:
    """Return the command that reopens one stored session from anywhere."""
    return f"zettcode --resume {shlex.quote(session_id)} --workspace {shlex.quote(str(workspace))}"


def session_exists(config: ZettCodeConfig, session_id: str) -> bool:
    """Return whether the store holds a session with this id in this workspace."""
    from .app.agent.storage import SessionStore

    return SessionStore(config.store, config.workspace).read(session_id).header is not None


def resolve_config(argv: list[str] | None = None) -> ZettCodeConfig:
    """Build the settings from the config file, reporting a bad file as a clean exit.

    The workspace is parsed first: ``--help`` exits inside ``argparse``, and it
    would be absurd for the flag that explains the program to load the agent
    runtime on the way out.
    """
    workspace, _ = parse_args(argv)
    from .config import load_config
    from .tui.capabilities import detect_reduced_motion

    try:
        return load_config(workspace, reduced_motion_default=detect_reduced_motion())
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error


async def async_main(config: ZettCodeConfig, *, resume: str | None = None) -> None:
    """Own runtime lifecycle around the full-screen application.

    The runtime is built by the first turn, not here: ``preview`` has
    everything the shell paints with, and the provider SDK is imported while
    the reader is looking at the first frame.

    Args:
        config: Settings loaded from the config file.
        resume: Stored session to open instead of a fresh one; an id the store
            does not hold is reported before the terminal is taken over.
    """
    from .app import ZettCodeApp
    from .app.agent.agent import ZettCodeAgent
    from .tui import DARK, ThemeFileError, load_theme

    if resume is not None and not session_exists(config, resume):
        raise SystemExit(f"zettcode: no session {resume} in {config.store}")
    try:
        theme = load_theme(config.theme_file) if config.theme_file is not None else DARK
    except ThemeFileError as error:
        raise SystemExit(f"zettcode: {error}") from error
    agent = ZettCodeAgent.preview(config)
    app = ZettCodeApp(agent, theme=theme, auto_theme=config.theme_file is None)
    if resume is not None:
        app.restore_session(resume)
    try:
        await app.run()
    finally:
        await agent.aclose()
        # The reader leaves the shell; the way back in is worth one line.
        print(f"\nresume this session: {resume_command(agent.session_id, config.workspace)}\n")


def main() -> None:
    """Installed console-script entry point."""
    _, resume = parse_args()
    asyncio.run(async_main(resolve_config(), resume=resume))


if __name__ == "__main__":
    main()
