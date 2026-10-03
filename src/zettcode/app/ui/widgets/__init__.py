"""Widgets the ZettCode shell composes, one component per module.

These are the application's own pieces — the transcript view, the composer's
command completion, the model picker, the root, and the banner — as opposed to
``zettcode.tui``, which holds the reusable framework they are built from.
"""

from .completer import CommandCompleter, help_text
from .model_page import ModelPage
from .root import ZettCodeRoot
from .transcript import TranscriptSource, TranscriptView
from .welcome import WELCOME

__all__ = [
    "CommandCompleter",
    "ModelPage",
    "TranscriptSource",
    "TranscriptView",
    "WELCOME",
    "ZettCodeRoot",
    "help_text",
]
