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
    "AskUserPage": ".ask_page",
    "BashPage": ".bash_page",
    "CommandCompleter": ".completer",
    "Composer": ".composer",
    "LOCK_CAPTIONS": ".composer",
    "UPDATING_CAPTIONS": ".composer",
    "ContextPage": ".context_page",
    "DocumentPage": ".document_page",
    "EFFORT_ROWS": ".effort_page",
    "EffortPage": ".effort_page",
    "FollowUpQueue": ".follow_up",
    "FORM_CHROME_ROWS": ".form_page",
    "HARNESS_ROWS": ".harness_page",
    "HarnessPage": ".harness_page",
    "Field": ".form_page",
    "FormPage": ".form_page",
    "form_rows": ".form_page",
    "model_settings_rows": ".model_settings_page",
    "INPUT_ROWS": ".input_page",
    "InputPage": ".input_page",
    "LATER": ".update_page",
    "ModelPage": ".model_page",
    "ModelSettingsPage": ".model_settings_page",
    "PetView": ".pet",
    "PetPage": ".pet_page",
    "PluginRow": ".plugins_page",
    "PluginsPage": ".plugins_page",
    "SEND_KIND_ROWS": ".send_kind_page",
    "SELF_COMPACT_ROWS": ".self_compact_page",
    "SKIP": ".update_page",
    "SelfCompactPage": ".self_compact_page",
    "SendKind": ".send_kind_page",
    "SendKindPage": ".send_kind_page",
    "SessionsPage": ".sessions_page",
    "SteeringQueue": ".steering",
    "StatuslinePage": ".statusline_page",
    "TranscriptSource": ".transcript",
    "TranscriptView": ".transcript",
    "UPGRADE": ".update_page",
    "UpdatePage": ".update_page",
    "UsagePage": ".usage_page",
    "WELCOME": ".welcome",
    "ZettCodeRoot": ".root",
    "bottom_panel": ".panel",
    "format_ago": ".sessions_page",
    "help_text": ".completer",
    "pet_rows": ".pet_page",
    "statusline_rows": ".statusline_page",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .approval_page import ApprovalChoice, ApprovalPage
    from .ask_page import AskUserPage
    from .bash_page import BashPage
    from .completer import CommandCompleter, help_text
    from .composer import LOCK_CAPTIONS, UPDATING_CAPTIONS, Composer
    from .context_page import ContextPage
    from .document_page import DocumentPage
    from .effort_page import EFFORT_ROWS, EffortPage
    from .follow_up import FollowUpQueue
    from .form_page import FORM_CHROME_ROWS, Field, FormPage, form_rows
    from .harness_page import HARNESS_ROWS, HarnessPage
    from .input_page import INPUT_ROWS, InputPage
    from .model_page import ModelPage
    from .model_settings_page import ModelSettingsPage, model_settings_rows
    from .panel import bottom_panel
    from .pet import PetView
    from .pet_page import PetPage, pet_rows
    from .plugins_page import PluginRow, PluginsPage
    from .root import ZettCodeRoot
    from .self_compact_page import SELF_COMPACT_ROWS, SelfCompactPage
    from .send_kind_page import SEND_KIND_ROWS, SendKind, SendKindPage
    from .sessions_page import SessionsPage, format_ago
    from .statusline_page import StatuslinePage, statusline_rows
    from .steering import SteeringQueue
    from .transcript import TranscriptSource, TranscriptView
    from .update_page import LATER, SKIP, UPGRADE, UpdatePage
    from .usage_page import UsagePage
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
    "AskUserPage",
    "BashPage",
    "CommandCompleter",
    "Composer",
    "ContextPage",
    "DocumentPage",
    "EFFORT_ROWS",
    "EffortPage",
    "FollowUpQueue",
    "FORM_CHROME_ROWS",
    "HARNESS_ROWS",
    "HarnessPage",
    "Field",
    "FormPage",
    "form_rows",
    "INPUT_ROWS",
    "InputPage",
    "LATER",
    "LOCK_CAPTIONS",
    "ModelPage",
    "ModelSettingsPage",
    "PetView",
    "PetPage",
    "PluginRow",
    "PluginsPage",
    "SEND_KIND_ROWS",
    "SELF_COMPACT_ROWS",
    "SKIP",
    "SelfCompactPage",
    "SendKind",
    "SendKindPage",
    "SessionsPage",
    "SteeringQueue",
    "StatuslinePage",
    "TranscriptSource",
    "TranscriptView",
    "UPGRADE",
    "UPDATING_CAPTIONS",
    "UpdatePage",
    "UsagePage",
    "WELCOME",
    "ZettCodeRoot",
    "bottom_panel",
    "format_ago",
    "help_text",
    "model_settings_rows",
    "pet_rows",
    "statusline_rows",
]
