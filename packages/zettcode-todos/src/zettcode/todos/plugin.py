"""The plugin that keeps the plan the shell's panel draws."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.plugin import Plugin, PluginSetting
from zettcode.engine.plugins.services import TODOS

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


class TodoPlan(Plugin):
    """The ``todo_write`` tool, and the plan it keeps, shown in the shell's panel.

    The extension is provided as a service whether or not the tool is on, because the shell asks it for the
    plan on every turn and an extension nobody registered simply has none to show. Only
    ``[harness] todowrite`` decides whether the model is given the tool.
    """

    name = "todos"
    description = "The todo_write tool and the plan it keeps"
    setting = PluginSetting("todowrite_enabled", "harness", "todowrite")

    def activate(self, ctx: PluginContext) -> None:
        """Provide the extension, and hand it to the agent when the tool is on."""
        from zett_agent.extensions.todo import TodoWriteExtension

        extension = TodoWriteExtension()
        ctx.agent.provide(TODOS, extension)
        if ctx.config.todowrite_enabled:
            ctx.agent.register_extension(extension)
