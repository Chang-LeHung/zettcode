"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line; the single argument is the
workspace, and ``$ZETTCODE_CONFIG`` can point at a different config file.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .app import ZettCodeApp
from .app.agent.agent import ZettCodeAgent
from .config import ZettCodeConfig, load_config
from .tui import DARK, ThemeFileError, detect_reduced_motion, load_theme


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace positional, defaulting to the current directory."""
    parser = argparse.ArgumentParser(description="Run the ZettCode terminal coding agent")
    parser.add_argument("workspace", nargs="?", type=Path, default=Path.cwd())
    return parser.parse_args(argv).workspace


def resolve_config(argv: list[str] | None = None) -> ZettCodeConfig:
    """Build the settings from the config file, reporting a bad file as a clean exit."""
    try:
        return load_config(workspace_from_args(argv), reduced_motion_default=detect_reduced_motion())
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error


async def async_main(config: ZettCodeConfig) -> None:
    """Own runtime lifecycle around the full-screen application."""
    try:
        theme = load_theme(config.theme_file) if config.theme_file is not None else DARK
    except ThemeFileError as error:
        raise SystemExit(f"zettcode: {error}") from error
    agent = await ZettCodeAgent.create(config)
    try:
        await ZettCodeApp(agent, theme=theme).run()
    finally:
        await agent.aclose()


def main() -> None:
    """Installed console-script entry point."""
    asyncio.run(async_main(resolve_config()))


if __name__ == "__main__":
    main()
