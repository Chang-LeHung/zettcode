"""Agent-facing glue: the conversation model and the events that fill it."""

from __future__ import annotations

import importlib

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Entry": ".transcript",
    "Transcript": ".transcript",
    "TranscriptProjector": ".projection",
    "ZettCodeAgent": ".agent",
    "ZettCodeRuntime": ".runtime",
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


__all__ = ["Entry", "Transcript", "TranscriptProjector", "ZettCodeAgent", "ZettCodeRuntime"]
