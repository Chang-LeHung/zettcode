"""The MCP client of ZettCode: the plugin that connects the servers a configuration file names, and the extension it hands
the agent.

This is a part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point
and activated with the agent's other parts. ``[mcp] enabled`` in the configuration is what turns it off. The extension
(:mod:`zettcode.mcp.extension`) imports the MCP SDK, which costs more than the first frame, so nothing here imports it
until the agent is built.
"""

from __future__ import annotations

from .plugin import McpTools

__all__ = ["McpTools"]
