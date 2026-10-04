"""Widgets the ZettCode shell composes, one component per module.

These are the application's own pieces — the transcript view, the composer's
command completion, the model picker, the session list, the approval prompt,
the root, and the banner — as opposed to ``zettcode.tui``, which holds the
reusable framework they are built from.
"""

from __future__ import annotations

import importlib

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "ApprovalChoice": ".approval_page",
    "ApprovalPage": ".approval_page",
    "CommandCompleter": ".completer",
    "Composer": ".composer",
    "ContextPage": ".context_page",
    "ModelPage": ".model_page",
    "SessionsPage": ".sessions_page",
    "TranscriptSource": ".transcript",
    "TranscriptView": ".transcript",
    "WELCOME": ".welcome",
    "ZettCodeRoot": ".root",
    "bottom_panel": ".panel",
    "format_ago": ".sessions_page",
    "help_text": ".completer",
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
    "ApprovalChoice",
    "ApprovalPage",
    "CommandCompleter",
    "Composer",
    "ContextPage",
    "ModelPage",
    "SessionsPage",
    "TranscriptSource",
    "TranscriptView",
    "WELCOME",
    "ZettCodeRoot",
    "bottom_panel",
    "format_ago",
    "help_text",
]
