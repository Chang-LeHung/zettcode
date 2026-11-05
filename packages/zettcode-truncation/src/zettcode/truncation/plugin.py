"""The plugin that keeps an over-long tool result in the session's folder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.plugin import Plugin
from zettcode.engine.plugins.services import PERSISTENCE
from zettcode.engine.storage import SessionStore

from .extension import LongOutputExtension

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


class LongOutput(Plugin):
    """Keeps a result over a tool's budget in a file, and sends its start and its end instead.

    The tools in this repository bound what they return themselves; this is the backstop for the ones that come
    from elsewhere — an MCP server, a subagent, a plugin — so one long answer cannot fill the context of every
    later request in the session. It states the priority nearly everything shares, and it is handed over ahead of
    the session store because it has to see the result first.
    """

    name = "long-output"
    description = "Keeps over-long tool results in the session folder"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension over the session store."""
        ctx.agent.register_extension(LongOutputExtension(ctx.service(PERSISTENCE, SessionStore)))
