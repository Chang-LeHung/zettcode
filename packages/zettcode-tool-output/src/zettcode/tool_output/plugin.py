"""The plugin that moves a shell command's kept output into the session's folder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.plugin import Plugin
from zettcode.engine.plugins.services import PERSISTENCE
from zettcode.engine.storage import SessionStore

from .extension import ToolOutputExtension

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


class ToolOutput(Plugin):
    """Moves a long tool result into the session's folder before it is stored or sent anywhere.

    The extension acts on what the ``bash`` tool wrote, so it registers at the same priority as the coding bundle and
    is handed over after it: a run keeps the order the extensions registered in wherever their priorities agree.
    """

    name = "tool-output"
    description = "Keeps long tool output in the session folder"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension over the session store."""
        ctx.agent.register_extension(ToolOutputExtension(ctx.service(PERSISTENCE, SessionStore)))
