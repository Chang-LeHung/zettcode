"""The MCP extension ZettCode hands to the runtime, with readable failures."""

from __future__ import annotations

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.mcp import McpExtension


class ReportingMcpExtension(McpExtension):
    """An MCP extension whose failures say which servers the request tried.

    One server that is not running fails the whole turn, and the failure arrives
    as a task-group exception naming nothing at all. Adding the configured names
    is the difference between "unhandled errors in a TaskGroup" and knowing that
    the server is simply not up.

    The module is imported when a runtime starts, not when the application is
    imported: the MCP SDK it builds on costs more than the first frame.
    """

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register remote tools, or fail with the server names in the text."""
        from .runtime import describe_error

        try:
            await super().on_tool(context)
        except BaseException as error:
            names = ", ".join(server.name for server in self.servers)
            raise RuntimeError(f"MCP unavailable ({names}): {describe_error(error)}") from error
