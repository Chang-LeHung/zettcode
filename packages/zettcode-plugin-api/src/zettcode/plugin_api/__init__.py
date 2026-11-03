"""What a plugin imports: one package, so one dependency.

A ZettCode plugin is a class published under the ``zettcode.plugins`` entry point, and everything it may touch is
re-exported here: the agent side (:mod:`zettcode.engine.plugins`), what only a screen has
(:mod:`zettcode.app.plugins`), the command a handler returns, and the widgets it may draw with. Installing this
distribution installs the engine, the widget framework and the terminal application, and nothing else to think about.

The names are the ones the guide shows in `docs/guide/plugins.md`; they are re-exports, not a second definition, so a
plugin and the program cannot disagree about a signature.
"""

from __future__ import annotations

from zettcode.app.commands import CommandContext, CommandHost, CommandResult, CommandUi
from zettcode.app.plugins import (
    HOST_LINK,
    HostLink,
    PluginUiMixin,
    ShellContext,
    TuiGroups,
    TuiPlugin,
    TuiPlugins,
    UiSlots,
    load_terminal_plugins,
)
from zettcode.app.plugins.loader import TerminalLoader, terminal_context
from zettcode.app.ui.widgets import bottom_panel
from zettcode.app.ui.widgets.panel import pressed
from zettcode.app.ui.widgets.statusline_page import SWITCH_WIDTH, draw_switch
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import (
    AgentBuild,
    Contribution,
    ExtensionFactory,
    Plugin,
    PluginAgentMixin,
    PluginContext,
    PluginEventMixin,
    PluginExtension,
    PluginMaintenanceMixin,
    PluginMiddlewareMixin,
    PluginModelMixin,
    PluginRunMixin,
    Plugins,
    PluginSetting,
    PluginSetupMixin,
    PluginToolMixin,
    PluginTurnMixin,
)
from zettcode.mention import Mention, MentionProvider
from zettcode.plugin_tui import TuiGroup
from zettcode.providers import Provider
from zettcode.registry import Registry
from zettcode.tui import Canvas, Host, MouseAction, MouseEvent, Span, Style, TextLine, Widget
from zettcode.tui.render import blend, display_width, truncate

__all__ = [
    "HOST_LINK",
    "AgentBuild",
    "Canvas",
    "CommandContext",
    "CommandHost",
    "CommandResult",
    "CommandUi",
    "Contribution",
    "ExtensionFactory",
    "Host",
    "HostLink",
    "Mention",
    "MentionProvider",
    "ModelConfig",
    "MouseAction",
    "MouseEvent",
    "Plugin",
    "PluginAgentMixin",
    "PluginContext",
    "PluginEventMixin",
    "PluginExtension",
    "PluginMaintenanceMixin",
    "PluginMiddlewareMixin",
    "PluginModelMixin",
    "PluginRunMixin",
    "PluginSetupMixin",
    "PluginSetting",
    "PluginToolMixin",
    "PluginTurnMixin",
    "PluginUiMixin",
    "Plugins",
    "Provider",
    "Registry",
    "SWITCH_WIDTH",
    "ShellContext",
    "Span",
    "Style",
    "TerminalLoader",
    "TextLine",
    "TuiGroup",
    "TuiGroups",
    "TuiPlugin",
    "TuiPlugins",
    "UiSlots",
    "Widget",
    "ZettCodeConfig",
    "blend",
    "bottom_panel",
    "display_width",
    "draw_switch",
    "load_terminal_plugins",
    "pressed",
    "terminal_context",
    "truncate",
]
