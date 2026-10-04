"""Widgets the ZettCode shell composes, one component per module.

These are the application's own pieces — the transcript view, the composer's
command completion, the model picker, the session list, the approval prompt,
the root, and the banner — as opposed to ``zettcode.tui``, which holds the
reusable framework they are built from.
"""

from .approval_page import ApprovalChoice, ApprovalPage
from .completer import CommandCompleter, help_text
from .composer import Composer
from .context_page import ContextPage
from .model_page import ModelPage
from .panel import bottom_panel
from .root import ZettCodeRoot
from .sessions_page import SessionsPage, format_ago
from .transcript import TranscriptSource, TranscriptView
from .welcome import WELCOME

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
