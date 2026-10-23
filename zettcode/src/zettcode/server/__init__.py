"""ZettCode behind an HTTP API: the coding agent, driven by `zettcode.sdk`, one workspace per process.

The server is a thin layer: an endpoint says what to ask the agent and how to let a run answer for itself, and the
SDK does the work. It owns no model loop, no tools, and no session format, so a session begun here is one the
terminal can open afterwards, and the other way round.

It is part of this package, not a package of its own: one ``pip install zettcode`` writes both console scripts, the
terminal's ``zettcode`` and the server's ``zettcode-server``. The application is built by :func:`create_app`, and
served by :mod:`zettcode.server.cli`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only; importing the app costs FastAPI
    from .app import create_app
    from .settings import Settings

__all__ = ["Settings", "create_app"]


def __getattr__(name: str) -> Any:
    """Load the application on first use, so ``--version`` does not import FastAPI."""
    if name == "create_app":
        from .app import create_app

        return create_app
    if name == "Settings":
        from .settings import Settings

        return Settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
