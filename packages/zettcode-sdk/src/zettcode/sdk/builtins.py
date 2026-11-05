"""The agent-side extensions ZettCode ships with, offered the way any plugin offers one.

Each class here owns one ``zett-agent`` extension and the switch in the configuration that turns it on, so
the runtime lists none of them by hand: it asks the loaded plugins for what they contributed. They register
through :meth:`~zettcode.engine.plugins.context.PluginContext` and
:meth:`~zettcode.engine.plugins.context.PluginContext`, which are also what a third-party
plugin uses, so a plugin that wraps a whole extension is not a second-class citizen.

Two rules decide how one registers:

* An extension that costs something to import, or needs the provider the agent starts on, is registered as
  a **factory**: a plugin activates while the first frame is still being drawn, and the factory is called
  only when the agent is built, after the imports the runtime warms up. The ``zett_agent`` imports are inside
  the factories for that reason.
* An object the application also has to reach (the plan, the usage counters, the compaction) is **provided**
  as a service by name, and the runtime reads it from there instead of keeping a field for it.

The order of :data:`AGENT_PLUGINS` is the order the agent receives the extensions in; extensions that share a
priority keep it. The loader finds the plugins through the ``zettcode.agent`` entry-point group this package
publishes and activates them by the rank that list gives them (``Plugin.rank``), then by their ``deps``: what one
reads from another, such as the capabilities the subagents are sized by, is a ``deps`` entry and not a position. What
a plugin builds on (the session store, the permission policy) is handed over by the runtime by name, see
:mod:`zettcode.engine.plugins.services`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from zettcode.config import ModelConfig
from zettcode.engine.dialogue.side import SideQuestions
from zettcode.engine.extensions.capabilities import ModelCapabilities
from zettcode.engine.extensions.compaction import CompactionCounter, OnDemandCompaction
from zettcode.engine.extensions.context import ContextExtension
from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.extensions.tool_output import ToolOutputExtension
from zettcode.engine.extensions.truncation import LongOutputExtension
from zettcode.engine.extensions.usage import UsageExtension
from zettcode.engine.permission import ShellDenyExtension, ShellPolicy
from zettcode.engine.permission.approval import ShellApprovalMemory
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting
from zettcode.engine.plugins.services import (
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
from zettcode.engine.storage import SessionStore
from zettcode.mentions import FileMentions

from .messenger import Messenger

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

    from zett_agent.extensions.base import AgentExtension
    from zett_agent.jit_harness import JITToolHost

    from zettcode.config import ZettCodeConfig
    from zettcode.engine.plugins import Plugins
    from zettcode.engine.plugins.state import AgentBuild

_P = TypeVar("_P", bound="Plugins")


class FileResources(Plugin):
    """The ``@`` resource provider for the workspace's own files.

    A name a skill (``zettcode-skills``) also offers is the skill: a repository holds a file called ``test`` and a
    skill is the more specific thing to mean, which the skills provider says with its ``precedence``. Nothing turns
    this off, because a workspace always has files.
    """

    name = "files"

    def activate(self, ctx: PluginContext) -> None:
        """Offer the workspace's files as ``@`` resources."""
        ctx.agent.register_mention(FileMentions(ctx.config.workspace))


class CodingTools(Plugin):
    """The coding bundle: the file tools, search and the shell tool."""

    name = "coding"
    description = "The file, search and shell tools"

    def activate(self, ctx: PluginContext) -> None:
        """Register the bundle; it is the largest import the agent needs, so it waits for the build."""

        policy = ctx.service(POLICY, ShellPolicy)

        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.files import CodingBundle

            return CodingBundle(policy)

        ctx.agent.register_extension_factory("CodingBundle", build)


