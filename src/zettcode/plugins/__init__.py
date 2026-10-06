"""Plugin support: the public API, the adapter, and the entry-point loader.

A plugin author needs only this package::

    from zettcode.plugins import CommandResult, Plugin, PluginContainer

    class Greeter(Plugin):
        name = "greeter"

        def activate(self, container: PluginContainer) -> None:
            container.register_command("greet", "say hello", self.greet)

        async def greet(self, argument: str) -> CommandResult:
            return CommandResult(notification=f"hello {argument}".strip())

The distribution then publishes ``greeter = "my_package:Greeter"`` under the
``zettcode.plugins`` entry-point group and ZettCode picks it up at startup.

The pieces live in focused modules — :mod:`~zettcode.plugins.state` for the
snapshot and segment types, :mod:`~zettcode.plugins.mixins` for the hook groups,
:mod:`~zettcode.plugins.container` for activation, :mod:`~zettcode.plugins.plugin`
for the base class, and :mod:`~zettcode.plugins.loader` for discovery — and are
re-exported here as one surface.
"""

from __future__ import annotations

from ..app.commands import Command, CommandResult
from ..tui import Span, Style, TextLine, Theme
from .builtins import BUILTIN_PLUGINS
from .container import CommandHandler, PluginContainer
from .extension import PluginExtension
from .loader import PLUGIN_ENTRY_POINT_GROUP, installed_entry_points, load_plugins
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
    PluginUiMixin,
)
from .plugin import Plugin, Plugins
from .state import (
    Activity,
    ActivityState,
    DisplayState,
    ModelState,
    SessionState,
    ShellContext,
    UiBuilder,
    UiRegion,
    UiRow,
    UiSegment,
    UiSide,
)

__all__ = [
    "PLUGIN_ENTRY_POINT_GROUP",
    "Activity",
    "ActivityState",
    "BUILTIN_PLUGINS",
    "UiBuilder",
    "UiRegion",
    "UiRow",
    "UiSide",
    "Command",
    "CommandHandler",
    "CommandResult",
    "DisplayState",
    "ModelState",
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
    "PluginUiMixin",
    "Plugins",
    "SessionState",
    "ShellContext",
    "Span",
    "Style",
    "TextLine",
    "Theme",
    "UiSegment",
    "installed_entry_points",
    "load_plugins",
]
