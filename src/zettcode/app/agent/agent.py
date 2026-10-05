"""Application-facing coding agent used by the terminal UI."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from zett_agent.agent import AgentRunConfig
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.extensions.events import CompactionEvent
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_RESPONSE_EVENT_NAME
from zett_agent.extensions.steering import STEERING_MESSAGE_EVENT_NAME
from zett_agent.messages import (
    AnyMessage,
    AssistantMessage,
    ImageBytesSource,
    ImageContent,
    SystemMessage,
    TextContent,
    UserMessage,
)
from zett_agent.model import ReasoningEffort, ToolDefinition

from ...config import ModelConfig, ZettCodeConfig
from ...plugins import UiRow
from ..commands import Command, CommandResult
from .context import ContextReport
from .export import build_trace, render_html, write_export
from .replay import replay
from .runtime import ZettCodeRuntime, build_system_prompt
from .storage import Session, SessionInfo
from .title import summarize_title
from .transcript import Transcript
from .usage import UsageSnapshot

#: One piece of a user turn, in the order it was written: a run of text, or the
#: encoded bytes and media type of an image placed where that run ends.
type PromptPart = str | tuple[bytes, str]


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
            Command("/compact", "summarize the context now", "agent", self._command_compact),
            Command("/export", "write this session to an HTML file: /export [path]", "agent", self._command_export),
        )

    @property
    def plugin_commands(self) -> tuple[Command, ...]:
        """Return the commands the installed plugins registered.

        The shell keeps them after its own commands, so a plugin cannot take
        over a built-in name; plugin-versus-plugin duplicates are rejected when
        the plugins load.
        """
        return self.runtime.plugins.commands

    @property
    def plugin_failures(self) -> tuple[str, ...]:
        """Return one message per plugin that could not be loaded or activated."""
        return self.runtime.plugins.failures

    @property
    def plugin_rows(self) -> tuple[UiRow, ...]:
        """Return the header and status rows plugins asked the shell to draw."""
        return self.runtime.plugins.rows

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
        replayed = replay(
            session,
            renderers=transcript.renderers,
            processors=transcript.processors,
            frame=transcript.frame,
        )
        transcript.replace(replayed.transcript.entries)
        self.runtime.usage.seed(session_id, replayed.usage)
        # The instructions come from a request this process already assembled, or
        # from the prompt the runtime would build; the environment and tool notes
        # only exist inside a request, which the report admits.
        instructions = self.runtime.context.instructions or (
            SystemMessage(content=build_system_prompt(self.runtime.config)),
        )
        self.runtime.context.remember(session_id, [*instructions, *replayed.history])
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

        Raises:
            ValueError: When the newest checkpoint already covers the branch —
                a second pass would summarize nothing but the checkpoint.
        """
        if self._compacted_at_the_head():
            raise ValueError("Already compacted; send a message before compacting again")
        await self.runtime.start()
        return await self.runtime.started.compact(
            config=AgentRunConfig(session_id=self.session_id),
            model=self.runtime.provider,
        )

    def _compacted_at_the_head(self) -> bool:
        """Return whether nothing has been appended since the newest checkpoint.

        Messages and checkpoints both carry ``created_at``, so the last message
        being older than the last checkpoint is what says the branch has not
        moved since it was summarized — no matter which session is active or
        whether the transcript in this process ever showed that compaction.
        """
        try:
            session = self.runtime.persistence.read(self.session_id)
        except ValueError:
            # A runtime without a store to read: no checkpoint can cover it.
            return False
        latest = session.latest_compaction
        if latest is None or session.head_id is None:
            return False
        head = session.message(session.head_id)
        return head is not None and head.created_at <= latest.created_at

    async def _command_new(self, argument: str) -> CommandResult:
        """Start a fresh session."""
        session_id = self.new_session()
        return CommandResult(notification=f"started session {session_id[:8]}")

    async def export_session(self, path: str | Path | None = None) -> Path:
        """Write the active session, and the context it now carries, to HTML.

        The conversation is rendered with the same processors the shell paints,
        and the request the next turn would send is included beside it, so a
        reader sees both the history and what the model is down to.

        Args:
            path: File to write; ``None`` puts ``zettcode-<id8>.html`` in the
                workspace. A relative path is taken from the working directory.

        Returns:
            The absolute path that was written.

        Raises:
            ValueError: When the session has no stored header, so there is
                nothing to export yet.
        """
        session = self.runtime.persistence.read(self.session_id)
        if session.header is None:
            raise ValueError("Nothing to export: this session has not been stored yet")
        report = await self.context_report()
        messages, tools = self._context_request(session)
        trace = build_trace(
            session,
            title=self.session_name,
            subtitle=f"Session {self.session_id} · {self.workspace}",
            meta=self._export_meta(session),
            tags=(self.runtime.active_model.shown_name, self.effort),
            context_messages=messages,
            tools=tuple(tool.name for tool in tools),
            report=report,
        )
        trace = replace(trace, exported_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))
        target = path if path is not None else self.workspace / f"zettcode-{self.session_id[:8]}.html"
        return write_export(target, render_html(trace))

    def _context_request(self, session: Session) -> tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]]:
        """Return the messages and tools the next turn would send.

        The request this process assembled is the honest answer; before one has
        run — a session restored into a fresh process — the instructions and the
        active branch stand in for it, which is all that can be known there.
        """
        assembled = self.runtime.context.assembled(self.session_id)
        if assembled is not None:
            messages, tools = assembled
            return tuple(messages), tuple(tools)
        instructions = self.runtime.context.instructions or (
            SystemMessage(content=build_system_prompt(self.runtime.config)),
        )
        checkpoint, tail = session.active()
        stored: list[AnyMessage] = [checkpoint.message[0]] if checkpoint is not None else []
        stored.extend(line.message[0] for line in tail if line.message[0].include_in_messages)
        return (*(instructions or ()), *stored), self.runtime.context.tools

    def _export_meta(self, session: Session) -> tuple[tuple[str, str], ...]:
        """Return the label/value pairs the exported page's sidebar carries."""
        model = self.runtime.active_model
        return (
            ("Workspace", str(self.workspace)),
            ("Model", f"{model.shown_name} ({model.model})"),
            ("Effort", self.effort),
            ("Created", session.created_at.astimezone().strftime("%Y-%m-%d %H:%M")),
            ("Updated", session.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")),
            ("Messages", f"{session.message_count}"),
        )

    async def _command_export(self, argument: str) -> CommandResult:
        """Write the session and its context to one HTML file.

        The path argument is optional; without it the file lands in the
        workspace, named after the session, and the result says where.
        """
        path = await self.export_session(argument.strip() or None)
        return CommandResult(message=f"Exported to `{path}`")

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

    def steer(self, text: str) -> bool:
        """Queue an urgent user message for the request that is running.

        The agent adopts it at the next model or tool boundary and drops the
        rest of the current task, so the shell offers this only while a turn is
        in flight. Returns whether a running request accepted the message, which
        is what tells the shell it may show the message as queued.

        Args:
            text: What the user typed; blank text is refused without asking the
                agent, and a request that is not running refuses it here.
        """
        if not text.strip():
            return False
        try:
            agent = self.runtime.started.agent
        except RuntimeError:
            return False
        accepted = agent.emit_external_event(
            ExternalEvent(name=STEERING_MESSAGE_EVENT_NAME, payload={"content": text}),
            config=AgentRunConfig(session_id=self.session_id),
        )
        return bool(accepted)

    async def aclose(self) -> None:
        """Release the underlying runtime resources."""
        await self.runtime.aclose()
