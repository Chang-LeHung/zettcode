"""Application runtime that composes AgentClient with coding extensions.

The runtime is built in two steps. :meth:`ZettCodeRuntime.preview` assembles
everything that needs no provider — settings, the session store, this
application's own extensions — so the shell can paint its first frame;
:meth:`ZettCodeRuntime.start` imports the provider SDK, builds the client, and
is what a turn or a command awaits before it reaches the model. That split is
worth a few hundred milliseconds of startup, and the modules that cost them
stay out of the import graph until they are needed.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from zett_agent.agent import AgentRunConfig
from zett_agent.client import AgentClient
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.extensions.ask_user import AskUserExtension
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.coding import CodingExtension
from zett_agent.extensions.shell_approval import ShellApprovalExtension
from zett_agent.extensions.todo import TodoWriteExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.ids import new_uuid7
from zett_agent.model import ReasoningEffort

from ...config import DEFAULT_ANTHROPIC_BASE_URL, ModelConfig, ZettCodeConfig
from ...paths import DEFAULT_MCP_CONFIG
from ...plugins import Plugins, load_plugins
from ..pipeline import ImportPipeline
from .dialogue.side import SideQuestions
from .extensions.capabilities import ModelCapabilities
from .extensions.compaction import OnDemandCompaction
from .extensions.context import ContextExtension, Tokenizer
from .extensions.usage import UsageExtension
from .permission import Permission, ShellDenyExtension, ShellPolicy, parse_permission
from .permission.approval import ShellApprovalMemory
from .storage import SessionStore

if TYPE_CHECKING:  # pragma: no cover - annotations only; the imports are the cost
    from zett_agent.providers.anthropic import AnthropicProvider
    from zett_agent.providers.openai import OpenAIProvider

    #: The adapters this runtime may own. Each is an ``AgentModel``; naming both
    #: is what also says they can be closed, which the runtime does at shutdown.
    Adapter: TypeAlias = OpenAIProvider | AnthropicProvider


#: Modules imported ahead of the code that needs them, in this order. The model
#: SDKs are the cost — hundreds of milliseconds each, even with their bytecode
#: cached — and the zett-agent module is what :meth:`ZettCodeRuntime._build`
#: would otherwise import on the event loop. A name added here moves its import
#: off the first turn and onto the pipeline's thread.
WARM_MODULES = ("openai", "anthropic", "zett_agent.client")


#: Modules a request needs only under the configuration that asks for them: each
#: of these pulls its own machinery, and a run that has no use for one should not
#: pay for it. The names are the ones :meth:`ZettCodeRuntime._build` imports.
WARM_MODULES_WHEN = (
    ("subagent_enabled", "zett_agent.extensions.subagent"),
    ("mcp_enabled", "zett_agent.extensions.mcp"),
)


def build_system_prompt(config: ZettCodeConfig, *, now: datetime | None = None) -> str:
    """Build request instructions with an explicit workspace boundary.

    The prompt is the head of every request, so whatever it contains is part of
    the provider's cache key: the date is deliberately the only time-derived
    value, and only the day of it. A clock reading with seconds would make the
    head unique to each launch and drop the cache for the whole conversation.

    Args:
        config: Settings the runtime was built from.
        now: Moment to describe, injectable for tests; defaults to the local
            current time.
    """
    moment = now or datetime.now().astimezone()
    return f"""You are ZettCode, a focused coding agent working with the user in one local workspace.

Inspect relevant files before editing. Make focused changes, preserve unrelated work,
and run checks proportional to risk. Explain blockers concretely. Do not perform
destructive actions unless the user explicitly requests them.

Runtime environment:
- Workspace: {config.workspace}
- Today: {moment.date().isoformat()}
- Operating system: {platform.platform()}
- Architecture: {platform.machine() or "unknown"}
- Python: {platform.python_implementation()} {platform.python_version()}
- Executable: {sys.executable}
- Shell: {os.getenv("SHELL", "unknown")}

