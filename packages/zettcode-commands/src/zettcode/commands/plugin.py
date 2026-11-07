"""The plugin that offers the slash commands that act on the application.

One plugin, not one per command group, so the order ``/help`` lists them in is the order they are registered here and
does not depend on how the loader happens to sort entry-point names. It is found through the ``zettcode.plugin``
entry point and is one the terminal requires: with no ``/help``, no ``/plugins`` and no ``/model`` there would be no
way back to a working setup from inside the program.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.plugin_api.plugin import TuiPlugin

from .handlers import (
    BashCommand,
    CodeReview,
    HelpCommand,
    ModelCommands,
    PluginCommand,
    SessionCommands,
    ShellControl,
    SideQuestion,
)
from .hub import HubCommand
from .usage import UsageCommand

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class CommandsPlugin(TuiPlugin):
    """``/help``, ``/plugins``, ``/resume``, ``/model``, ``/btw``, ``/review``, ``/bash``, ``/clear``, ``/usage``…"""

    name = "commands"
    description = "The slash commands that act on the application"

    def __init__(self) -> None:
        #: The command groups, in the order ``/help`` lists them.
        self.groups: tuple[TuiPlugin, ...] = (
            HelpCommand(),
            PluginCommand(),
            SessionCommands(),
            ModelCommands(),
            SideQuestion(),
            CodeReview(),
            BashCommand(),
            ShellControl(),
            UsageCommand(),
            HubCommand(),
        )

    def activate(self, ctx: PluginContext) -> None:
        """Register every group's commands, in order, on this plugin's own context."""
        if ctx.tui is None:
            return
        for group in self.groups:
            group.activate(ctx)
