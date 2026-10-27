"""The agent-side extensions ZettCode ships with, offered the way any plugin offers one.

Each class here owns one ``zett-agent`` extension and the switch in the configuration that turns it on, so
the runtime lists none of them by hand: it asks the loaded plugins for what they contributed. They register
through :meth:`~zettcode.engine.plugins.PluginContainer.register_extension` and
:meth:`~zettcode.engine.plugins.PluginContainer.register_extension_factory`, which are also what a third-party
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
:mod:`zettcode.engine.plugins.services`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from zettcode.config import ModelConfig
from zettcode.engine.dialogue.side import SideQuestions
from zettcode.engine.extensions.capabilities import ModelCapabilities
from zettcode.engine.extensions.compaction import CompactionCounter, OnDemandCompaction
from zettcode.engine.extensions.context import ContextExtension
from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.extensions.tool_output import ToolOutputExtension
from zettcode.engine.extensions.usage import UsageExtension
from zettcode.engine.messenger import Messenger
from zettcode.engine.permission import ShellDenyExtension, ShellPolicy
from zettcode.engine.permission.approval import ShellApprovalMemory
from zettcode.engine.storage import SessionStore
from zettcode.mentions import FileMentions, SkillMentions

from .container import PluginContainer
from .plugin import AgentPlugin
from .services import (
    APPROVAL,
    CAPABILITIES,
    COMPACTION,
    COMPACTION_COUNTER,
    CONTEXT,
    HARNESS,
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
    from zett_agent.jit_harness import JITToolHost

    from .state import AgentBuild


class SkillResources(AgentPlugin):
    """The builtin ``@`` resource provider: the skills on this machine.

    Registering it here rather than inside the shell keeps the shell generic: it
    merges whatever providers the bundle holds, and the skills are simply the
    one the repository ships.
    """

    name = "skills"

    def activate(self, container: PluginContainer) -> None:
        """Offer the discovered skills as ``@`` resources, when skills are on."""
        if container.config.skills_enabled:
            container.register_mention(SkillMentions(container.config))


class FileResources(AgentPlugin):
    """The ``@`` resource provider for the workspace's own files.

    Registered after the skills, so a name both could offer is the skill: a
    repository holds a file called ``test`` and a skill is the more specific
    thing to mean. Nothing turns this off, because a workspace always has files.
    """

    name = "files"

    def activate(self, container: PluginContainer) -> None:
        """Offer the workspace's files as ``@`` resources."""
        container.register_mention(FileMentions(container.config.workspace))


class CodingTools(AgentPlugin):
    """The coding bundle: the file tools, search and the shell tool."""

    name = "coding"
    description = "The file, search and shell tools"

    def activate(self, container: PluginContainer) -> None:
        """Register the bundle; it is the largest import the agent needs, so it waits for the build."""

        policy = container.service(POLICY, ShellPolicy)

        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.files import CodingBundle

            return CodingBundle(policy)

        container.register_extension_factory("CodingBundle", build)


class ToolOutput(AgentPlugin):
    """Moves a long tool result into the session's folder before it is stored or sent anywhere."""

    name = "tool-output"
    description = "Keeps long tool output in the session folder"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension over the session store."""
        container.register_extension(ToolOutputExtension(container.service(PERSISTENCE, SessionStore)))


class Capabilities(AgentPlugin):
    """What the configured models can do, so a tool is not offered to one that cannot use it."""

    name = "capabilities"
    description = "Filters tools by what the model takes"

    def activate(self, container: PluginContainer) -> None:
        """Provide the filter, over the runtime's own table of the models it has built."""
        capabilities = ModelCapabilities(container.service(MODELS, dict))
        container.provide(CAPABILITIES, capabilities)
        container.register_extension(capabilities)


