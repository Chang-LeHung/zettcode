"""The plain commands of the plugin system, for a program that runs one.

A plugin registers these on ``ctx.commands``: text for any front end to show, or a preset for a turn. They are
re-exported here because the server may not import the engine — the SDK is the door it has.
"""

from ..engine.plugins.commands import PlainCommand, PlainCommandContext, TextCommandResult, TurnCommandResult

__all__ = ["PlainCommand", "PlainCommandContext", "TextCommandResult", "TurnCommandResult"]
