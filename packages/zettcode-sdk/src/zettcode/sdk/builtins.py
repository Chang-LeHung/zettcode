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

A part that lives in a distribution of its own (the skills, the MCP client, the files, the harness, the ``ask_user``
tool, the project instructions, the plan, the shell's kept output, an over-long result and the per-tool guidance)
states no rank, so it is activated ahead of this list and registers its extension first; each of those still runs where
its own priority puts it. ``ask-user``, ``todos``, ``tool-output``, ``long-output`` and ``tool-guidelines`` share the
100 nearly everything else here has, so they run before what this module contributes in that band.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from zettcode.config import ModelConfig
from zettcode.engine.dialogue.side import SideQuestions
from zettcode.engine.extensions.capabilities import ModelCapabilities
from zettcode.engine.extensions.compaction import CompactionCounter, OnDemandCompaction
from zettcode.engine.extensions.context import ContextExtension
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
    MESSENGER,
    MODELS,
    PERSISTENCE,
    POLICY,
    SELECTED_MODEL,
    SIDES,
    USAGE,
)
from zettcode.engine.storage import SessionStore

from .messenger import Messenger

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

    from zett_agent.extensions.base import AgentExtension

    from zettcode.config import ZettCodeConfig
    from zettcode.engine.plugins import Plugins
    from zettcode.engine.plugins.state import AgentBuild

_P = TypeVar("_P", bound="Plugins")


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
    from zett_agent.jit_harness import JITHarnessExtension

    from zettcode.engine.plugins.extension import PluginExtension

    from .extensions.messaging import SessionMessagingExtension

    private: tuple[type, ...] = (
        InternalMessageExtension,
        SteeringExtension,
        SubAgentExtension,
        JITHarnessExtension,  # the switchable one of ``zettcode-jit-harness`` is a subclass
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
    CodingTools(),
    Capabilities(),
    Subagents(),
    Messaging(),
    ShellPermission(),
    SessionLog(),
    UsageTracking(),
    ContextTracking(),
    SideQuestionBoundary(),
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

#: Those and the parts that live in distributions of their own (skills, MCP, files, harness, ask-user, the project
#: instructions, the plan, the shell's kept output, an over-long result and the per-tool guidance): what an
#: installation must hold.
REQUIRED_AGENT_NAMES: tuple[str, ...] = (
    *AGENT_PLUGIN_NAMES,
    "files",
    "harness",
    "skills",
    "skill-tool",
    "mcp",
    "ask-user",
    "project-instructions",
    "todos",
    "tool-output",
    "long-output",
    "tool-guidelines",
)


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
