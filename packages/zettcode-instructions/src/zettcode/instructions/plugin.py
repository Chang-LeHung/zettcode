"""The plugin that hands the agent the workspace's project instructions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.plugin import Plugin, PluginSetting

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.context import PluginContext
    from zettcode.engine.plugins.state import AgentBuild


class ProjectInstructions(Plugin):
    """The workspace's ``AGENTS.md`` files, read again for every request so an edit applies at once."""

    name = "project-instructions"
    description = "The workspace's AGENTS.md instructions"
    setting = PluginSetting("agents_md_enabled", "agents_md")

    def activate(self, ctx: PluginContext) -> None:
        """Hand the agent the instructions, unless the configuration turned them off."""
        config = ctx.config
        if not config.agents_md_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.agents_md import AgentsMdExtension

            return AgentsMdExtension(config.workspace)

        ctx.agent.register_extension_factory("AgentsMdExtension", build)