Treat the workspace as the current working directory. Prefer relative paths in tool
calls. Verify mutable facts with tools instead of assuming this startup snapshot is current."""


def integration_extensions(config: ZettCodeConfig) -> tuple[AgentExtension, ...]:
    """Return the optional extensions this configuration asks for.

    They live outside the model loop, so they are built here and handed to
    :func:`create_agent` with the rest: the ``ask_user`` tool the model asks its
    questions through, the project instructions, the skills, and MCP. MCP is
    skipped when there is no server file to read, so an unconfigured run carries
    no MCP instructions at all rather than a system message saying there is
    nothing to load. The project instructions are the workspace's ``AGENTS.md``
    files: the extension reads them again on every request, so an edit applies to
    the next turn, and its priority keeps them ahead of the tool and skill
    guidance below.

    Args:
        config: Settings naming the workspace, what may ask questions, the skill
            roots, and the MCP server file.

    Returns:
        The extensions to add, in the order they lead the request.
    """
    from zett_agent.extensions.agents_md import AgentsMdExtension
    from zett_agent.extensions.skill import SkillExtension

    from .extensions.mcp import ReportingMcpExtension

    extensions: list[AgentExtension] = []
    if config.ask_user_enabled:
        extensions.append(AskUserExtension())
    if config.agents_md_enabled:
        extensions.append(AgentsMdExtension(config.workspace))
    if config.skills_enabled:
        extensions.append(SkillExtension(config.skill_search_roots()))
    if config.mcp_enabled:
        path = config.mcp_config or DEFAULT_MCP_CONFIG
        if Path(path).expanduser().is_file():
            extensions.append(ReportingMcpExtension(config_path=path))
    return tuple(extensions)


def _build_provider(selected: ModelConfig) -> Adapter:
    """Build the adapter one model entry asks for, importing only its SDK.

    The import lives in this function rather than at module level because it is
    the cost the first frame may not pay; the runtime's import pipeline warms the
    same module on its own thread before this runs.
    """
    if selected.anthropic:
        from zett_agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            selected.model,
            selected.token,
            base_url=selected.base_url or DEFAULT_ANTHROPIC_BASE_URL,
        )
    from zett_agent.providers.openai import OpenAIProvider

    return OpenAIProvider(
        selected.model,
        selected.token,
        base_url=selected.base_url,
        response=selected.responses_api,
    )


@dataclass(slots=True)
class ZettCodeRuntime:
    """Own the model, the persistence and approval extensions, the client, and the active session.

    Before :meth:`start` runs, ``client`` and ``model`` are ``None``: everything
    that does not need a provider is already here, which is what lets the shell
    paint. :attr:`started` and :attr:`provider` are the readers that insist the
    runtime is ready.
    """

    config: ZettCodeConfig
    persistence: SessionStore
    approval: ShellApprovalExtension
    #: The permission level, shared with the approval memory and the deny extension.
    policy: ShellPolicy
    todos: TodoWriteExtension
    usage: UsageExtension
    context: ContextExtension
    tokenizer: Tokenizer
    effort: ReasoningEffort
    session_id: str
    active_model: ModelConfig
    compaction: OnDemandCompaction
    #: The read-only boundary a side question runs behind; the shell keeps it to
    #: mark the run it is about to start.
    sides: SideQuestions = field(default_factory=SideQuestions)
    plugins: Plugins = field(default_factory=Plugins)
    event_dispatcher: AgentEventDispatcher | None = None
    client: AgentClient | None = None
    model: Adapter | None = None
    _starting: asyncio.Task[ZettCodeRuntime] | None = field(default=None, repr=False)
    _counter: asyncio.Task[None] | None = field(default=None, repr=False)
    _models: dict[ModelConfig, Adapter] = field(default_factory=dict)
    #: The warm-up imports, running on a daemon thread, and the loop-side event
    #: that releases whoever is waiting for them.
    _imports: ImportPipeline | None = field(default=None, repr=False)
    _ready: asyncio.Event | None = field(default=None, repr=False)

    @classmethod
    def preview(cls, config: ZettCodeConfig) -> ZettCodeRuntime:
        """Build the session side of the runtime, without a provider.

        Everything here is cheap: paths, a session identity, and the
        extensions this application owns. The provider SDK, the MCP client,
        and the tokenizer's vocabulary stay unimported until :meth:`start`.

        Args:
            config: Settings for the workspace and the session.
        """
        os.chdir(config.workspace)
        selected = config.models[0]
        # One policy, read by everything that decides whether a command is asked
        # about: the memory lets `safe` and `auto` through, the deny extension
        # refuses for `deny`, and the shell changes it from `/permission`.
        policy = ShellPolicy.from_mode(config.shell_approval, config.workspace)
        return cls(
            config=config,
            persistence=SessionStore(config.store, config.workspace),
            approval=ShellApprovalExtension(ShellApprovalMemory(policy)),
            policy=policy,
            todos=TodoWriteExtension(),
            usage=UsageExtension(),
            context=ContextExtension(),
            tokenizer=Tokenizer(),
            effort=config.reasoning_effort,
            session_id=new_uuid7(),
            active_model=selected,
            compaction=OnDemandCompaction(
                None,
                max_tokens=selected.compaction_max_tokens,
                keep_recent_tokens=selected.compaction_keep_tokens,
            ),
            plugins=load_plugins(config),
        )

    def start(self) -> asyncio.Task[ZettCodeRuntime]:
        """Build the provider and the client once, whoever asks first.

        The task is kept, so a background warm-up and the first turn cannot
        build two clients, and every later caller gets the same answer. What the
        build needs imported starts here as well, on a thread nobody waits for:
        a launch that ends before its first turn ends without paying for them.

        The token counter starts loading beside them, on the daemon thread its own
        deadline allows, so the vocabulary is there by the time a reader asks for
        `/context` instead of being fetched on that keystroke. Nothing waits for
        it here either: the load belongs to this runtime rather than to whoever
        needed it first, and :meth:`aclose` releases the wait.
        """
        if self._starting is None:
            self._begin_imports()
            self._starting = asyncio.ensure_future(self._build())
            self._counter = asyncio.ensure_future(self.tokenizer.prepare())
        return self._starting

    def warm_modules(self) -> tuple[str, ...]:
        """Return the modules to import ahead of the first turn, in order.

        The shell calls :meth:`start` once the first frame is painted, so what
        this list costs is paid while the reader reads that screen. A module
        belongs here when a turn needs it on the way to its first request and
        the first frame does not: the model SDKs, the zett-agent client, and the
        extensions the configuration turns on.
        """
        config = self.config
        optional = tuple(module for setting, module in WARM_MODULES_WHEN if getattr(config, setting, False))
        return (*WARM_MODULES, *optional)

    def _begin_imports(self) -> None:
        """Start the import pipeline, and the loop-side signal that releases its waiters.

        The signal is an :class:`asyncio.Event` set from the pipeline's thread,
        so the build waits for the imports without occupying a thread of its
        own: the default executor's threads are joined while the interpreter
        shuts down, which is what would keep a launch that ends early alive for
        the whole import.
        """
        loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()

        def finished() -> None:
            """Release the build, from whichever thread the pipeline reports on."""
            loop.call_soon_threadsafe(self._imports_done)

        self._imports = ImportPipeline(self.warm_modules())
        self._imports.start(on_finish=finished)

    def _imports_done(self) -> None:
        """Release whoever waits on the imports; runs on the event loop."""
        if self._ready is not None:
            self._ready.set()

    @property
    def _waiting_for_imports(self) -> bool:
        """Return whether a build is still parked on the import pipeline."""
        return self._ready is not None and not self._ready.is_set()

    async def _build(self) -> ZettCodeRuntime:
        """Wait for the imports, then hand the client its extensions.

        The imports block for a few hundred milliseconds — a model SDK alone is
        most of it on a cold cache — and they are already running on the
        pipeline's thread, so waiting here usually finds them finished and costs
        nothing. The event loop keeps painting through it, and the provider
        built at the end of the wait finds its SDK cached instead of importing
        it here; everything the loop owns is still built on the loop.
        """
        if self._ready is not None:
            await self._ready.wait()

        from zett_agent.client import create_agent

        selected = self.active_model
        model = self._provider(selected)
        capabilities = ModelCapabilities(self._models)
        extensions: list[AgentExtension] = [CodingExtension(), capabilities]
        if self.config.subagent_enabled:
            # Imported with the runtime, not with the module: the subagent
            # extension pulls in its SQLite store and SQLAlchemy, which a launch
            # that never runs a child should not pay for on the way to the first
            # frame. Before ToolGuidelinesExtension, so the task tool's own
            # guidance reaches the prompt it is registered for.
            from .extensions.subagents import subagent_extension

            extensions.append(subagent_extension(model=model, persistence=self.persistence, capabilities=capabilities))
        extensions.extend([ShellDenyExtension(self.policy), self.approval, self.persistence])
        if self.config.todowrite_enabled:
            extensions.append(self.todos)
        extensions.extend(
            [
                self.usage,
                self.context,
                self.sides,
                ToolGuidelinesExtension(),
                *integration_extensions(self.config),
                self.compaction,
                # One host drives every plugin, so the agent sees one extension;
                # the host places itself at the earliest priority any plugin
                # asked for.
                *self.plugins.extensions,
            ]
        )
        client = await create_agent(
            model,
            config=AgentRunConfig(session_id=self.session_id),
            system_prompt=build_system_prompt(self.config),
            extensions=extensions,
            reasoning_effort=self.config.reasoning_effort,
            parallel_tool_call=self.config.parallel_tool_call,
            max_iterations=self.config.max_iterations,
        )
        client.event_dispatcher = self.event_dispatcher
        self.model = model
        self.client = client
        return self

    def _provider(self, selected: ModelConfig) -> Adapter:
        """Return the provider for one configured model, building it if needed.

        Which adapter the entry gets is the entry's own choice: ``anthropic``
        speaks the Messages API through its own SDK, and every other entry
        speaks an OpenAI-compatible one, over chat completions or, when
        ``responses_api`` is set, the Responses API.
        """
        provider = self._models.get(selected)
        if provider is None:
            provider = _build_provider(selected)
            self._models[selected] = provider
        return provider

    @property
    def started(self) -> AgentClient:
        """Return the client, insisting that :meth:`start` has been awaited."""
        if self.client is None:
            raise RuntimeError("Runtime has not started; await start() first")
        return self.client

    @property
    def provider(self) -> Adapter:
        """Return the provider for the active model, insisting the runtime started."""
        if self.model is None:
            raise RuntimeError("Runtime has not started; await start() first")
        return self.model

    def set_event_dispatcher(self, dispatcher: AgentEventDispatcher | None) -> None:
        """Send streamed events to ``dispatcher``, now or as soon as there is a client."""
        self.event_dispatcher = dispatcher
        if self.client is not None:
            self.client.event_dispatcher = dispatcher

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> ZettCodeRuntime:
        """Build and start a runtime, for callers with nothing to paint."""
        runtime = cls.preview(config)
        await runtime.start()
        return runtime

    @property
    def permission(self) -> Permission:
        """Return how much of the shell may run without asking, right now."""
        return self.policy.level

    def use_permission(self, name: str | Permission) -> Permission:
        """Set how much of the shell may run without asking, for the rest of this run.

        Like the approval choices before it the level is a per-run policy and is
        deliberately not persisted: the next start begins at ``ask`` again, which
        matches the fresh session the shell opens on launch. It takes effect on
        the next command, including one in the request that is running now.

        Args:
            name: A level, or its name; case and surrounding space do not matter.

        Raises:
            ValueError: The name is not one of the four levels.
        """
        self.policy.level = name if isinstance(name, Permission) else parse_permission(name)
        return self.policy.level

    def approve_all_shell_commands(self) -> None:
        """Stop asking for shell approval for the rest of this process."""
        self.use_permission(Permission.AUTO)

    def use_effort(self, name: str | ReasoningEffort) -> ReasoningEffort:
        """Select how much reasoning the model may spend on later requests.

        Args:
            name: One of zett-agent's levels, by value (``"high"``) or as the
                enum itself; case and surrounding space are ignored.

        Returns:
            The level now in force.
        """
        if isinstance(name, ReasoningEffort):
            self.effort = name
            return name
        try:
            self.effort = ReasoningEffort(name.strip().lower())
        except ValueError:
            levels = ", ".join(level.value for level in ReasoningEffort)
            raise ValueError(f"Unknown reasoning effort: {name}. Try one of: {levels}") from None
        return self.effort

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent requests without changing sessions."""
        if isinstance(name, ModelConfig):
            chosen = next((entry for entry in self.config.models if entry is name), None)
            if chosen is None:
                raise ValueError("Unknown model selection")
        else:
            matches = [entry for entry in self.config.models if name in (entry.model, entry.display_model)]
            if not matches:
                raise ValueError(f"Unknown model: {name}")
            if len(matches) > 1:
                raise ValueError(f"Ambiguous model: {name}; use a unique display_model")
            chosen = matches[0]
        self.active_model = chosen
        # A preview runtime has no provider yet; the model it names is what
        # :meth:`_build` starts from.
        if self.client is not None:
            self.model = self._provider(chosen)
        # Context size is a property of the model, so switching models moves
        # the point at which a request is compacted with it.
        self.compaction.max_tokens = chosen.compaction_max_tokens
        self.compaction.keep_recent_tokens = chosen.compaction_keep_tokens
        return chosen

    def new_session(self) -> str:
        """Switch future requests to a fresh session identity."""
        self.session_id = new_uuid7()
        return self.session_id

    def use_session(self, session_id: str) -> None:
        """Select a persisted or new explicit session for the next request."""
        if not session_id.strip():
            raise ValueError("Session ID cannot be empty")
        self.session_id = session_id.strip()

    async def aclose(self) -> None:
        """Release all resources owned by this runtime.

        A build that is still parked on its imports is cancelled rather than
        awaited: those modules are for a turn that will not happen now, and the
        thread importing them is a daemon this process does not wait for either.
        A build that is past them is awaited, because it is already creating the
        client this method has to close.
        """
        if self._waiting_for_imports and self._starting is not None:
            self._starting.cancel()
        if self._imports is not None:
            # Whether or not a build is waiting, the imports have no reader left.
            self._imports.stop()
        if self._starting is not None:
            await asyncio.gather(self._starting, return_exceptions=True)
        counter, self._counter = self._counter, None
        if counter is not None:
            # A counter load still running is this shell leaving before it
            # answered: cancelling the wait leaves the load on its daemon thread,
            # which this process does not wait for either.
            counter.cancel()
            await asyncio.gather(counter, return_exceptions=True)
        for model in self._models.values():
            await model.aclose()
        await self.persistence.close()
