"""The ZettCode interface: the application shell and the widgets it composes."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "CommandCompleter": ".widgets",
    "ModelPage": ".widgets",
    "TranscriptSource": ".widgets",
    "TranscriptView": ".widgets",
    "WELCOME": ".widgets",
    "ZettCodeApp": ".app",
    "ZettCodeRoot": ".widgets",
    "help_text": ".widgets",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .app import ZettCodeApp
    from .widgets import (
        WELCOME,
        CommandCompleter,
        ModelPage,
        TranscriptSource,
        TranscriptView,
        ZettCodeRoot,
        help_text,
    )


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


__all__ = [
    "CommandCompleter",
    "ModelPage",
    "TranscriptSource",
    "TranscriptView",
    "WELCOME",
    "ZettCodeApp",
    "ZettCodeRoot",
    "help_text",
]
