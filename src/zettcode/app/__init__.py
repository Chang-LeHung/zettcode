"""ZettCode's application layer, split into its interface and its agent glue.

``ui`` holds what the user sees and drives: the transcript and the application
shell. ``agent`` holds the adapter that turns agent events into transcript
entries. This module is the facade over both, so ``from zettcode.app import
ZettCodeApp`` keeps working for callers that do not care where it lives.
"""

from __future__ import annotations

import importlib

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Entry": ".agent",
    "Transcript": ".agent",
    "TranscriptProjector": ".agent",
    "TranscriptSource": ".ui",
    "TranscriptView": ".ui",
    "ZettCodeAgent": ".agent",
    "ZettCodeApp": ".ui",
    "ZettCodeRoot": ".ui",
    "ZettCodeRuntime": ".agent",
}


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
    "Entry",
    "Transcript",
    "TranscriptProjector",
    "TranscriptSource",
    "TranscriptView",
    "ZettCodeApp",
    "ZettCodeAgent",
    "ZettCodeRoot",
    "ZettCodeRuntime",
]
