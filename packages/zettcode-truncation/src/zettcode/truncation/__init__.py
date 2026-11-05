"""A result too long to send, kept whole in the session's folder: the plugin that hands this to the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point.
The extension (:mod:`zettcode.truncation.extension`) reads the store the runtime provides under ``persistence``; it
runs before the store's own extension, so what the store appends is the preview and not the megabyte.
"""

from __future__ import annotations

from .plugin import LongOutput

__all__ = ["LongOutput"]
