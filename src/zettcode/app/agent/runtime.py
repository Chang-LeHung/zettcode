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
    ShellApprovalExtension,
    ShellApprovalMode,
    TodoWriteExtension,
    ToolGuidelinesExtension,
    create_agent,
    new_uuid7,
)

from ...config import ModelConfig, ZettCodeConfig
from .session import SessionStore


def build_system_prompt(config: ZettCodeConfig) -> str:
    """Build request instructions with an explicit workspace boundary."""
    now = datetime.now().astimezone()
    return f"""You are ZettCode, a focused coding agent working with the user in one local workspace.

Inspect relevant files before editing. Make focused changes, preserve unrelated work,
and run checks proportional to risk. Explain blockers concretely. Do not perform
destructive actions unless the user explicitly requests them.

Runtime environment:
- Workspace: {config.workspace}
- Local time: {now.isoformat(timespec="seconds")}
- Operating system: {platform.platform()}
- Architecture: {platform.machine() or "unknown"}
- Python: {platform.python_implementation()} {platform.python_version()}
- Executable: {sys.executable}
- Shell: {os.getenv("SHELL", "unknown")}

Treat the workspace as the current working directory. Prefer relative paths in tool
calls. Verify mutable facts with tools instead of assuming this startup snapshot is current."""


@dataclass(slots=True)
class ZettCodeRuntime:
    """Own the model, persistence extension, AgentClient, and active session."""

    config: ZettCodeConfig
    client: AgentClient
    persistence: SessionStore
    todos: TodoWriteExtension
    model: OpenAIProvider
    session_id: str
    active_model: ModelConfig
    _models: dict[ModelConfig, OpenAIProvider] = field(default_factory=dict)

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> ZettCodeRuntime:
        """Create all owned resources after changing into the chosen workspace."""
        os.chdir(config.workspace)
        persistence = SessionStore(config.store)
        recent = await persistence.list_sessions(limit=1)
        session_id = recent[0].session_id if recent else new_uuid7()
        selected = config.models[0]
        model = OpenAIProvider(
            selected.model,
            selected.token,
            base_url=selected.base_url,
            response=selected.responses_api,
        )
        todos = TodoWriteExtension()
        try:
            client = await create_agent(
                model,
                config=AgentRunConfig(session_id=session_id),
                system_prompt=build_system_prompt(config),
                extensions=[
                    CodingExtension(),
                    ShellApprovalExtension(enabled=config.shell_approval is ShellApprovalMode.REVIEW),
                    persistence,
                    todos,
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
        return cls(config, client, persistence, todos, model, session_id, selected, {selected: model})

    def use_model(self, name: str) -> ModelConfig:
        """Select a configured model for subsequent requests without changing sessions."""
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
