"""The engine's plugin support: the base class, the context, the loader, and the plugins the engine ships.

A plugin needs only this package::

    from zettcode.engine.plugins import Plugin, PluginContext

    class Audit(Plugin):
        name = "audit"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_extension(AuditExtension())

What a plugin can register follows from the groups on ``ctx``: :attr:`PluginContext.agent` in every process, and
:attr:`PluginContext.tui` where the terminal is loading. A plugin that fills a header or status row by overriding a
hook is a :class:`zettcode.app.plugins.TuiPlugin`, which is this class plus that mixin.

The pieces live in focused modules — :mod:`~zettcode.engine.plugins.mixins` for the hook groups,
:mod:`~zettcode.engine.plugins.context` for activation, :mod:`~zettcode.engine.plugins.plugin` for the base class, and
:mod:`~zettcode.engine.plugins.loader` for discovery — and are re-exported here as one surface.
"""

from __future__ import annotations

from .builtin_agent import AGENT_PLUGINS
from .context import PluginContext
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
from .plugin import Plugin, Plugins
from .state import AgentBuild, Contribution, ExtensionFactory
from .switches import PluginEntry, catalog, off_names, set_enabled

__all__ = [
    "AGENT_PLUGINS",
    "PLUGIN_ENTRY_POINT_GROUP",
    "AgentBuild",
    "Plugin",
    "PluginContext",
    "Contribution",
    "ExtensionFactory",
    "Loader",
    "PluginAgentMixin",
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
    "PluginEntry",
    "catalog",
    "installed_entry_points",
    "load_plugins",
    "off_names",
    "set_enabled",
]
