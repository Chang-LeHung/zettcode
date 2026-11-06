"""The plugin that hands the agent the ``ask_user`` tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class AskUser(Plugin[PluginContext]):
    """The ``ask_user`` tool: how the model puts a question to the reader instead of guessing."""

    name = "ask-user"
    description = "The ask_user tool"
    setting = PluginSetting("ask_user_enabled", "ask_user")

    def activate(self, ctx: PluginContext) -> None:
        """Hand the agent the tool, unless the configuration turned it off."""
        if not ctx.config.ask_user_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.ask_user import AskUserExtension

            return AskUserExtension()

        ctx.agent.register_extension_factory("AskUserExtension", build)
