"""The engine's plugin support: the base class, the context, the loader, and the switches.

A plugin needs only this package::

    from zettcode.engine.plugins import Plugin, PluginContext

    class Audit(Plugin[PluginContext]):
        name = "audit"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_extension(AuditExtension())

What a plugin can register follows from the groups on ``ctx``: :attr:`PluginContext.agent` in every process, and
:attr:`PluginContext.tui` where the terminal is loading. A plugin that fills a header or status row by overriding a
hook is a :class:`zettcode.app.plugins.TuiPlugin`, which is this class plus that mixin. The plugins ZettCode composes
the agent from are not here: they are :data:`zettcode.sdk.builtins.AGENT_PLUGINS`, because they need the broker, the
config file and the MCP client, which the engine does not carry.

The pieces live in focused modules — :mod:`~zettcode.engine.plugins.mixins` for the hook groups,
:mod:`~zettcode.engine.plugins.context` for activation, :mod:`~zettcode.engine.plugins.plugin` for the base class, and
:mod:`~zettcode.engine.plugins.loader` for discovery — and are re-exported here as one surface.
"""

from __future__ import annotations

from .cli import CliOption, installed_options
from .context import PluginContext
from .extension import PluginExtension
from .llm import ModelAccess
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
from .plugin import Plugin, Plugins, PluginSetting
from .services import (
    LLM,
    PLUGIN_AGENT,
    PLUGIN_CLI,
    PLUGIN_COMMANDS,
    PLUGIN_CONFIG,
    PLUGIN_SETTINGS,
    PLUGIN_TUI,
    PLUGIN_WORKSPACE,
)
from .state import AgentBuild, Contribution, ExtensionFactory
from .switches import PluginEntry, applied, catalog, off_names, set_enabled, set_many
from .triggers import Trigger, TriggerEvent, TriggerHost, TriggerScope, TriggerState, TriggerStatus

__all__ = [
    "PLUGIN_ENTRY_POINT_GROUP",
    "LLM",
    "ModelAccess",
    "CliOption",
    "PLUGIN_CLI",
    "installed_options",
    "PLUGIN_AGENT",
    "PLUGIN_COMMANDS",
    "PLUGIN_CONFIG",
    "PLUGIN_SETTINGS",
    "PLUGIN_TUI",
    "PLUGIN_WORKSPACE",
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
    "PluginSetting",
    "Trigger",
    "TriggerEvent",
    "TriggerHost",
    "TriggerScope",
    "TriggerState",
    "TriggerStatus",
    "applied",
    "catalog",
    "installed_entry_points",
    "load_plugins",
    "off_names",
    "set_enabled",
    "set_many",
]
