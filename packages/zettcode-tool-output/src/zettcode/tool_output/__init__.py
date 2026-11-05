"""A shell command's kept output, moved into the session's folder: the plugin that hands it to the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point.
The extension (:mod:`zettcode.tool_output.extension`) reads the store the runtime provides under ``persistence``, so
nothing here builds one; it acts on the ``bash`` tool's result after the tool has run and before it is stored.
"""

from __future__ import annotations

from .plugin import ToolOutput

__all__ = ["ToolOutput"]
