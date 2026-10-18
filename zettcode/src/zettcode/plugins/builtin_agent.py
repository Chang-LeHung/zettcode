"""The agent-side extensions ZettCode ships with, offered the way any plugin offers one.

Each class here owns one ``zett-agent`` extension and the switch in the configuration that turns it on, so
the runtime lists none of them by hand: it asks the loaded plugins for what they contributed. They register
through :meth:`~zettcode.plugins.PluginContainer.register_extension` and
:meth:`~zettcode.plugins.PluginContainer.register_extension_factory`, which are also what a third-party
plugin uses, so a plugin that wraps a whole extension is not a second-class citizen.

Two rules decide how one registers:

* An extension that costs something to import, or needs the provider the agent starts on, is registered as
  a **factory**: a plugin activates while the first frame is still being drawn, and the factory is called
  only when the agent is built, after the imports the runtime warms up. The ``zett_agent`` imports are inside
  the factories for that reason.
* An object the application also has to reach (the plan, the usage counters, the compaction) is **provided**
  as a service by name, and the runtime reads it from there instead of keeping a field for it.

The order of :data:`AGENT_PLUGINS` is the order the agent receives the extensions in; extensions that share a
priority keep it, so it is the order they were listed in when the runtime did the listing. What a plugin
builds on (the session store, the permission policy) is handed over by the runtime by name, see
:mod:`zettcode.plugins.services`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..app.agent.dialogue.side import SideQuestions
from ..app.agent.extensions.capabilities import ModelCapabilities
from ..app.agent.extensions.compaction import CompactionCounter, OnDemandCompaction
from ..app.agent.extensions.context import ContextExtension
from ..app.agent.extensions.messenger import Messenger
from ..app.agent.extensions.tool_output import ToolOutputExtension
from ..app.agent.extensions.usage import UsageExtension
from ..app.agent.permission import ShellDenyExtension, ShellPolicy
from ..app.agent.permission.approval import ShellApprovalMemory
from ..app.agent.storage import SessionStore
from ..config import ModelConfig
from .container import PluginContainer
from .plugin import Plugin
from .services import (
    APPROVAL,
    CAPABILITIES,
    COMPACTION,
    COMPACTION_COUNTER,
    CONTEXT,
    MESSENGER,
    MODELS,
    PERSISTENCE,
    POLICY,
    SELECTED_MODEL,
    SIDES,
    TODOS,
    USAGE,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from .state import AgentBuild


class CodingTools(Plugin):
    """The coding bundle: the file tools, search and the shell tool."""

    name = "coding"
    description = "The file, search and shell tools"

    def activate(self, container: PluginContainer) -> None:
        """Register the bundle; it is the largest import the agent needs, so it waits for the build."""

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.coding import CodingExtension

            return CodingExtension()

        container.register_extension_factory("CodingExtension", build)


class ToolOutput(Plugin):
    """Moves a long tool result into the session's folder before it is stored or sent anywhere."""

    name = "tool-output"
    description = "Keeps long tool output in the session folder"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension over the session store."""
        container.register_extension(ToolOutputExtension(container.service(PERSISTENCE, SessionStore)))


class Capabilities(Plugin):
    """What the configured models can do, so a tool is not offered to one that cannot use it."""

    name = "capabilities"
    description = "Filters tools by what the model takes"

    def activate(self, container: PluginContainer) -> None:
        """Provide the filter, over the runtime's own table of the models it has built."""
        capabilities = ModelCapabilities(container.service(MODELS, dict))
        container.provide(CAPABILITIES, capabilities)
        container.register_extension(capabilities)


