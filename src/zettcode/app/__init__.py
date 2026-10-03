"""ZettCode's application layer, split into its interface and its agent glue.

``ui`` holds what the user sees and drives: the transcript and the application
shell. ``agent`` holds the adapter that turns agent events into transcript
entries. This module is the facade over both, so ``from zettcode.app import
ZettCodeApp`` keeps working for callers that do not care where it lives.
"""

from .agent import Entry, Transcript, TranscriptProjector, ZettCodeAgent, ZettCodeRuntime
from .ui import TranscriptSource, TranscriptView, ZettCodeApp, ZettCodeRoot

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
