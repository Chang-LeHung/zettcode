"""The plugin that hands the agent the tools MCP servers offer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class McpTools(Plugin[PluginContext]):
    """The tools MCP servers offer. A server that is down is skipped, never fatal."""

    name = "mcp"
    description = "MCP servers"
    setting = PluginSetting("mcp_enabled", "mcp")

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension when MCP is on; a run with no server file gets none at all."""
        config = ctx.config
        if not config.mcp_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension | None:
            from .extension import build_scoped_mcp_extension

            return build_scoped_mcp_extension(config.mcp_files())

        ctx.agent.register_extension_factory("ReportingMcpExtension", build)
