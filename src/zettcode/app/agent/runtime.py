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
from typing import TYPE_CHECKING

from zett_agent.agent import AgentRunConfig
from zett_agent.client import AgentClient
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.coding import CodingExtension
from zett_agent.extensions.shell_approval import ShellApprovalExtension, ShellApprovalMode
from zett_agent.extensions.todo import TodoWriteExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.ids import new_uuid7
from zett_agent.model import ReasoningEffort

from ...config import DEFAULT_MCP_CONFIG, ModelConfig, ZettCodeConfig
from ...plugins import Plugins, load_plugins
from .approval import ShellApprovalMemory
from .capabilities import ModelCapabilities
from .compaction import OnDemandCompaction
from .context import ContextExtension, Tokenizer
from .storage import SessionStore
from .subagents import ZettCodeSubAgents
from .usage import UsageExtension

if TYPE_CHECKING:  # pragma: no cover - annotations only; the imports are the cost
    from zett_agent.providers.openai import OpenAIProvider


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
    """Return the optional skills and MCP extensions this configuration asks for.

    Both live outside the model loop, so they are built here and handed to
    :func:`create_agent` with the rest. MCP is skipped when there is no server
    file to read: an unconfigured run then carries no MCP instructions at all,
    rather than a system message saying there is nothing to load.

    Args:
        config: Settings naming the skill roots and the MCP server file.

    Returns:
        The extensions to add, most specific first.
    """
    from zett_agent.extensions.skill import SkillExtension

    from .mcp import ReportingMcpExtension

    extensions: list[AgentExtension] = []
    if config.skills_enabled:
        extensions.append(SkillExtension(config.skill_search_roots()))
    if config.mcp_enabled:
        path = config.mcp_config or DEFAULT_MCP_CONFIG
        if Path(path).expanduser().is_file():
            extensions.append(ReportingMcpExtension(config_path=path))
    return tuple(extensions)


def describe_error(error: BaseException) -> str:
    """Return the reasons an exception carries, not the group that wraps them.

    A failure inside a task group arrives as an ``ExceptionGroup`` whose own
    text says nothing — "unhandled errors in a TaskGroup (1 sub-exception)" —
    and a server refusing a connection is reported exactly that way. The reasons
    are the leaves, so that is what a row shows, each one once, however deeply
    the groups nest.

    Args:
        error: The exception a request failed with.

    Returns:
        The leaf reasons joined by ``"; "``, or the class name when a reason has
        no text of its own.
    """
    reasons: list[str] = []
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop(0)
        if isinstance(current, BaseExceptionGroup):
            pending[:0] = list(current.exceptions)
            continue
        text = str(current).strip() or type(current).__name__
        if text not in reasons:
            reasons.append(text)
    return "; ".join(reasons)


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
    todos: TodoWriteExtension
    usage: UsageExtension
    context: ContextExtension
    tokenizer: Tokenizer
    effort: ReasoningEffort
    session_id: str
    active_model: ModelConfig
    compaction: OnDemandCompaction
    plugins: Plugins = field(default_factory=Plugins)
    event_dispatcher: AgentEventDispatcher | None = None
    client: AgentClient | None = None
    model: OpenAIProvider | None = None
    _starting: asyncio.Task[ZettCodeRuntime] | None = field(default=None, repr=False)
    _models: dict[ModelConfig, OpenAIProvider] = field(default_factory=dict)

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
        return cls(
            config=config,
            persistence=SessionStore(config.store, config.workspace),
            approval=ShellApprovalExtension(
                ShellApprovalMemory(),
                enabled=config.shell_approval is ShellApprovalMode.REVIEW,
            ),
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
        build two clients, and every later caller gets the same answer.
        """
        if self._starting is None:
            self._starting = asyncio.ensure_future(self._build())
        return self._starting

    async def _build(self) -> ZettCodeRuntime:
        """Import what a provider needs, then hand the client its extensions."""
        from zett_agent.client import create_agent

        selected = self.active_model
        model = self._provider(selected)
        capabilities = ModelCapabilities(self._models)
        client = await create_agent(
            model,
            config=AgentRunConfig(session_id=self.session_id),
            system_prompt=build_system_prompt(self.config),
            extensions=[
                CodingExtension(),
                capabilities,
                # Before ToolGuidelinesExtension, so the task tool's own
                # guidance reaches the prompt it is registered for.
                ZettCodeSubAgents(
                    model=model,
                    persistence=self.persistence,
                    capabilities=capabilities,
                ),
                self.approval,
                self.persistence,
                self.todos,
                self.usage,
                self.context,
                ToolGuidelinesExtension(),
                *integration_extensions(self.config),
                self.compaction,
                # One host drives every plugin, so the agent sees one
                # extension; the host places itself at the earliest priority
                # any plugin asked for.
                *self.plugins.extensions,
            ],
            reasoning_effort=self.config.reasoning_effort,
            parallel_tool_call=self.config.parallel_tool_call,
            max_iterations=self.config.max_iterations,
        )
        client.event_dispatcher = self.event_dispatcher
        self.model = model
        self.client = client
        return self

    def _provider(self, selected: ModelConfig) -> OpenAIProvider:
        """Return the provider for one configured model, building it if needed."""
        from zett_agent.providers.openai import OpenAIProvider

        provider = self._models.get(selected)
        if provider is None:
            provider = OpenAIProvider(
                selected.model,
                selected.token,
                base_url=selected.base_url,
                response=selected.responses_api,
            )
            self._models[selected] = provider
        return provider

    @property
    def started(self) -> AgentClient:
        """Return the client, insisting that :meth:`start` has been awaited."""
        if self.client is None:
            raise RuntimeError("Runtime has not started; await start() first")
        return self.client

    @property
    def provider(self) -> OpenAIProvider:
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

    def approve_all_shell_commands(self) -> None:
        """Stop asking for shell approval for the rest of this process.

        Approval is a per-run policy and is deliberately not persisted: the
        next start begins in review mode again, matching the fresh session the
        shell opens on launch.
        """
        self.approval.enabled = False

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
        """Release all resources owned by this runtime."""
        if self._starting is not None and not self._starting.done():
            await asyncio.gather(self._starting, return_exceptions=True)
        for model in self._models.values():
            await model.aclose()
        await self.persistence.close()