class Subagents(Plugin):
    """The ``task`` tool: children that work on a delegated piece of the job in their own sessions."""

    name = "subagents"
    description = "The task tool and its profiles"

    def activate(self, container: PluginContainer) -> None:
        """Register the tool when ``[harness] subagent`` is on, built once the provider exists."""
        config = container.config
        if not config.subagent_enabled:
            return
        persistence = container.service(PERSISTENCE, SessionStore)
        capabilities = container.service(CAPABILITIES, ModelCapabilities)

        def build(agent: AgentBuild) -> AgentExtension:
            # Imported here: the module pulls in the SQLite store and SQLAlchemy, which a launch that
            # never runs a child should not pay for on the way to the first frame.
            from ..app.agent.extensions.subagents import subagent_extension

            return subagent_extension(
                model=agent.model,
                persistence=persistence,
                capabilities=capabilities,
                # The parent's project instructions go to its children too.
                workspace=config.workspace if config.agents_md_enabled else None,
                max_iterations=config.subagent_max_iterations,
            )

        container.register_extension_factory("ParentModelSubAgents", build)


class Messaging(Plugin):
    """The tools that talk to the other sessions open on this machine."""

    name = "messaging"
    description = "The session messaging tools"

    def activate(self, container: PluginContainer) -> None:
        """Register the tools when the configuration gave the runtime a line to the other sessions."""
        messenger = container.find(MESSENGER, Messenger)
        if messenger is None:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from ..app.agent.extensions.messaging import SessionMessagingExtension

            return SessionMessagingExtension(messenger)

        container.register_extension_factory("SessionMessagingExtension", build)


class ShellPermission(Plugin):
    """Decides which shell commands run: ``deny`` refuses them, anything else is asked about or let through.

    The deny extension runs before the approval one (its priority is lower), because the approval can ask
    but cannot refuse on the reader's behalf. Both read the one policy the runtime owns, so changing the
    level in ``/permission`` applies to the next command.
    """

    name = "shell-permission"
    description = "Approval and refusal of shell commands"

    def activate(self, container: PluginContainer) -> None:
        """Register the deny and approval extensions and provide the approval, whose memory the shell reads."""
        from zett_agent.extensions.shell_approval import ShellApprovalExtension

        policy = container.service(POLICY, ShellPolicy)
        approval = ShellApprovalExtension(ShellApprovalMemory(policy))
        container.provide(APPROVAL, approval)
        container.register_extension(ShellDenyExtension(policy))
        container.register_extension(approval)


class SessionLog(Plugin):
    """Writes the conversation to the session's log as it happens, and restores it on resume."""

    name = "session-log"
    description = "Session persistence"

    def activate(self, container: PluginContainer) -> None:
        """Register the store, which is both what the shell reads sessions from and an extension."""
        container.register_extension(container.service(PERSISTENCE, SessionStore))


class UsageTracking(Plugin):
    """Counts the tokens each session has spent, for the status line and ``/usage``."""

    name = "usage-tracking"
    description = "Token accounting"

    def activate(self, container: PluginContainer) -> None:
        """Provide the counters and register the extension that fills them."""
        usage = UsageExtension()
        container.provide(USAGE, usage)
        container.register_extension(usage)


class ContextTracking(Plugin):
    """Remembers the last assembled request of each session, for ``/context``."""

    name = "context-tracking"
    description = "What the last request was made of"

    def activate(self, container: PluginContainer) -> None:
        """Provide the recorder and register the extension that fills it."""
        context = ContextExtension()
        container.provide(CONTEXT, context)
        container.register_extension(context)


class SideQuestionBoundary(Plugin):
    """``/btw``: questions answered on a read-only run beside the conversation."""

    name = "side-questions"
    description = "The read-only boundary side questions run behind"

    def activate(self, container: PluginContainer) -> None:
        """Provide the boundary, which the shell marks before it starts a side run, and register it."""
        sides = SideQuestions()
        container.provide(SIDES, sides)
        container.register_extension(sides)


