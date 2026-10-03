"""The ZettCode interface: the application shell and the widgets it composes."""

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