class ToolOutput(Plugin):
    """Moves a long tool result into the session's folder before it is stored or sent anywhere."""

    name = "tool-output"
    description = "Keeps long tool output in the session folder"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension over the session store."""
        ctx.agent.register_extension(ToolOutputExtension(ctx.service(PERSISTENCE, SessionStore)))


class LongOutput(Plugin):
    """Keeps a result over a tool's budget in a file, and sends its start and its end instead.

    The tools in this repository bound what they return themselves; this is the backstop for the ones that come
    from elsewhere — an MCP server, a subagent, a plugin — so one long answer cannot fill the context of every
    later request in the session.
    """

    name = "long-output"
    description = "Keeps over-long tool results in the session folder"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension over the session store."""
        ctx.agent.register_extension(LongOutputExtension(ctx.service(PERSISTENCE, SessionStore)))


class Capabilities(Plugin):
    """What the configured models can do, so a tool is not offered to one that cannot use it."""

    name = "capabilities"
    description = "Filters tools by what the model takes"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the filter, over the runtime's own table of the models it has built."""
        capabilities = ModelCapabilities(ctx.service(MODELS, dict))
        ctx.agent.provide(CAPABILITIES, capabilities)
        ctx.agent.register_extension(capabilities)


class Subagents(Plugin):
    """The ``task`` tool: children that work on a delegated piece of the job in their own sessions."""

    name = "subagents"
    description = "The task tool and its profiles"
    # Reads the capabilities the plugin below provides, so it is activated after it whatever their ranks say.
    deps = ("capabilities",)
    setting = PluginSetting("subagent_enabled", "harness", "subagent")

    def activate(self, ctx: PluginContext) -> None:
        """Register the tool when ``[harness] subagent`` is on, built once the provider exists."""
        config = ctx.config
        if not config.subagent_enabled:
            return
        persistence = ctx.service(PERSISTENCE, SessionStore)
        capabilities = ctx.service(CAPABILITIES, ModelCapabilities)
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

        ctx.agent.register_extension_factory("ParentModelSubAgents", build)


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
    from zettcode.engine.plugins.extension import PluginExtension

    from .extensions.messaging import SessionMessagingExtension

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


class Messaging(Plugin):
    """The tools that talk to the other sessions open on this machine."""

    name = "messaging"
    description = "The session messaging tools"

    def activate(self, ctx: PluginContext) -> None:
        """Register the tools when the configuration gave the runtime a line to the other sessions."""
        messenger = ctx.find(MESSENGER, Messenger)
        if messenger is None:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from .extensions.messaging import SessionMessagingExtension

            return SessionMessagingExtension(messenger)

        ctx.agent.register_extension_factory("SessionMessagingExtension", build)


class ShellPermission(Plugin):
    """Decides which shell commands run: ``deny`` refuses them, anything else is asked about or let through.

    The deny extension runs before the approval one (its priority is lower), because the approval can ask
    but cannot refuse on the reader's behalf. Both read the one policy the runtime owns, so changing the
    level in ``/permission`` applies to the next command.
    """

    name = "shell-permission"
    description = "Approval and refusal of shell commands"

    def activate(self, ctx: PluginContext) -> None:
        """Register the deny and approval extensions and provide the approval, whose memory the shell reads."""
        from zett_agent.extensions.shell_approval import ShellApprovalExtension

        policy = ctx.service(POLICY, ShellPolicy)
        approval = ShellApprovalExtension(ShellApprovalMemory(policy))
        ctx.agent.provide(APPROVAL, approval)
        ctx.agent.register_extension(ShellDenyExtension(policy))
        ctx.agent.register_extension(approval)


class Harness(Plugin):
    """The just-in-time harness: the model keeps small Python tools of its own, when the reader has it on.

    The extension is always registered and inert until the switch is on, so ``/harness on`` reaches the next
    request of a client that was already built. Each session keeps its tools in its own folder under
    ``config.harness_dir``, which is ``~/.zettcode/harness`` unless the configuration object says otherwise.
    """

    name = "harness"
    description = "The just-in-time tool harness, off by default"
    setting = PluginSetting("jit_harness", "harness", "jit")

    def activate(self, ctx: PluginContext) -> None:
        """Register the switchable extension; the framework's harness is imported when the agent is built."""
        from zettcode.engine.harness_paths import harness_root

        switch = ctx.service(HARNESS, HarnessSwitch)
        root = harness_root(ctx.config)
        policy = ctx.service(POLICY, ShellPolicy)

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
                legacy_root=ctx.config.harness_dir,
            )

        ctx.agent.register_extension_factory("SwitchedHarness", build)


