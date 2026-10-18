"""The agent-side extensions ZettCode ships with, offered the way any plugin offers one.

Each class here owns one ``zett-agent`` extension and the switch in the configuration that turns it on, so
the runtime no longer lists them by hand: it asks the loaded plugins for what they contributed. They
register through :meth:`~zettcode.plugins.PluginContainer.register_extension`, which is also what a
third-party plugin uses, so a plugin that wraps a whole extension is not a second-class citizen.

The ``zett_agent`` imports are inside ``activate``: a plugin is activated only once the shell is going to
use it, and an extension a configuration switches off should not be imported for nothing.
"""

from __future__ import annotations

from .container import PluginContainer
from .plugin import Plugin

#: The service name the todo extension is provided under; the shell reads the plan through it.
TODOS_SERVICE = "todos"


class TodoPlan(Plugin):
    """The ``todo_write`` tool, and the plan it keeps, shown in the shell's panel.

    The extension is provided as a service whether or not the tool is on, because the shell asks it for the
    plan on every turn and an extension nobody registered simply has none to show. Only
    ``[agent] todowrite`` decides whether the model is given the tool.
    """

    name = "todos"
    description = "The todo_write tool and the plan it keeps"

    def activate(self, container: PluginContainer) -> None:
        """Provide the extension, and hand it to the agent when the tool is on."""
        from zett_agent.extensions.todo import TodoWriteExtension

        extension = TodoWriteExtension()
        container.provide(TODOS_SERVICE, extension)
        if container.config.todowrite_enabled:
            container.register_extension(extension)


class AskUser(Plugin):
    """The ``ask_user`` tool: how the model puts a question to the reader instead of guessing."""

    name = "ask-user"
    description = "The ask_user tool"

    def activate(self, container: PluginContainer) -> None:
        """Hand the agent the tool, unless the configuration turned it off."""
        if container.config.ask_user_enabled:
            from zett_agent.extensions.ask_user import AskUserExtension

            container.register_extension(AskUserExtension())


class ProjectInstructions(Plugin):
    """The workspace's ``AGENTS.md`` files, read again for every request so an edit applies at once."""

    name = "project-instructions"
    description = "The workspace's AGENTS.md instructions"

    def activate(self, container: PluginContainer) -> None:
        """Hand the agent the instructions, unless the configuration turned them off."""
        if container.config.agents_md_enabled:
            from zett_agent.extensions.agents_md import AgentsMdExtension

            container.register_extension(AgentsMdExtension(container.config.workspace))
