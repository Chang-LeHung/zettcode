"""What a plugin imports: the contract, and the one dependency it needs.

A ZettCode plugin is a class published under the ``zettcode.plugin`` entry point, and everything it may touch is
re-exported here: the base classes and hooks of the agent side and of the terminal's rows, the command a handler returns,
the row model and the presenter it implements, the pet format, the link to the shell, and the few widgets a panel is
drawn with.

This package is the bottom of the graph a plugin lives in. The engine, the widget framework and the SDK are what it
needs; it imports neither the terminal application nor any implementation of the contracts it defines. The built-in rows
(`zettcode-presenters`), the shell and the loader that builds ``ctx.tui`` (`zettcode-app`) are written *against* it, which
is what lets a plugin and the program replace each other's parts without either importing the other.

The names are resolved on first use, like the program's other facades: importing one row constant must not pull the
settings, the runtime and a provider SDK in with it, because the boot frame is drawn before any of them exist.

The names are the ones the guide shows in `docs/guide/plugins.md`. They are re-exports, not a second definition, so a
plugin and the program cannot disagree about a signature.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Activity": ".state",
    "ActivityState": ".state",
    "AgentBuild": "zettcode.engine.plugins",
    "BusyPolicy": ".commands",
    "CONTENT_INDENT": ".presenters",
    "Canvas": "zettcode.tui",
    "ChangesEntry": ".entries",
    "Command": ".commands",
    "CommandAgent": ".commands",
    "CommandContext": ".commands",
    "CommandHandler": ".commands",
    "CommandHost": ".commands",
    "CommandList": ".commands",
    "CommandProvider": ".commands",
    "CommandResult": ".commands",
    "CommandTranscript": ".commands",
    "CommandUi": ".commands",
    "Contribution": "zettcode.engine.plugins",
    "DeleteEntry": ".entries",
    "DisplayState": ".state",
    "EditEntry": ".entries",
    "Entry": ".entries",
    "EntryKind": ".entries",
    "EntryStatus": ".entries",
    "ExtensionFactory": "zettcode.engine.plugins",
    "FileChangeEntry": ".entries",
    "FileSummary": ".entries",
    "HOST_LINK": ".host",
    "Host": "zettcode.tui",
    "HostLink": ".host",
    "MarkdownEntry": ".entries",
    "Mention": "zettcode.mention",
    "MentionProvider": "zettcode.mention",
    "MessageEntry": ".entries",
    "ModelConfig": "zettcode.config",
    "ModelState": ".state",
    "MouseAction": "zettcode.tui",
    "MouseEvent": "zettcode.tui",
    "NoticeLevel": ".entries",
    "Pet": ".pets",
    "PetSource": ".pets",
    "PlainCommandContext": "zettcode.engine.plugins.commands",
    "PlainCommandHost": "zettcode.engine.plugins.commands",
    "Plugin": "zettcode.engine.plugins",
    "PluginAgentMixin": "zettcode.engine.plugins",
    "PluginContext": "zettcode.engine.plugins",
    "PluginEventMixin": "zettcode.engine.plugins",
    "PluginExtension": "zettcode.engine.plugins",
    "PluginMaintenanceMixin": "zettcode.engine.plugins",
    "PluginMiddlewareMixin": "zettcode.engine.plugins",
    "PluginModelMixin": "zettcode.engine.plugins",
    "PluginRunMixin": "zettcode.engine.plugins",
    "PluginSetting": "zettcode.engine.plugins",
    "PluginSetupMixin": "zettcode.engine.plugins",
    "PluginToolMixin": "zettcode.engine.plugins",
    "PluginTurnMixin": "zettcode.engine.plugins",
    "PluginUiMixin": ".mixins",
    "Plugins": "zettcode.engine.plugins",
    "Presenter": ".presenters",
    "Presenters": ".presenters",
    "Provider": "zettcode.providers",
    "Rail": ".switch",
    "ReadEntry": ".entries",
    "Registry": "zettcode.registry",
    "RelayEntry": ".entries",
    "Row": ".rows",
    "SWITCH_WIDTH": ".switch",
    "SessionState": ".state",
    "ShellContext": ".state",
    "Span": "zettcode.tui",
    "Style": "zettcode.tui",
    "Subcommand": ".commands",
    "TextCommandResult": "zettcode.engine.plugins.commands",
    "TextEntry": ".entries",
    "TextLine": "zettcode.tui",
    "ThinkingEntry": ".entries",
    "ToolEntry": ".entries",
    "TuiGroup": "zettcode.plugin_tui",
    "TuiPlugin": ".plugin",
    "TuiPlugins": ".plugin",
    "Trigger": "zettcode.engine.plugins",
    "TriggerEvent": "zettcode.engine.plugins",
    "TriggerScope": "zettcode.engine.plugins",
    "TurnCommandResult": "zettcode.engine.plugins.commands",
    "TurnSegment": ".state",
    "UiBuilder": ".state",
    "UiRegion": ".state",
    "UiRow": ".state",
    "UiSegment": ".state",
    "UiSide": ".state",
    "WaitEntry": ".entries",
    "Widget": "zettcode.tui",
    "WriteEntry": ".entries",
    "ZettCodeConfig": "zettcode.config",
    "blend": "zettcode.tui.render",
    "bottom_panel": ".panels",
    "display_width": "zettcode.tui.render",
    "draw_switch": ".switch",
    "pressed": ".panels",
    "truncate": "zettcode.tui.render",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
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
        Trigger,
        TriggerEvent,
        TriggerScope,
    )
    from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult, TurnCommandResult
    from zettcode.mention import Mention, MentionProvider
    from zettcode.plugin_tui import TuiGroup
    from zettcode.providers import Provider
    from zettcode.registry import Registry
    from zettcode.tui import Canvas, Host, MouseAction, MouseEvent, Span, Style, TextLine, Widget
    from zettcode.tui.render import blend, display_width, truncate

    from .commands import (
        BusyPolicy,
        Command,
        CommandAgent,
        CommandContext,
        CommandHandler,
        CommandHost,
        CommandList,
        CommandProvider,
        CommandResult,
        CommandTranscript,
        CommandUi,
        Subcommand,
    )
    from .entries import (
        ChangesEntry,
        DeleteEntry,
        EditEntry,
        Entry,
        EntryKind,
        EntryStatus,
        FileChangeEntry,
        FileSummary,
        MarkdownEntry,
        MessageEntry,
        NoticeLevel,
        ReadEntry,
        RelayEntry,
        TextEntry,
        ThinkingEntry,
        ToolEntry,
        WaitEntry,
        WriteEntry,
    )
    from .host import HOST_LINK, HostLink
    from .mixins import PluginUiMixin
    from .panels import bottom_panel, pressed
    from .pets import Pet, PetSource
    from .plugin import TuiPlugin, TuiPlugins
    from .presenters import CONTENT_INDENT, Presenter, Presenters
    from .rows import Row
    from .state import (
        Activity,
        ActivityState,
        DisplayState,
        ModelState,
        SessionState,
        ShellContext,
        TurnSegment,
        UiBuilder,
        UiRegion,
        UiRow,
        UiSegment,
        UiSide,
    )
    from .switch import SWITCH_WIDTH, Rail, draw_switch


def __getattr__(name: str) -> Any:
    """Import the module a public name lives in, the first time it is asked for.

    Args:
        name: The public name the plugin asked for.

    Returns:
        What that module defines under the name.

    Raises:
        AttributeError: The package has no such name.
    """
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "Activity",
    "ActivityState",
    "AgentBuild",
    "BusyPolicy",
    "CONTENT_INDENT",
    "Canvas",
    "ChangesEntry",
    "Command",
    "CommandAgent",
    "CommandContext",
    "CommandHandler",
    "CommandHost",
    "CommandList",
    "CommandProvider",
    "CommandResult",
    "CommandTranscript",
    "CommandUi",
    "Contribution",
    "DeleteEntry",
    "DisplayState",
    "EditEntry",
    "Entry",
    "EntryKind",
    "EntryStatus",
    "ExtensionFactory",
    "FileChangeEntry",
    "FileSummary",
    "HOST_LINK",
    "Host",
    "HostLink",
    "MarkdownEntry",
    "Mention",
    "MentionProvider",
    "MessageEntry",
    "ModelConfig",
    "ModelState",
    "MouseAction",
    "MouseEvent",
    "NoticeLevel",
    "Pet",
    "PetSource",
    "PlainCommandContext",
    "PlainCommandHost",
    "Plugin",
    "PluginAgentMixin",
    "PluginContext",
    "PluginEventMixin",
    "PluginExtension",
    "PluginMaintenanceMixin",
    "PluginMiddlewareMixin",
    "PluginModelMixin",
    "PluginRunMixin",
    "PluginSetting",
    "PluginSetupMixin",
    "PluginToolMixin",
    "PluginTurnMixin",
    "PluginUiMixin",
    "Plugins",
    "Presenter",
    "Presenters",
    "Provider",
    "Rail",
    "ReadEntry",
    "Registry",
    "RelayEntry",
    "Row",
    "SWITCH_WIDTH",
    "SessionState",
    "ShellContext",
    "Span",
    "Style",
    "Subcommand",
    "TextCommandResult",
    "TextEntry",
    "TextLine",
    "ThinkingEntry",
    "ToolEntry",
    "TuiGroup",
    "TuiPlugin",
    "TuiPlugins",
    "Trigger",
    "TriggerEvent",
    "TriggerScope",
    "TurnCommandResult",
    "TurnSegment",
    "UiBuilder",
    "UiRegion",
    "UiRow",
    "UiSegment",
    "UiSide",
    "WaitEntry",
    "Widget",
    "WriteEntry",
    "ZettCodeConfig",
    "blend",
    "bottom_panel",
    "display_width",
    "draw_switch",
    "pressed",
    "truncate",
]