class SessionLog(Plugin):
    """Writes the conversation to the session's log as it happens, and restores it on resume."""

    name = "session-log"
    description = "Session persistence"

    def activate(self, ctx: PluginContext) -> None:
        """Register the store, which is both what the shell reads sessions from and an extension."""
        ctx.agent.register_extension(ctx.service(PERSISTENCE, SessionStore))


class UsageTracking(Plugin):
    """Counts the tokens each session has spent, for the status line and ``/usage``."""

    name = "usage-tracking"
    description = "Token accounting"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the counters and register the extension that fills them."""
        # The count comes from the encoding compaction has already warmed, and answers for a provider that reports no
        # usage of its own; the rate's numerator is the provider's count.
        counter = ctx.service(COMPACTION_COUNTER, CompactionCounter)
        usage = UsageExtension(count_context=counter.count)
        ctx.agent.provide(USAGE, usage)
        ctx.agent.register_extension(usage)


class ContextTracking(Plugin):
    """Remembers the last assembled request of each session, for ``/context``."""

    name = "context-tracking"
    description = "What the last request was made of"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the recorder and register the extension that fills it."""
        context = ContextExtension()
        ctx.agent.provide(CONTEXT, context)
        ctx.agent.register_extension(context)


class SideQuestionBoundary(Plugin):
    """``/btw``: questions answered on a read-only run beside the conversation."""

    name = "side-questions"
    description = "The read-only boundary side questions run behind"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the boundary, which the shell marks before it starts a side run, and register it."""
        sides = SideQuestions()
        ctx.agent.provide(SIDES, sides)
        ctx.agent.register_extension(sides)


class ToolGuidance(Plugin):
    """The guidance each tool carries: its call shapes, guidelines and return type, in the tool's own description."""

    name = "tool-guidelines"
    description = "Per-tool guidance in each tool's description"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension; it is small, but it belongs with the others that wait for the build."""

        def build(_: AgentBuild) -> AgentExtension:
            from zettcode.engine.extensions.guidance import tool_guidance

            return tool_guidance()

        ctx.agent.register_extension_factory("ToolGuidelinesExtension", build)


class AskUser(Plugin):
    """The ``ask_user`` tool: how the model puts a question to the reader instead of guessing."""

    name = "ask-user"
    description = "The ask_user tool"
    setting = PluginSetting("ask_user_enabled", "ask_user")

    def activate(self, ctx: PluginContext) -> None:
        """Hand the agent the tool, unless the configuration turned it off."""
        if not ctx.config.ask_user_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.ask_user import AskUserExtension

            return AskUserExtension()

        ctx.agent.register_extension_factory("AskUserExtension", build)


class ProjectInstructions(Plugin):
    """The workspace's ``AGENTS.md`` files, read again for every request so an edit applies at once."""

    name = "project-instructions"
    description = "The workspace's AGENTS.md instructions"
    setting = PluginSetting("agents_md_enabled", "agents_md")

    def activate(self, ctx: PluginContext) -> None:
        """Hand the agent the instructions, unless the configuration turned them off."""
        config = ctx.config
        if not config.agents_md_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.agents_md import AgentsMdExtension

            return AgentsMdExtension(config.workspace)

        ctx.agent.register_extension_factory("AgentsMdExtension", build)


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


class SelfCompaction(Plugin):
    """The switch for letting the model compact its own context.

    The work is the runtime's: ``[compaction] self`` is the default, and a session that chose otherwise keeps its
    choice. This plugin exists so `/plugins` can show and write that default like any other plugin setting.
    """

    name = "self-compaction"
    description = "Let the model compact its own context"
    setting = PluginSetting("self_compaction", "compaction", "self")

    def activate(self, ctx: PluginContext) -> None:
        """Nothing to register: the setting decides the runtime's policy, not an object here."""


