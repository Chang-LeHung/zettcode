"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line; the single argument is the
workspace, and ``$ZETTCODE_CONFIG`` can point at a different config file.

Nothing beyond the standard library is imported at module level: ``zettcode
--help`` prints and exits, and paying for the agent runtime, the widget
library, or the theme loader before the user has asked for a session would make
the one command that needs none of them the slowest.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ZettCodeConfig


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace positional, defaulting to the current directory."""
    parser = argparse.ArgumentParser(description="Run the ZettCode terminal coding agent")
    parser.add_argument("workspace", nargs="?", type=Path, default=Path.cwd())
    return parser.parse_args(argv).workspace


def resolve_config(argv: list[str] | None = None) -> ZettCodeConfig:
    """Build the settings from the config file, reporting a bad file as a clean exit.

    The workspace is parsed first: ``--help`` exits inside ``argparse``, and it
    would be absurd for the flag that explains the program to load the agent
    runtime on the way out.
    """
    workspace = workspace_from_args(argv)
    from .config import load_config
    from .tui.capabilities import detect_reduced_motion

    try:
        return load_config(workspace, reduced_motion_default=detect_reduced_motion())
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error


async def async_main(config: ZettCodeConfig) -> None:
    """Own runtime lifecycle around the full-screen application."""
    from .app import ZettCodeApp
    from .app.agent.agent import ZettCodeAgent
    from .tui import DARK, ThemeFileError, load_theme

    try:
        theme = load_theme(config.theme_file) if config.theme_file is not None else DARK
    except ThemeFileError as error:
        raise SystemExit(f"zettcode: {error}") from error
    agent = await ZettCodeAgent.create(config)
    try:
        await ZettCodeApp(agent, theme=theme, auto_theme=config.theme_file is None).run()
    finally:
        await agent.aclose()


def main() -> None:
    """Installed console-script entry point."""
    asyncio.run(async_main(resolve_config()))


if __name__ == "__main__":
    main()
