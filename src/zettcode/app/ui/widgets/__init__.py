"""Widgets the ZettCode shell composes, one component per module.

These are the application's own pieces — the transcript view, the composer's
command completion, the model picker, the session list, the approval prompt,
the root, and the banner — as opposed to ``zettcode.tui``, which holds the
reusable framework they are built from.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "ApprovalChoice": ".approval_page",
    "ApprovalPage": ".approval_page",
    "CommandCompleter": ".completer",
    "Composer": ".composer",
    "ContextPage": ".context_page",
    "LATER": ".update_page",
    "ModelPage": ".model_page",
    "SKIP": ".update_page",
    "SessionsPage": ".sessions_page",
    "SteeringQueue": ".steering",
    "TranscriptSource": ".transcript",
    "TranscriptView": ".transcript",
    "UPGRADE": ".update_page",
    "UpdatePage": ".update_page",
    "WELCOME": ".welcome",
    "ZettCodeRoot": ".root",
    "bottom_panel": ".panel",
    "format_ago": ".sessions_page",
    "help_text": ".completer",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .approval_page import ApprovalChoice, ApprovalPage
    from .completer import CommandCompleter, help_text
    from .composer import Composer
    from .context_page import ContextPage
    from .model_page import ModelPage
    from .panel import bottom_panel
    from .root import ZettCodeRoot
    from .sessions_page import SessionsPage, format_ago
    from .steering import SteeringQueue
    from .transcript import TranscriptSource, TranscriptView
    from .update_page import LATER, SKIP, UPGRADE, UpdatePage
    from .welcome import WELCOME


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
    "LATER",
    "ModelPage",
    "SKIP",
    "SessionsPage",
    "SteeringQueue",
    "TranscriptSource",
    "TranscriptView",
    "UPGRADE",
    "UpdatePage",
    "WELCOME",
    "ZettCodeRoot",
    "bottom_panel",
    "format_ago",
    "help_text",
]