class Compaction(Plugin):
    """Shortens the conversation when it nears the model's window, or when the reader asks."""

    name = "compaction"
    description = "Context compaction"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the policy, sized for the model the run starts on; the runtime resizes it on a switch.

        A machine with no model configured has nothing to size it from: the policy is provided with the
        extension's own defaults — nothing runs to compact before there is a model — and ``use_model`` sizes it
        the moment the first entry is written.
        """
        selected = ctx.find(SELECTED_MODEL, ModelConfig)
        counter = ctx.service(COMPACTION_COUNTER, CompactionCounter)
        if selected is None:
            compaction = OnDemandCompaction(None, count_tokens=counter.count)
        else:
            compaction = OnDemandCompaction(
                None,
                max_tokens=selected.compaction_max_tokens,
                keep_recent_tokens=selected.compaction_keep_tokens,
                count_tokens=counter.count,
            )
        ctx.agent.provide(COMPACTION, compaction)
        ctx.agent.register_extension(compaction)


#: The agent-side plugins in the order the agent receives their extensions. The distribution publishes the same list as
#: entry points (``zettcode.agent`` in this package's ``pyproject.toml``) and the loader reads it from there; this tuple
#: is what gives each its rank, and what a caller that loads without discovering (a test, a checkout with no installed
#: distribution) passes as ``builtins=``. ``test_agent_parts.py`` holds the two lists together.
AGENT_PLUGINS: tuple[Plugin[PluginContext], ...] = (
    FileResources(),
    CodingTools(),
    ToolOutput(),
    LongOutput(),
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
    SelfCompaction(),
    Compaction(),
)

for _rank, _plugin in enumerate(AGENT_PLUGINS):
    # One list is the order; the rank is read from it, so there is no second number to keep in step by hand.
    type(_plugin).rank = _rank
# The rank lives on the class, so a class listed twice would take the last index for both.
assert len({type(plugin) for plugin in AGENT_PLUGINS}) == len(AGENT_PLUGINS), "AGENT_PLUGINS lists a class twice"

#: The names of those plugins, which the program cannot run without.
AGENT_PLUGIN_NAMES: tuple[str, ...] = tuple(plugin.name for plugin in AGENT_PLUGINS)

#: Those and the parts that live in distributions of their own (skills, MCP): what an installation must hold.
REQUIRED_AGENT_NAMES: tuple[str, ...] = (*AGENT_PLUGIN_NAMES, "skills", "skill-tool", "mcp")


def require_agent_parts(plugins: _P) -> _P:
    """Return ``plugins``, or raise when the plugins that compose the agent were not found at all.

    A failure to activate one is recorded in ``failed`` as it always was; what is refused here is an installation that
    has none of them to activate, which would start an agent with no tools, no session log and no compaction.

    Raises:
        RequiredPluginError: One of :data:`AGENT_PLUGIN_NAMES` neither loaded nor failed.
    """
    from zettcode.engine.plugins.loader import RequiredPluginError

    # Keyed on where a plugin came from and not on what it calls itself: ``builtins`` holds the origin of every plugin
    # the program published, loaded or not, and a stranger that names itself ``mcp`` is not among them.
    seen = set(plugins.builtins)
    missing = {name: "not installed" for name in REQUIRED_AGENT_NAMES if name not in seen}
    if missing:
        raise RequiredPluginError(missing)
    return plugins


def load_agent_plugins(config: ZettCodeConfig, shared: Mapping[str, object]) -> Plugins:
    """Load the agent's plugins and the distributions a reader enabled: the loader a runtime is built with.

    The engine's own default loads the installed plugins and none of the agent's, because the engine does not ship
    them. Whoever builds the runtime says which agent it wants: the SDK passes this, and the terminal passes
    :func:`zettcode.app.plugins.loader.terminal_plugins`, which adds the plugins only a screen can hold.
    """
    from zettcode.engine.plugins import load_plugins

    return require_agent_parts(load_plugins(config, builtins=(), shared=shared))
