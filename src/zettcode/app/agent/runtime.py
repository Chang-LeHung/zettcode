"""Application runtime that composes AgentClient with coding extensions."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime

from zett_agent import (
    AgentClient,
    AgentRunConfig,
    CodingExtension,
    CompactionExtension,
    OpenAIProvider,
    ReasoningEffort,
    ShellApprovalExtension,
    ShellApprovalMode,
    TodoWriteExtension,
    ToolGuidelinesExtension,
    create_agent,
    new_uuid7,
)

from ...config import ModelConfig, ZettCodeConfig
from .context import ContextExtension, Tokenizer
from .storage import SessionStore
from .usage import UsageExtension


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


@dataclass(slots=True)
class ZettCodeRuntime:
    """Own the model, the persistence and approval extensions, the client, and the active session."""

    config: ZettCodeConfig
    client: AgentClient
    persistence: SessionStore
    approval: ShellApprovalExtension
    todos: TodoWriteExtension
    usage: UsageExtension
    context: ContextExtension
    tokenizer: Tokenizer
    effort: ReasoningEffort
    model: OpenAIProvider
    session_id: str
    active_model: ModelConfig
    _models: dict[ModelConfig, OpenAIProvider] = field(default_factory=dict)

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> ZettCodeRuntime:
        """Create all owned resources after changing into the chosen workspace."""
        os.chdir(config.workspace)
        persistence = SessionStore(config.store, config.workspace)
        session_id = new_uuid7()
        selected = config.models[0]
        model = OpenAIProvider(
            selected.model,
            selected.token,
            base_url=selected.base_url,
            response=selected.responses_api,
        )
        todos = TodoWriteExtension()
        approval = ShellApprovalExtension(enabled=config.shell_approval is ShellApprovalMode.REVIEW)
        usage = UsageExtension()
        context = ContextExtension()
        try:
            client = await create_agent(
                model,
                config=AgentRunConfig(session_id=session_id),
                system_prompt=build_system_prompt(config),
                extensions=[
                    CodingExtension(),
                    approval,
                    persistence,
                    todos,
                    usage,
                    context,
                    ToolGuidelinesExtension(),
                    CompactionExtension(
                        None,
                        max_tokens=config.compaction_max_tokens,
                        keep_recent_tokens=config.compaction_keep_tokens,
                    ),
                ],
                reasoning_effort=config.reasoning_effort,
                parallel_tool_call=config.parallel_tool_call,
                max_iterations=config.max_iterations,
            )
        except BaseException:
            await model.aclose()
            await persistence.close()
            raise
        return cls(
            config,
            client,
            persistence,
            approval,
            todos,
            usage,
            context,
            Tokenizer(),
            config.reasoning_effort,
            model,
            session_id,
            selected,
            {selected: model},
        )

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
        if chosen not in self._models:
            self._models[chosen] = OpenAIProvider(
                chosen.model,
                chosen.token,
                base_url=chosen.base_url,
                response=chosen.responses_api,
            )
        self.model = self._models[chosen]
        self.active_model = chosen
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
        for model in self._models.values():
            await model.aclose()
        await self.persistence.close()
