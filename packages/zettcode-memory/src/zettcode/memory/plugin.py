"""The plugins that give the agent its workspace memory and its background-daemon guide."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class Memory(Plugin[PluginContext]):
    """The agent's persistent workspace memory; off until the reader asks for it."""

    name = "memory"
    description = "Persistent workspace memory"

    @classmethod
    def default_enabled(cls) -> bool:
        """Leave memory off until the reader asks for it with ``[plugins] enable``."""
        return False

    def activate(self, ctx: PluginContext) -> None:
        """Register the memory extension; its import waits for the build."""
        ctx.agent.register_extension_factory("MemoryExtension", self._memory)

    @staticmethod
    def _memory(_: AgentBuild) -> AgentExtension:
        from .extension import MemoryExtension

        return MemoryExtension()


class DaemonGuide(Plugin[PluginContext]):
    """Tell the model it can start a background agent, when the request can use one."""

    name = "daemon-guide"
    description = "The background-daemon guide"

    def activate(self, ctx: PluginContext) -> None:
        """Register the guide extension; its import waits for the build."""
        ctx.agent.register_extension_factory("DaemonGuideExtension", self._daemon_guide)

    @staticmethod
    def _daemon_guide(_: AgentBuild) -> AgentExtension:
        from .extension import DaemonGuideExtension

        return DaemonGuideExtension()
