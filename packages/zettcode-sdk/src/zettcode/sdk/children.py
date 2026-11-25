"""The daemon handoff around a model-issued shell command, scoped to that tool task only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zett_agent.extensions.base import AgentExtension

from zettcode.daemon import CHILD_STATE_ENV
from zettcode.engine.plugins.children import ChildSession, encode_child_state
from zettcode.engine.plugins.environment import shell_environment

if TYPE_CHECKING:
    from zett_agent.agent import AgentRunContext
    from zett_agent.extensions.base import ToolCallNext
    from zett_agent.messages import ToolCall
    from zett_agent.tools.base import ToolResult

    from zettcode.engine.plugins import Plugins


class ChildEnvironment(AgentExtension):
    """Give ``bash``'s subprocess the active plugins' daemon snapshot, without changing ``os.environ``."""

    name = "PluginChildEnvironment"

    def __init__(self, plugins: Plugins) -> None:
        self.plugins = plugins
        # Wrap even a plugin host that replaces bash without calling the local handler.
        self.priority = min((plugin.priority for plugin in plugins.plugins), default=100) - 1

    async def on_tool_call(self, context: AgentRunContext, call: ToolCall, call_next: ToolCallNext) -> ToolResult:
        if call.name != "bash":
            return await call_next()
        state = self.plugins.export_child(ChildSession("daemon"))
        # Even an empty snapshot masks stale process-level handoffs. The daemon removes its copy before building
        # any tools, and each future bash exports again from the active plugins.
        with shell_environment({CHILD_STATE_ENV: encode_child_state(state)}):
            return await call_next()
