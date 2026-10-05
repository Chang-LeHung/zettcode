"""Application-facing coding agent used by the terminal UI."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from zett_agent.agent import AgentRunConfig
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.extensions.events import CompactionEvent
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_RESPONSE_EVENT_NAME
from zett_agent.messages import (
    AnyMessage,
    AssistantMessage,
    ImageBytesSource,
    ImageContent,
    SystemMessage,
    TextContent,
    ToolMessage,
    UserMessage,
)
from zett_agent.model import ReasoningEffort

from ...config import ModelConfig, ZettCodeConfig
from ..commands import Command, CommandResult
from .context import ContextReport
from .entries import EntryStatus
from .runtime import ZettCodeRuntime, build_system_prompt
from .storage import SessionInfo
from .title import summarize_title
from .transcript import Transcript
from .usage import UsageSnapshot

#: One piece of a user turn, in the order it was written: a run of text, or the
#: encoded bytes and media type of an image placed where that run ends.
PromptPart = str | tuple[bytes, str]


#: The name a session shows before the agent has given it a title.
UNTITLED_SESSION = "New session"


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

    @classmethod
    def preview(cls, config: ZettCodeConfig) -> ZettCodeAgent:
        """Wrap a runtime that still has to start, so a shell can paint first.

        The runtime here holds the session and this application's own
        extensions; the provider SDK and the client are built by the first
        :meth:`runtime.start`, which a turn or a command awaits. Everything the
        shell reads per frame — the model, the effort, the session, the usage —
        is answered from that preview.
        """
        return cls(ZettCodeRuntime.preview(config))

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
    def session_title(self) -> str | None:
        """Return the active session's stored display title, if it has one.

        Reading the store folds the whole metadata log, so callers that paint
        often should cache the result instead of asking once per frame.
        """
        return self.runtime.persistence.session_title(self.session_id)

    @property
    def session_name(self) -> str:
        """Return the name to show for the active session.

        A session is named after its first reply; until then the store has no
        title, and a status line or list row that shows nothing at all reads
        like a bug rather than like a fresh session.
        """
        return self.session_title or UNTITLED_SESSION

    @property
    def usage(self) -> UsageSnapshot:
        """Return the active session's cumulative token counters.

        The numbers come from the usage extension's in-memory totals, so the
        status line can read them every frame; a session replayed from the store
        is seeded before this is asked.
        """
        return self.runtime.usage.snapshot(self.session_id)

    async def context_report(self) -> ContextReport | None:
        """Return what the next request carries by source, or None before the first call.

        The tokenizer is prepared first: it prefers tiktoken and falls back to a
        character estimate when that vocabulary cannot be opened, which the
        report names so the numbers are not mistaken for exact ones.
        """
        tokenizer = self.runtime.tokenizer
        await tokenizer.prepare()
        return self.runtime.context.report(
            self.session_id,
            window=self.runtime.active_model.context_window,
            tokenizer=tokenizer,
        )

    @property
    def models(self) -> tuple[ModelConfig, ...]:
        """Return the models available for selection."""
        return self.runtime.config.models

    @property
    def effort(self) -> str:
        """Return the reasoning effort the next request will ask for."""
        return self.runtime.effort.value

    @property
    def efforts(self) -> tuple[str, ...]:
        """Return the reasoning levels the runtime accepts, cheapest first."""
        return tuple(level.value for level in ReasoningEffort)

    def use_effort(self, name: str) -> str:
        """Select a reasoning level for later requests and return its value."""
        return self.runtime.use_effort(name).value

    @property
    def commands(self) -> tuple[Command, ...]:
        """Return the conversation commands the agent owns.

        They report through transcript Markdown; commands that present a widget
        (such as the model picker) belong to the shell, which owns the widgets.
        """
        return (
            Command("/new", "start a fresh session", "agent", self._command_new),
            Command("/use", "switch to a session: /use <id>", "agent", self._command_use),
            Command("/compact", "summarize the context now", "agent", self._command_compact),
        )

    @property
    def active_model(self) -> ModelConfig:
        """Return the model selected for the next turn."""
        return self.runtime.active_model

    def set_event_dispatcher(self, dispatcher: AgentEventDispatcher) -> None:
        """Send streamed agent events to the application's transcript projector."""
        self.runtime.set_event_dispatcher(dispatcher)

    async def stream(self, parts: Sequence[PromptPart]) -> AsyncIterator[AgentEvent]:
        """Run one turn with the selected session, model, and reasoning effort.

        Args:
            parts: The user turn in the order it was written: text runs and the
                images the composer interleaved with them. A turn without
                images is simply one text part.
        """
        await self.runtime.start()
        client = self.runtime.started
        async for event in client.stream(
            self.request(parts),
            config=AgentRunConfig(session_id=self.session_id),
            model=self.runtime.provider,
            reasoning_effort=self.runtime.effort,
        ):
            yield event

    @staticmethod
    def request(parts: Sequence[PromptPart]) -> str | UserMessage:
        """Return the user turn those ordered parts make up.

        Text and images keep the order they were written in inside one
        ``UserMessage``, so a picture is read where its writer placed it rather
        than after the whole prompt. A turn with no image stays a plain string.
        """
        if all(isinstance(part, str) for part in parts):
            return "".join(part for part in parts if isinstance(part, str))
        content: list[TextContent | ImageContent] = []
        for part in parts:
            if isinstance(part, str):
                if part:
                    content.append(TextContent(part))
                continue
            data, media_type = part
            content.append(ImageContent(source=ImageBytesSource(data=data, media_type=media_type)))
        return UserMessage(content=content)

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
        usage = UsageSnapshot()
        history: list[AnyMessage] = []
        for line in session.branch():
            if line.usage is not None:
                # Assistant lines are the ones that consumed a model response;
                # their duration is the generation time the rate divides by.
                usage = usage.with_usage(line.usage, line.timing.duration_ns / 1_000_000_000)
            message = line.message[0]
            if message.include_in_messages and not isinstance(message, SystemMessage):
                # The same slice a request would restore, so `/context` can
                # measure a session that has not run in this process yet.
                history.append(message)
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
        self.runtime.usage.seed(session_id, usage)
        # The instructions come from a request this process already assembled, or
        # from the prompt the runtime would build; the environment and tool notes
        # only exist inside a request, which the report admits.
        instructions = self.runtime.context.instructions or (
            SystemMessage(content=build_system_prompt(self.runtime.config)),
        )
        self.runtime.context.remember(session_id, [*instructions, *history])
        self.use_session(session_id)

    async def list_sessions(self, *, limit: int = 20) -> list[SessionInfo]:
        """List persisted session metadata by recent activity."""
        return await self.runtime.persistence.list_sessions(limit=limit)

    async def rename_session(self, title: str) -> str:
        """Store a display title for the active session and return it cleaned.

        A title the user typed wins over the one the background summarizer would
        have written: ``title_session`` never renames a session that already has
        a title, so naming by hand also stops the model call.

        Args:
            title: Name to store; surrounding space is trimmed, and a blank or
                over-long name is rejected by the store.
        """
        await self.runtime.persistence.set_title(self.session_id, title)
        return title.strip()

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
        await self.runtime.start()
        title = await summarize_title(self.runtime.provider, question=question, answer=answer)
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

    async def compact(self) -> CompactionEvent | None:
        """Summarize the conversation now, without adding a turn to it.

        zett-agent runs one pass over the restored session and dispatches every
        event it emits, so the transcript animates the same ``Compacting`` row an
        automatic compaction shows. Nothing is appended to the conversation and
        no primary model call is made: the only work is the summary itself.

        Returns:
            The checkpoint that was stored, or ``None`` when there was nothing
            worth replacing.
        """
        await self.runtime.start()
        return await self.runtime.started.compact(
            config=AgentRunConfig(session_id=self.session_id),
            model=self.runtime.provider,
        )

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

    async def _command_compact(self, argument: str) -> CommandResult:
        """Summarize the conversation now, whatever its size.

        The row and the outcome notice arrive while this await runs: the pass
        dispatches through the same event dispatcher a turn does, so the
        transcript animates ``Compacting`` and ends with ``Context compaction
        applied`` (or ``skipped`` when the summary would not be smaller).
        """
        await self.compact()
        return CommandResult()

    def respond_approval(self, session_id: str, call_id: str, decision: str, remember: bool) -> None:
        """Answer a pending shell approval for the originating session."""
        self.runtime.started.agent.emit_external_event(
            ExternalEvent(
                name=SHELL_APPROVAL_RESPONSE_EVENT_NAME,
                payload={"tool_call_id": call_id, "decision": decision, "remember": remember},
            ),
            config=AgentRunConfig(session_id=session_id),
        )

    async def aclose(self) -> None:
        """Release the underlying runtime resources."""
        await self.runtime.aclose()
