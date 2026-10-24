"""The engine's plugin support: the base class, the container, the loader, and the plugins the engine ships.

A plugin that contributes to the agent needs only this package::

    from zettcode.engine.plugins import AgentPlugin, PluginContainer

    class Audit(AgentPlugin):
        name = "audit"

        def activate(self, container: PluginContainer) -> None:
            container.register_extension(AuditExtension())

A plugin that also adds commands, palettes, pets, presenters or header and status rows is a
:class:`zettcode.app.plugins.TerminalPlugin`, which the terminal loads on top of these.

The pieces live in focused modules — :mod:`~zettcode.engine.plugins.mixins` for the hook groups,
:mod:`~zettcode.engine.plugins.container` for activation, :mod:`~zettcode.engine.plugins.plugin` for the base
class, and :mod:`~zettcode.engine.plugins.loader` for discovery — and are re-exported here as one surface.
"""

from __future__ import annotations

from .builtin_agent import AGENT_PLUGINS
from .container import PluginContainer
from .extension import PluginExtension
from .loader import PLUGIN_ENTRY_POINT_GROUP, Loader, installed_entry_points, load_plugins
from .mixins import (
    PluginAgentMixin,
    PluginEventMixin,
    PluginMaintenanceMixin,
    PluginMiddlewareMixin,
    PluginModelMixin,
    PluginRunMixin,
    PluginSetupMixin,
    PluginToolMixin,
    PluginTurnMixin,
)
from .plugin import AgentPlugin, Plugin, Plugins
from .state import AgentBuild, Contribution, ExtensionFactory

__all__ = [
    "AGENT_PLUGINS",
    "PLUGIN_ENTRY_POINT_GROUP",
    "AgentBuild",
    "AgentPlugin",
    "Contribution",
    "ExtensionFactory",
    "Loader",
    "Plugin",
    "PluginAgentMixin",
    "PluginContainer",
    "PluginEventMixin",
    "PluginExtension",
    "PluginMaintenanceMixin",
    "PluginMiddlewareMixin",
    "PluginModelMixin",
    "PluginRunMixin",
    "PluginSetupMixin",
    "PluginToolMixin",
    "PluginTurnMixin",
    "Plugins",
    "installed_entry_points",
    "load_plugins",
]
