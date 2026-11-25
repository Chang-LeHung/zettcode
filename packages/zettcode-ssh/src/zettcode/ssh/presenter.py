"""Opt SSH tools into the local rendering families without changing their identity."""

from __future__ import annotations

from typing import Any

from zettcode.plugin_api import Entry, NextPresenter, Presenter, TextLine
from zettcode.plugin_api.presenters import ToolRenderingAlias

PREFIX = "ssh__"
_TOOL_NAMES = frozenset({"read", "read_file", "write_file", "edit", "bash", "glob", "grep"})


class SSHToolNames(Presenter[Any]):
    """Supply explicit rendering aliases; the shell's own presenters draw the rows."""

    priority = 10

    def tool_rendering_alias(self, name: str) -> ToolRenderingAlias | None:
        """Only the plugin's known tools share local rendering, never arbitrary MCP suffixes."""
        if name.startswith(PREFIX) and name[len(PREFIX) :] in _TOOL_NAMES:
            return ToolRenderingAlias(name[len(PREFIX) :], "ssh/")
        return None

    def handle(self, entry: Entry, next: NextPresenter) -> Presenter[Any]:
        """Pass every entry on unchanged."""
        return next(entry)

    def lines(self, entry: Any, width: int, theme: Any, frame: int) -> list[TextLine]:
        """Never called: this presenter only supplies aliases."""
        raise AssertionError("SSHToolNames only supplies rendering aliases")


__all__ = ["PREFIX", "SSHToolNames"]
