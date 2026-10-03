"""Application-facing coding agent used by the terminal UI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from zett_agent import (
    SHELL_APPROVAL_RESPONSE_EVENT_NAME,
    AgentEvent,
    AgentEventDispatcher,
    AgentRunConfig,
    AssistantMessage,
    ExternalEvent,
    ToolMessage,
    UserMessage,
)

from ...config import ModelConfig, ZettCodeConfig
from ..commands import Command, CommandResult
from .entries import EntryStatus
from .runtime import ZettCodeRuntime
from .storage import SessionInfo
from .title import summarize_title
from .transcript import Transcript


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
        """Return the conversation commands the agent owns.

        They report through transcript Markdown; commands that present a widget
        (such as the model picker) belong to the shell, which owns the widgets.
        """
        return (
            Command("/new", "start a fresh session", "agent", self._command_new),
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

    def restore_session(self, session_id: str, transcript: Transcript) -> None:
        """Load the active stored branch into the UI before switching sessions."""
        session = self.runtime.persistence.read(session_id)
        if session.header is None:
            raise ValueError(f"Unknown session: {session_id}")
        restored = Transcript(renderers=transcript.renderers, processors=transcript.processors)
        restored.frame = transcript.frame
        for line in session.branch():
            message = line.message[0]
            match message:
                case UserMessage():
                    restored.user_message(message.text)
                case AssistantMessage():
                    if message.reasoning:
                        restored.restore_thinking(message.reasoning, line.timing.reasoning_duration_ns)
                    if message.content:
                        restored.append_answer(message.content)
                    for call in message.tool_calls:
                        restored.start_tool(call.id, call.name, call.arguments)
                case ToolMessage():
                    status = EntryStatus.COMPLETED if message.success else EntryStatus.FAILED
                    restored.complete_tool(message.tool_call_id, message.text, status=status, wait=False)
                case _:
                    continue
        restored.finish_restored_tools()
        transcript.replace(restored.entries)
        self.use_session(session_id)

    async def list_sessions(self, *, limit: int = 20) -> list[SessionInfo]:
        """List persisted session metadata by recent activity."""
        return await self.runtime.persistence.list_sessions(limit=limit)

    async def title_session(self, session_id: str) -> str | None:
        """Name a session from its first exchange, unless it already has a title.

        The call is a background nicety: it reads the stored branch, asks the
        active model for a short title, and appends that title to the session.

        Args:
            session_id: Session to name.

        Returns:
            The stored title, or ``None`` when the session was already named, has
            no first exchange yet, or the model replied with nothing usable.
        """
        if self.runtime.persistence.session_title(session_id) is not None:
            return None
        session = self.runtime.persistence.read(session_id)
        branch = session.branch()
        question = next(
            (line.message[0].text for line in branch if isinstance(line.message[0], UserMessage)),
            None,
        )
        answer = next(
            (line.message[0].content for line in reversed(branch) if isinstance(line.message[0], AssistantMessage)),
            None,
        )
        if not question or not answer:
            return None
        title = await summarize_title(self.runtime.model, question=question, answer=answer)
        if title is None:
            return None
        await self.runtime.persistence.set_title(session_id, title)
        return title

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent turns."""
        return self.runtime.use_model(name)

    def approve_all_shell_commands(self) -> None:
        """Approve every shell command for the rest of this run, without asking."""
        self.runtime.approve_all_shell_commands()

    async def _command_new(self, argument: str) -> CommandResult:
        """Start a fresh session."""
        session_id = self.new_session()
        return CommandResult(notification=f"started session {session_id[:8]}")

    async def _command_use(self, argument: str) -> CommandResult:
        """Switch to the requested session."""
        if not argument:
            return CommandResult(message="Usage: `/use <session-id>`")
        self.use_session(argument)
        return CommandResult(notification=f"using session {self.session_id[:8]}")

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