class Subagents(AgentPlugin):
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
        messaging = config.subagent_messaging

        def build(agent: AgentBuild) -> AgentExtension:
            # Imported here: the module pulls in the SQLite store and SQLAlchemy, which a launch that
            # never runs a child should not pay for on the way to the first frame.
            from zettcode.engine.extensions.subagents import subagent_extension

            return subagent_extension(
                model=agent.model,
                persistence=persistence,
                capabilities=capabilities,
                # The parent's project instructions go to its children too.
                workspace=config.workspace if config.agents_md_enabled else None,
                max_iterations=config.subagent_max_iterations,
                shares=_shared_with_children(messaging=messaging),
            )

        container.register_extension_factory("ParentModelSubAgents", build)


def _shared_with_children(*, messaging: bool) -> Callable[[AgentExtension], bool]:
    """Return what decides, for each extension the parent runs, whether a ``coding`` child gets it too.

    A child is the parent without the complicated parts, so this lists what is *not* shared:

    * what is part of every agent and is not its to share: the framework's own internal-message and steering
      extensions, which an agent adds for itself and refuses to be given;
    * ``task``, so a child cannot start another child;
    * the just-in-time harness, whose tools are code the model writes and runs in this process;
    * ``list_sessions`` and ``send_message``, unless ``[harness] subagent_messaging`` asks for them;
    * ``ask_user``: a child works until it has finished and answers the parent, so a question put to the person
      in the middle of it would be a conversation the person never started. What it needs to know has to be in
      the task;
    * what belongs to the conversation the person is having: the plan panel (``todo_write``, whose list the shell
      draws for the parent's session and would never show for a child's), the ``/btw`` boundary, the token and
      context counters of the session, the plugin host that drives third-party hooks;
    * what a child is given of its own in another form: its session store, the capability filter, and the
      project instructions and tool guidance (each child reads and renders its own).

    Everything else is shared as it is, which is what puts the child's shell under the parent's permission
    level and approval memory, and gives it the parent's skills, questions and MCP servers.
    """
    # Imported here: the framework's subagent and harness modules are what a launch that never delegates
    # should not load.
    from zett_agent.extensions.agents_md import AgentsMdExtension
    from zett_agent.extensions.ask_user import AskUserExtension
    from zett_agent.extensions.internal_message import InternalMessageExtension
    from zett_agent.extensions.steering import SteeringExtension
    from zett_agent.extensions.subagent import SubAgentExtension
    from zett_agent.extensions.todo import TodoWriteExtension
    from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension

    from zettcode.engine.extensions.harness import SwitchedHarness
    from zettcode.engine.extensions.messaging import SessionMessagingExtension

    from .extension import PluginExtension

    private: tuple[type, ...] = (
        InternalMessageExtension,
        SteeringExtension,
        SubAgentExtension,
        SwitchedHarness,
        AskUserExtension,
        TodoWriteExtension,
        SideQuestions,
        UsageExtension,
        ContextExtension,
        PluginExtension,
        SessionStore,
        ModelCapabilities,
        AgentsMdExtension,
        ToolGuidelinesExtension,
    )
    if not messaging:
        private = (*private, SessionMessagingExtension)
    return lambda extension: not isinstance(extension, private)


class Messaging(AgentPlugin):
    """The tools that talk to the other sessions open on this machine."""

    name = "messaging"
    description = "The session messaging tools"

    def activate(self, container: PluginContainer) -> None:
        """Register the tools when the configuration gave the runtime a line to the other sessions."""
        messenger = container.find(MESSENGER, Messenger)
        if messenger is None:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.messaging import SessionMessagingExtension

            return SessionMessagingExtension(messenger)

        container.register_extension_factory("SessionMessagingExtension", build)


class ShellPermission(AgentPlugin):
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


