"""Agent-facing glue: the conversation model and the events that fill it."""

from .projection import TranscriptProjector
from .runtime import ZettCodeRuntime
from .transcript import Entry, Transcript

__all__ = ["Entry", "Transcript", "TranscriptProjector", "ZettCodeRuntime"]
