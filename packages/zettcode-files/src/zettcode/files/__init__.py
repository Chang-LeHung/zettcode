"""The files of the workspace as ``@`` references: the provider and the plugin that registers it.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point.
"""

from __future__ import annotations

from .mentions import FileMentions
from .plugin import FileResources

__all__ = ["FileMentions", "FileResources"]
