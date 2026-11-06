"""The plugin that registers the guidance each tool carries in its own description."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class ToolGuidance(Plugin[PluginContext]):
    """The guidance each tool carries: its call shapes, guidelines and return type, in the tool's own description."""

    name = "tool-guidelines"
    description = "Per-tool guidance in each tool's description"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension as a factory: it is built with the agent, not while the first frame is drawn."""

        # Imported in the factory: the extension imports the framework's tool-guidelines module, which a launch that
        # never builds an agent does not need.
        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.guidance import tool_guidance

            return tool_guidance()

        ctx.agent.register_extension_factory("ToolGuidelinesExtension", build)
