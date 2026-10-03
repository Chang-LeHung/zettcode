"""Application-facing coding agent used by the terminal UI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from zett_agent import (
    SHELL_APPROVAL_RESPONSE_EVENT_NAME,
    AgentEvent,
    AgentEventDispatcher,
    AgentRunConfig,
    ExternalEvent,
)

from ...config import ModelConfig, ZettCodeConfig
from ..commands import Command, CommandResult
from .runtime import ZettCodeRuntime
from .session import Session


class ZettCodeAgent:
    """Expose agent operations without leaking runtime resources to the UI.

    The runtime assembles the vendor client and extensions; this class is the
    application's entry point for turns, session and model selection, progress,
    and responses to approval requests.
    """

    def __init__(self, runtime: ZettCodeRuntime) -> None:
        self.runtime = runtime

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> ZettCodeAgent:
        """Build the runtime and wrap it in the application agent."""
        return cls(await ZettCodeRuntime.create(config))

    @property
    def workspace(self) -> Path:
        """Return the workspace displayed in the header."""
        return self.runtime.config.workspace

    @property
    def reduced_motion(self) -> bool:
        """Return whether decorative animation is disabled."""
        return self.runtime.config.reduced_motion

    @property
    def session_id(self) -> str:
        """Return the session used for the next turn."""
        return self.runtime.session_id

    @property
    def models(self) -> tuple[ModelConfig, ...]:
        """Return the models available for selection."""
        return self.runtime.config.models

    @property
    def commands(self) -> tuple[Command, ...]:
        """Return the commands owned by the coding agent."""
        return (
            Command("/new", "start a fresh session", "agent", self._command_new),
            Command("/sessions", "list persisted sessions", "agent", self._command_sessions),
            Command("/model", "choose a model", "agent", self._command_model),
            Command("/use", "switch to a session: /use <id>", "agent", self._command_use),
        )

    @property
    def active_model(self) -> ModelConfig:
        """Return the model selected for the next turn."""
        return self.runtime.active_model

    def set_event_dispatcher(self, dispatcher: AgentEventDispatcher) -> None:
        """Send streamed agent events to the application's transcript projector."""
        self.runtime.client.event_dispatcher = dispatcher

    def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """Run one turn with the selected session and model."""
        return self.runtime.client.stream(
            prompt,
            config=AgentRunConfig(session_id=self.session_id),
            model=self.runtime.model,
        )

    def tasks(self) -> tuple[tuple[str, str], ...]:
        """Return the current session's plan as display-ready status/content pairs."""
        progress = self.runtime.todos.todos(self.session_id)
        return tuple((item.status.value, item.content) for item in progress.todos) if progress else ()

    def new_session(self) -> str:
        """Start a new conversation."""
        return self.runtime.new_session()

    def use_session(self, session_id: str) -> None:
        """Switch future turns to a session."""
        self.runtime.use_session(session_id)

    async def list_sessions(self, *, limit: int = 20) -> list[Session]:
        """List persisted sessions by recent activity."""
        return await self.runtime.persistence.list_sessions(limit=limit)

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent turns."""
        return self.runtime.use_model(name)

    async def _command_new(self, argument: str) -> CommandResult:
        """Start a fresh session."""
        session_id = self.new_session()
        return CommandResult(notification=f"started session {session_id[:8]}")

    async def _command_use(self, argument: str) -> CommandResult:
        """Switch to the requested session."""
        if not argument:
            return CommandResult(messages=("Usage: /use <session-id>",))
        self.use_session(argument)
        return CommandResult(notification=f"using session {self.session_id[:8]}")

    async def _command_sessions(self, argument: str) -> CommandResult:
        """List recent sessions in the transcript."""
        sessions = await self.list_sessions(limit=20)
        if not sessions:
            return CommandResult(messages=("No persisted sessions.",))
        return CommandResult(
            messages=tuple(
                f"{'*' if session.session_id == self.session_id else ' '} "
                f"{session.session_id}  {session.message_count} messages"
                for session in sessions
            )
        )

    async def _command_model(self, argument: str) -> CommandResult:
        """Open the picker, or select a named model directly."""
        if not argument:
            return CommandResult(page="models")
        selected = self.use_model(argument)
        return CommandResult(notification=f"using model {selected.shown_name}", relayout=True)

    def respond_approval(self, session_id: str, call_id: str, decision: str, remember: bool) -> None:
        """Answer a pending shell approval for the originating session."""
        self.runtime.client.agent.emit_external_event(
            ExternalEvent(
                name=SHELL_APPROVAL_RESPONSE_EVENT_NAME,
                payload={"tool_call_id": call_id, "decision": decision, "remember": remember},
            ),
            config=AgentRunConfig(session_id=session_id),
        )

    async def aclose(self) -> None:
        """Release the underlying runtime resources."""
        await self.runtime.aclose()
