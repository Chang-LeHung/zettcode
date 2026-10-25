"""Application runtime that composes AgentClient with coding extensions.

The runtime is built in two steps. :meth:`ZettCodeEngine.preview` assembles
everything that needs no provider — settings, the session store, this
application's own extensions — so the shell can paint its first frame;
:meth:`ZettCodeEngine.start` imports the provider SDK, builds the client, and
is what a turn or a command awaits before it reaches the model. That split is
worth a few hundred milliseconds of startup, and the modules that cost them
stay out of the import graph until they are needed.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, TypeAlias

from zett_agent.agent import AgentRunConfig
from zett_agent.client import AgentClient
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.extensions.shell_approval import ShellApprovalExtension
from zett_agent.extensions.todo import TodoWriteExtension
from zett_agent.ids import new_uuid7
from zett_agent.model import ReasoningEffort

from zettcode.config import DEFAULT_ANTHROPIC_BASE_URL, KEYLESS_TOKEN, ModelConfig, ZettCodeConfig, model_index
from zettcode.engine.messenger import Messenger
from zettcode.engine.plugins import AgentBuild, Plugins, load_plugins
from zettcode.engine.plugins.services import (
    APPROVAL,
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

from .dialogue.side import SideQuestions
from .extensions.compaction import COUNTER_WAIT, CompactionCounter, OnDemandCompaction
from .extensions.context import ContextExtension, Tokenizer
from .extensions.harness_switch import HarnessSwitch
from .extensions.usage import UsageExtension
from .permission import Permission, ShellPolicy, parse_permission
from .permission.sandbox import ShellSandbox
from .pipeline import ImportPipeline
from .storage import NoLocks, SessionGuard, SessionLocks, SessionStore

if TYPE_CHECKING:  # pragma: no cover - annotations only; the imports are the cost
    from zett_agent.providers.anthropic import AnthropicProvider
    from zett_agent.providers.openai import OpenAIProvider

    #: The adapters this runtime may own. Each is an ``AgentModel``; naming both
    #: is what also says they can be closed, which the runtime does at shutdown.
    Adapter: TypeAlias = OpenAIProvider | AnthropicProvider

#: Loads the plugins for a runtime from the configuration and what the runtime hands them by name.
PluginLoader: TypeAlias = Callable[[ZettCodeConfig, Mapping[str, object]], Plugins]


#: Modules imported ahead of the code that needs them, in this order. The model
#: SDKs are the cost — hundreds of milliseconds each, even with their bytecode
#: cached — and the zett-agent module is what :meth:`ZettCodeEngine._build`
#: would otherwise import on the event loop. A name added here moves its import
#: off the first turn and onto the pipeline's thread.
WARM_MODULES = ("zett_agent.client", "zettcode.engine.extensions.files")

#: What each model SDK needs imported before its first request, in order. ``openai`` alone is not
#: enough: its resource tree (``openai.resources``) is imported the first time a client touches
#: one, and that is five hundred modules — 430 ms measured — on whichever thread made the first
#: request, which is the event loop. ``anthropic`` has no such tree to speak of (15 ms).
OPENAI_WARM_MODULES = ("openai", "openai.resources")
ANTHROPIC_WARM_MODULES = ("anthropic",)


#: Modules a request needs only under the configuration that asks for them: each
#: of these pulls its own machinery, and a run that has no use for one should not
#: pay for it. The names are the ones :meth:`ZettCodeEngine._build` imports.
WARM_MODULES_WHEN = (
    ("subagent_enabled", "zett_agent.extensions.subagent"),
    ("mcp_enabled", "zett_agent.extensions.mcp"),
)


def _load_engine_plugins(config: ZettCodeConfig, shared: Mapping[str, object]) -> Plugins:
    """Load the plugins the engine ships and the installed ones that need only the engine."""
    return load_plugins(config, shared=shared)


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

Changing files: use the file tools, and only them. To edit a file that exists, call
edit directly: read the lines first, copy old_text exactly, and send every change
to that file in one call. Use write_file for a new file or a deliberate whole-file rewrite.
Never change a file's contents through the shell: no sed, awk, perl -i,
python -c, a script you write to do the editing, cat or echo with a redirection, a heredoc,
or tee. There is no delete tool: remove a file with rm in the shell, like any command.
The shell is for running things (tests, builds, git, searches, removing files), not for editing; the
file tools show the user exactly what changed and the shell commands do not. If
edit fails, read the file again and retry it with corrected old_text; do not fall
back to a shell command.

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


def _build_provider(selected: ModelConfig) -> Adapter:
    """Build the adapter one model entry asks for, importing only its SDK.

    The import lives in this function rather than at module level because it is
    the cost the first frame may not pay; the runtime's import pipeline warms the
    same module on its own thread before this runs.

    A model with no key is called with :data:`KEYLESS_TOKEN`, because the adapters refuse to be built without one and a
    local server ignores what it is sent. The temperature is the adapter's own argument on an OpenAI-compatible
    endpoint; Anthropic's adapter has none, so it goes in the body of the request, where the API reads it.
    """
    token = selected.token or KEYLESS_TOKEN
    if selected.anthropic:
        from zett_agent.providers.anthropic import AnthropicProvider

        extra: dict[str, object] = {}
        if selected.temperature is not None:
            extra["extra_body"] = {"temperature": selected.temperature}
        return AnthropicProvider(
            selected.model,
            token,
            base_url=selected.base_url or DEFAULT_ANTHROPIC_BASE_URL,
            **extra,  # type: ignore[arg-type]
        )
    from zett_agent.providers.openai import OpenAIProvider

    options: dict[str, object] = {}
    if selected.temperature is not None:
        options["temperature"] = selected.temperature
    return OpenAIProvider(
        selected.model,
        token,
        base_url=selected.base_url,
        response=selected.responses_api,
        **options,  # type: ignore[arg-type]
    )


@dataclass(slots=True)
class ZettCodeEngine:
    """Own the model, the persistence and approval extensions, the client, and the active session.

    Before :meth:`start` runs, ``client`` and ``model`` are ``None``: everything
    that does not need a provider is already here, which is what lets the shell
    paint. :attr:`started` and :attr:`provider` are the readers that insist the
    runtime is ready.
    """

    config: ZettCodeConfig
    persistence: SessionStore
    #: The permission level, shared with the approval memory and the deny extension.
    policy: ShellPolicy
    #: The level a run starts at, and what a session that never chose one goes back to when it is opened again.
    default_permission: Permission
    tokenizer: Tokenizer
    effort: ReasoningEffort
    session_id: str
    active_model: ModelConfig
    #: What the compaction counts the context with; loaded on a thread of its own so that the
    #: first turn does not load it on the event loop. See :class:`CompactionCounter`.
    compaction_counter: CompactionCounter
    plugins: Plugins = field(default_factory=Plugins)
    #: The lock on the session this process has open: only the process that holds it writes to the session.
    #: A runtime that was not given one (a test's) shares nothing, so every claim is granted.
    session_locks: SessionGuard = field(default_factory=NoLocks)
    #: The line to the other sessions, when the configuration switches messaging on; the shell fills in
    #: what it does with a message received. ``None`` registers no tool and joins no broker.
    messenger: Messenger | None = None
    event_dispatcher: AgentEventDispatcher | None = None
    client: AgentClient | None = None
    model: Adapter | None = None
    _starting: asyncio.Task[ZettCodeEngine] | None = field(default=None, repr=False)
    _counter: asyncio.Task[None] | None = field(default=None, repr=False)
    #: The sweep for empty session folders a killed process left behind, run once at the start on a thread.
    _tidying: asyncio.Task[int] | None = field(default=None, repr=False)
    _models: dict[ModelConfig, Adapter] = field(default_factory=dict)
    #: Each session's own self-compaction choice as last read or written; see :meth:`self_compaction_choice`.
    _self_choices: dict[str, bool | None] = field(default_factory=dict, repr=False)
    #: Each session's own permission level as last read or written; see :meth:`permission_choice`.
    _permissions: dict[str, str | None] = field(default_factory=dict, repr=False)
    #: Whether a level was chosen for this process rather than for a session (``--full``, a client's
    #: ``permission=``): while it is set, opening a session does not put that session's level back.
    _permission_override: bool = field(default=False, repr=False)
    #: The warm-up imports, running on a daemon thread, and the loop-side event
    #: that releases whoever is waiting for them.
    _imports: ImportPipeline | None = field(default=None, repr=False)
    _ready: asyncio.Event | None = field(default=None, repr=False)

    @classmethod
    def preview(cls, config: ZettCodeConfig, load: PluginLoader | None = None) -> ZettCodeEngine:
        """Build the session side of the runtime, without a provider.

        Everything here is cheap: paths, a session identity, and the
        extensions this application owns. The provider SDK, the MCP client,
        and the tokenizer's vocabulary stay unimported until :meth:`start`.

        Args:
            config: Settings for the workspace and the session.
            load: How the plugins are loaded, given the configuration and what the runtime hands them. A front
                end that has plugins of its own passes its loader; the default loads the engine's.
        """
        os.chdir(config.workspace)
        selected = config.models[0]
        # One policy, read by everything that decides whether a command is asked
        # about: the memory lets `safe` and `auto` through, the deny extension
        # refuses for `deny`, and the shell changes it from `/permission`.
        policy = ShellPolicy.from_mode(
            config.shell_approval, config.workspace, ShellSandbox(config.workspace, network=config.shell_network)
        )
        counter = CompactionCounter()
        persistence = SessionStore(config.store, config.workspace)
        models: dict[ModelConfig, Adapter] = {}
        messenger = Messenger.create(config)
        harness = HarnessSwitch(on=config.jit_harness)
        # What the built-in agent plugins build on, handed over by name: they own the extensions, the
        # runtime owns this state and goes on using it. See `zettcode.engine.plugins.services`.
        shared: dict[str, object] = {
            POLICY: policy,
            HARNESS: harness,
            PERSISTENCE: persistence,
            MODELS: models,
            COMPACTION_COUNTER: counter,
            SELECTED_MODEL: selected,
        }
        if messenger is not None:
            shared[MESSENGER] = messenger
        runtime = cls(
            config=config,
            persistence=persistence,
            session_locks=SessionLocks(persistence.session_dir),
            policy=policy,
            default_permission=policy.level,
            tokenizer=Tokenizer(),
            effort=selected.accepted_effort(config.reasoning_effort),
            session_id=new_uuid7(),
            active_model=selected,
            compaction_counter=counter,
            plugins=(load or _load_engine_plugins)(config, shared),
            messenger=messenger,
            _models=models,
        )
        # The session a launch starts in is a new one, so this always succeeds; a launch that resumes
        # another moves the lock when it installs it.
        runtime.session_locks.claim(runtime.session_id)
        # Asked for every request, so a choice made in the middle of a conversation applies to its next one.
        runtime.compaction.self_compact = runtime.self_compacting
        return runtime

    def start(self) -> asyncio.Task[ZettCodeEngine]:
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
            self.compaction_counter.start()
            self._starting = asyncio.ensure_future(self._build())
            self._counter = asyncio.ensure_future(self.tokenizer.prepare())
            # Folders that held no conversation and that no process has open: what a launch that was killed
            # leaves. A thread, because it is a listing and a lock probe per folder and nothing waits for it.
            self._tidying = asyncio.ensure_future(asyncio.to_thread(self.persistence.prune_empty))
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
        # The SDKs of every configured model, not only the active one: `/model` can select an
        # entry that speaks the other API, and its adapter imports its SDK when it is built. An
        # entry that is not configured cannot be selected, so its SDK is left alone — a run that
        # only talks to OpenAI-compatible endpoints does not import `anthropic` on a thread that
        # competes with the interface for the interpreter.
        sdks: list[str] = []
        if any(not model.anthropic for model in config.models):
            sdks.extend(OPENAI_WARM_MODULES)
        if any(model.anthropic for model in config.models):
            sdks.extend(ANTHROPIC_WARM_MODULES)
        optional = tuple(module for setting, module in WARM_MODULES_WHEN if getattr(config, setting, False))
        return (*sdks, *WARM_MODULES, *optional)

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

    async def _build(self) -> ZettCodeEngine:
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
        # The compaction's encoding, loaded on its own thread since `start`: what the first turn
        # would otherwise load on this loop, with nothing painted and no key read until it was done.
        # Waiting for it here is only a wait — the loop is free — and it is bounded, so a first run
        # with no network goes on with an estimate instead of for as long as a download takes.
        await self.compaction_counter.wait(COUNTER_WAIT)

        from zett_agent.client import create_agent

        selected = self.active_model
        model = self._provider(selected)
        # Every extension the agent runs is a plugin's: the built-in ones (the coding tools, the session
        # store, the shell approval, the compaction ... see `zettcode.engine.plugins.builtin_agent`) in the order
        # they are listed there, then any a third-party plugin brings, and last the one host that drives
        # the plugins' hooks, which places itself at the earliest priority any plugin asked for.
        extensions = [*self.plugins.agent_extensions(AgentBuild(model=model)), *self.plugins.extensions]
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
    async def create(cls, config: ZettCodeConfig, load: PluginLoader | None = None) -> ZettCodeEngine:
        """Build and start a runtime, for callers with nothing to paint."""
        runtime = cls.preview(config, load)
        await runtime.start()
        return runtime

    @property
    def todos(self) -> TodoWriteExtension | None:
        """Return the extension that keeps the model's plan, or ``None`` when no plugin provides one."""
        return self.plugins.find(TODOS, TodoWriteExtension)

    @property
    def approval(self) -> ShellApprovalExtension:
        """Return the shell approval extension, whose memory the shell reads and resets."""
        return self.plugins.service(APPROVAL, ShellApprovalExtension)

    @property
    def usage(self) -> UsageExtension:
        """Return the token accounting the status line and ``/usage`` read."""
        return self.plugins.service(USAGE, UsageExtension)

    @property
    def context(self) -> ContextExtension:
        """Return the recorder of what each session's last request was made of."""
        return self.plugins.service(CONTEXT, ContextExtension)

    @property
    def sides(self) -> SideQuestions:
        """Return the read-only boundary a side question runs behind; the shell marks the run it starts."""
        return self.plugins.service(SIDES, SideQuestions)

    @property
    def compaction(self) -> OnDemandCompaction:
        """Return the compaction policy, which a model switch resizes."""
        return self.plugins.service(COMPACTION, OnDemandCompaction)

    @property
    def harness(self) -> HarnessSwitch:
        """Return the switch of the just-in-time harness, which the next request reads."""
        return self.plugins.service(HARNESS, HarnessSwitch)

    def use_harness(self, on: bool) -> bool:
        """Turn the just-in-time harness on or off for later requests, and return whether it is on.

        Like the permission level this is per run and not written to the configuration: ``[harness] jit`` is the
        default a run starts with. It takes effect on the next request, because a request mounts the harness's
        tools when it starts.
        """
        self.harness.on = bool(on)
        return self.harness.on

    @property
    def permission(self) -> Permission:
        """Return how much of the shell may run without asking, right now."""
        return self.policy.level

    def use_permission(self, name: str | Permission, *, remember: bool = True) -> Permission:
        """Set how much of the shell may run without asking, and remember it for this session.

        The level is written to the session's own metadata, so opening the session again puts it back in force
        instead of asking all over again; a session set back to the level a run starts at forgets the choice and
        follows the default. A new session begins at the default, so one job's decision does not leak into the
        next. It takes effect on the next command, including one in the request that is running now.

        Args:
            name: A level, or its name; case and surrounding space do not matter.
            remember: Whether the level belongs to the session. ``False`` is for a decision that covers this run
                only, such as "approve every command" from the approval panel.

        Raises:
            ValueError: The name is not one of the four levels.
            OSError: The level could not be written to the session; nothing changed, so a caller that reported
                success would be reporting a setting that is not on disk.
        """
        selected = name if isinstance(name, Permission) else parse_permission(name)
        if remember:
            self.persistence.set_permission(self.session_id, selected.value, default=self.default_permission.value)
            self._permissions[self.session_id] = selected.value
            # The level belongs to the session again, so opening another one puts that one's level back.
            self._permission_override = False
        else:
            # A level chosen for this process wins over what a session remembers, for as long as it runs.
            self._permission_override = True
        self.policy.level = selected
        return selected

    def permission_choice(self, session_id: str) -> str | None:
        """Return the level one session last ran at, ``None`` when it never chose one.

        Read from the session's file once and remembered: opening a session asks for it on every start, and the
        only writer is the process holding the session's lock.
        """
        if session_id not in self._permissions:
            self._permissions[session_id] = self.persistence.session_permission(session_id)
        return self._permissions[session_id]

    def _adopt_permission(self) -> None:
        """Put the active session's own level in force, or the one a run starts at when it has none."""
        if self._permission_override:
            return
        stored = self.permission_choice(self.session_id)
        try:
            self.policy.level = self.default_permission if stored is None else Permission(stored)
        except ValueError:
            # A level a newer version wrote, or a damaged file: the default is the honest answer.
            self.policy.level = self.default_permission

    def approve_all_shell_commands(self) -> None:
        """Stop asking for shell approval for the rest of this process."""
        self.use_permission(Permission.FULL, remember=False)

    def self_compaction_choice(self, session_id: str) -> bool | None:
        """Return the choice one session made about self-compaction, ``None`` when it follows the default.

        Read from the session's file once and remembered: the status line asks on every repaint, and only
        the process that holds the session's lock writes it, so what was read stays true until this
        runtime changes it.
        """
        if session_id not in self._self_choices:
            self._self_choices[session_id] = self.persistence.session_self_compact(session_id)
        return self._self_choices[session_id]

    def choose_self_compaction(self, session_id: str, choice: bool | None) -> None:
        """Save one session's choice about self-compaction, and remember it only once it is saved.

        Raises:
            OSError: The choice could not be written; the remembered one is unchanged.
        """
        self.persistence.set_self_compact(session_id, choice, default=self.config.self_compaction)
        self._self_choices[session_id] = choice

    def self_compacting(self, session_id: str) -> bool:
        """Return whether the model may request compaction in one session.

        The session's own choice when it made one, else the configuration's ``[compaction] self``.
        """
        choice = self.self_compaction_choice(session_id)
        return self.config.self_compaction if choice is None else choice

    def use_effort(self, name: str | ReasoningEffort) -> ReasoningEffort:
        """Select how much reasoning the model may spend on later requests.

        A level the active model does not take is refused, naming the ones it does: a reader who typed
        ``/effort ultra`` should hear that this model stops at ``high``, not get ``high`` unannounced.
        (A level that is *inherited* — the one in force when the model changes — is moved, by
        :meth:`use_model`, because nobody asked for it.)

        Args:
            name: One of zett-agent's levels, by value (``"high"``) or as the
                enum itself; case and surrounding space are ignored.

        Returns:
            The level now in force.

        Raises:
            ValueError: The name is not a level, or the active model does not take it.
        """
        if isinstance(name, ReasoningEffort):
            level = name
        else:
            try:
                level = ReasoningEffort(name.strip().lower())
            except ValueError:
                levels = ", ".join(known.value for known in ReasoningEffort)
                raise ValueError(f"Unknown reasoning effort: {name}. Try one of: {levels}") from None
        accepted = self.active_model.efforts
        if level not in accepted:
            levels = ", ".join(known.value for known in accepted)
            raise ValueError(f"{self.active_model.shown_name} does not take {level.value}. Try one of: {levels}")
        self.effort = level
        return level

    def find_model(self, name: str) -> ModelConfig | None:
        """Return the configured model a recorded name stands for, if exactly one does.

        The name a session records is the one the picker showed. It is looked for first as that, and only when no
        display name answers, as a model id — ``/model`` takes a name the same way, so a session and a reader
        always mean the same model by one word. A name that two entries answer to is not a choice this can make
        for the reader, and is reported as not found: the configuration is no longer the one the session was saved
        with, and guessing would move the model under the reader without saying so.
        """
        try:
            index = model_index(self.config.models, name)
        except ValueError:
            return None
        return None if index is None else self.config.models[index]

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent requests without changing sessions."""
        if isinstance(name, ModelConfig):
            # The very entry first, so two entries that hold the same settings stay two choices; an
            # equal one is accepted too, because a model read back from the config file is a new
            # object holding what the session's entry holds, and is the same model to a reader.
            chosen = next((entry for entry in self.config.models if entry is name), None) or next(
                (entry for entry in self.config.models if entry == name), None
            )
            if chosen is None:
                raise ValueError("Unknown model selection")
        else:
            index = model_index(self.config.models, name)
            if index is None:
                raise ValueError(f"Unknown model: {name}")
            chosen = self.config.models[index]
        self.active_model = chosen
        # A preview runtime has no provider yet; the model it names is what
        # :meth:`_build` starts from.
        if self.client is not None:
            self.model = self._provider(chosen)
        # Context size is a property of the model, so switching models moves
        # the point at which a request is compacted with it.
        self.compaction.max_tokens = chosen.compaction_max_tokens
        self.compaction.keep_recent_tokens = chosen.compaction_keep_tokens
        # The level in force follows the model to the nearest one it takes, so a request is never sent
        # with a level its endpoint would reject.
        self.effort = chosen.accepted_effort(self.effort)
        return chosen

    def replace_models(self, models: tuple[ModelConfig, ...]) -> ModelConfig:
        """Adopt a new list of models in this running session, keeping the one in use if it is still there.

        This is what ``/config`` calls after it has written the file: the entries a reader added or
        removed take effect without a restart, and the model a conversation is using is not
        changed under it unless it was the one removed. An entry is the same entry when it is equal
        by value — what is read back from the file is a new object holding the same settings — and
        the one in use is looked for that way. When it is not there — it was removed, or it was the
        entry that was edited — the entry now at its old place takes over: the edited one stays in
        use, and a removed one is replaced by its neighbour rather than by whichever came first.

        Args:
            models: The configured models, in file order; must not be empty.

        Returns:
            The model in use afterwards, which is the previous one unless it was removed.
        """
        if not models:
            raise ValueError("At least one model must stay configured")
        previous = self.active_model
        old = self.config.models
        place = old.index(previous) if previous in old else 0
        self.config = replace(self.config, models=models)
        # The adapters already built stay in the cache even for an entry that is gone: the cache is
        # what shutdown walks to close each client, so dropping one here would leak its connection.
        chosen = next((entry for entry in models if entry == previous), models[min(place, len(models) - 1)])
        return self.use_model(chosen)

    def new_session(self) -> str:
        """Switch future requests to a fresh session identity, and lock it."""
        self.session_id = new_uuid7()
        self.session_locks.claim(self.session_id)
        self._adopt_permission()
        return self.session_id

    def use_session(self, session_id: str) -> None:
        """Select a persisted or new explicit session for the next request, and try to lock it.

        Whether the lock was had is :attr:`session_locked`: a session another process has open is still
        selected, so the reader can read it, and is not written to.
        """
        if not session_id.strip():
            raise ValueError("Session ID cannot be empty")
        self.session_id = session_id.strip()
        self.session_locks.claim(self.session_id)
        self._adopt_permission()

    @property
    def session_locked(self) -> bool:
        """Return whether the active session is held by another process, so that this one only reads it."""
        return not self.session_locks.holds(self.session_id)

    def retake_session(self) -> bool:
        """Try again to lock the active session, and say whether this process holds it now."""
        return self.session_locks.claim(self.session_id)

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
        tidying, self._tidying = self._tidying, None
        if tidying is not None:
            await asyncio.gather(tidying, return_exceptions=True)
        for model in self._models.values():
            await model.aclose()
        await self.persistence.close()
        self.session_locks.release()
