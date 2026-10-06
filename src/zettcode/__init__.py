"""Terminal coding agent built on zett-agent."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: The one place the version is written. ``pyproject.toml`` reads it from here
#: and the release workflow checks the tag against it, so a bump is one edit.
__version__ = "0.1.2"

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "ModelConfig": ".config",
    "ZettCodeAgent": ".app.agent.agent",
    "ZettCodeConfig": ".config",
    "ZettCodeRuntime": ".app.agent.runtime",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .app.agent.agent import ZettCodeAgent
    from .app.agent.runtime import ZettCodeRuntime
    from .config import ModelConfig, ZettCodeConfig


def __getattr__(name: str) -> object:
    """Import the module a public name lives in, the first time it is asked for.

    This package is a facade over several subpackages, and a caller that wants
    one name should not pay for the rest of them — the TUI alone holds the
    widget library, the Markdown parser, the diff viewer, and the syntax
    scanners. ``__all__`` is still the public surface.
    """
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    """Return the names this package publishes."""
    return sorted(__all__)


__all__ = ["ModelConfig", "ZettCodeAgent", "ZettCodeConfig", "ZettCodeRuntime"]