class ToolGuidance(Plugin):
    """The guidance each tool carries into the system prompt."""

    name = "tool-guidelines"
    description = "Per-tool guidance in the prompt"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension; it is small, but it belongs with the others that wait for the build."""

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension

            return ToolGuidelinesExtension()

        container.register_extension_factory("ToolGuidelinesExtension", build)


class AskUser(Plugin):
    """The ``ask_user`` tool: how the model puts a question to the reader instead of guessing."""

    name = "ask-user"
    description = "The ask_user tool"

    def activate(self, container: PluginContainer) -> None:
        """Hand the agent the tool, unless the configuration turned it off."""
        if not container.config.ask_user_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.ask_user import AskUserExtension

            return AskUserExtension()

        container.register_extension_factory("AskUserExtension", build)


class ProjectInstructions(Plugin):
    """The workspace's ``AGENTS.md`` files, read again for every request so an edit applies at once."""

    name = "project-instructions"
    description = "The workspace's AGENTS.md instructions"

    def activate(self, container: PluginContainer) -> None:
        """Hand the agent the instructions, unless the configuration turned them off."""
        config = container.config
        if not config.agents_md_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.agents_md import AgentsMdExtension

            return AgentsMdExtension(config.workspace)

        container.register_extension_factory("AgentsMdExtension", build)


class SkillTool(Plugin):
    """The skills the model can load: their list in the prompt and the tool that reads one."""

    name = "skill-tool"
    description = "Skills the model can load"

    def activate(self, container: PluginContainer) -> None:
        """Hand the agent the skills found under the configured roots, when skills are on."""
        config = container.config
        if not config.skills_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.skill import SkillExtension

            return SkillExtension(config.skill_search_roots())

        container.register_extension_factory("SkillExtension", build)


class McpTools(Plugin):
    """The tools MCP servers offer. A server that is down is skipped, never fatal."""

    name = "mcp"
    description = "MCP servers"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension when MCP is on; a run with no server file gets none at all."""
        config = container.config
        if not config.mcp_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension | None:
            from ..app.agent.extensions.mcp import build_scoped_mcp_extension

            return build_scoped_mcp_extension(config.mcp_files())

        container.register_extension_factory("ReportingMcpExtension", build)


class TodoPlan(Plugin):
    """The ``todo_write`` tool, and the plan it keeps, shown in the shell's panel.

    The extension is provided as a service whether or not the tool is on, because the shell asks it for the
    plan on every turn and an extension nobody registered simply has none to show. Only
    ``[harness] todowrite`` decides whether the model is given the tool.
    """

    name = "todos"
    description = "The todo_write tool and the plan it keeps"

    def activate(self, container: PluginContainer) -> None:
        """Provide the extension, and hand it to the agent when the tool is on."""
        from zett_agent.extensions.todo import TodoWriteExtension

        extension = TodoWriteExtension()
        container.provide(TODOS, extension)
        if container.config.todowrite_enabled:
            container.register_extension(extension)


class Compaction(Plugin):
    """Shortens the conversation when it nears the model's window, or when the reader asks."""

    name = "compaction"
    description = "Context compaction"

    def activate(self, container: PluginContainer) -> None:
        """Provide the policy, sized for the model the run starts on; the runtime resizes it on a switch."""
        selected = container.service(SELECTED_MODEL, ModelConfig)
        counter = container.service(COMPACTION_COUNTER, CompactionCounter)
        compaction = OnDemandCompaction(
            None,
            max_tokens=selected.compaction_max_tokens,
            keep_recent_tokens=selected.compaction_keep_tokens,
            count_tokens=counter.count,
        )
        container.provide(COMPACTION, compaction)
        container.register_extension(compaction)


#: The agent-side plugins in the order the agent receives their extensions.
AGENT_PLUGINS: tuple[Plugin, ...] = (
    CodingTools(),
    ToolOutput(),
    Capabilities(),
    Subagents(),
    Messaging(),
    ShellPermission(),
    SessionLog(),
    TodoPlan(),
    UsageTracking(),
    ContextTracking(),
    SideQuestionBoundary(),
    ToolGuidance(),
    AskUser(),
    ProjectInstructions(),
    SkillTool(),
    McpTools(),
    Compaction(),
)