class Harness(AgentPlugin):
    """The just-in-time harness: the model keeps small Python tools of its own, when the reader has it on.

    The extension is always registered and inert until the switch is on, so ``/harness on`` reaches the next
    request of a client that was already built. Each session keeps its tools in its own folder under
    ``config.harness_dir``, which is ``~/.zettcode/harness`` unless the configuration object says otherwise.
    """

    name = "harness"
    description = "The just-in-time tool harness, off by default"

    def activate(self, container: PluginContainer) -> None:
        """Register the switchable extension; the framework's harness is imported when the agent is built."""
        switch = container.service(HARNESS, HarnessSwitch)
        root = container.config.harness_dir
        policy = container.service(POLICY, ShellPolicy)

        def host() -> JITToolHost:
            """Where one session's repository code runs.

            A child process either way, so a crash, a hang or a runaway allocation in code the model wrote stays
            out of this window. The boundary comes from the policy — none at `full`, the boundary `safe` uses below it — and `None` on a machine
            that has no sandbox.
            """
            from zett_agent.jit_harness import SubprocessToolHost

            return SubprocessToolHost(sandbox=policy.jit_sandbox())

        def boundary() -> str:
            """What a session's child was built around: the sandbox itself, or none.

            The *level* is not the key. `ask` and `safe` hand the harness the same sandbox, and restarting a child for
            nothing costs the model its loaded repository — the next tool call fails until it is loaded again — so this
            changes only when the boundary does.
            """
            sandbox = policy.jit_sandbox()
            return "none" if sandbox is None else type(sandbox).__name__ + str(id(sandbox))

        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.harness import SwitchedHarness

            return SwitchedHarness(
                root,
                switch,
                host_factory=host,
                boundary=boundary,
                unbounded=policy.sandbox_missing,
            )

        container.register_extension_factory("SwitchedHarness", build)


class SessionLog(AgentPlugin):
    """Writes the conversation to the session's log as it happens, and restores it on resume."""

    name = "session-log"
    description = "Session persistence"

    def activate(self, container: PluginContainer) -> None:
        """Register the store, which is both what the shell reads sessions from and an extension."""
        container.register_extension(container.service(PERSISTENCE, SessionStore))


class UsageTracking(AgentPlugin):
    """Counts the tokens each session has spent, for the status line and ``/usage``."""

    name = "usage-tracking"
    description = "Token accounting"

    def activate(self, container: PluginContainer) -> None:
        """Provide the counters and register the extension that fills them."""
        usage = UsageExtension()
        container.provide(USAGE, usage)
        container.register_extension(usage)


class ContextTracking(AgentPlugin):
    """Remembers the last assembled request of each session, for ``/context``."""

    name = "context-tracking"
    description = "What the last request was made of"

    def activate(self, container: PluginContainer) -> None:
        """Provide the recorder and register the extension that fills it."""
        context = ContextExtension()
        container.provide(CONTEXT, context)
        container.register_extension(context)


class SideQuestionBoundary(AgentPlugin):
    """``/btw``: questions answered on a read-only run beside the conversation."""

    name = "side-questions"
    description = "The read-only boundary side questions run behind"

    def activate(self, container: PluginContainer) -> None:
        """Provide the boundary, which the shell marks before it starts a side run, and register it."""
        sides = SideQuestions()
        container.provide(SIDES, sides)
        container.register_extension(sides)


class ToolGuidance(AgentPlugin):
    """The guidance each tool carries into the system prompt."""

    name = "tool-guidelines"
    description = "Per-tool guidance in the prompt"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension; it is small, but it belongs with the others that wait for the build."""

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension

            return ToolGuidelinesExtension()

        container.register_extension_factory("ToolGuidelinesExtension", build)


class AskUser(AgentPlugin):
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


class ProjectInstructions(AgentPlugin):
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


class SkillTool(AgentPlugin):
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


class McpTools(AgentPlugin):
    """The tools MCP servers offer. A server that is down is skipped, never fatal."""

    name = "mcp"
    description = "MCP servers"

    def activate(self, container: PluginContainer) -> None:
        """Register the extension when MCP is on; a run with no server file gets none at all."""
        config = container.config
        if not config.mcp_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension | None:
            from zettcode.engine.extensions.mcp import build_scoped_mcp_extension

            return build_scoped_mcp_extension(config.mcp_files())

        container.register_extension_factory("ReportingMcpExtension", build)


class TodoPlan(AgentPlugin):
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


class Compaction(AgentPlugin):
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
AGENT_PLUGINS: tuple[AgentPlugin, ...] = (
    SkillResources(),
    FileResources(),
    CodingTools(),
    ToolOutput(),
    Capabilities(),
    Subagents(),
    Messaging(),
    ShellPermission(),
    Harness(),
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
