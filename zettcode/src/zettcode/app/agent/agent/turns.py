"""Running a turn: building the message, streaming the agent's events, and steering one in flight."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import replace
from typing import cast

from zett_agent.agent import AgentRunConfig
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.exceptions import AgentResumeError
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.steering import STEERING_MESSAGE_EVENT_NAME
from zett_agent.messages import ImageBytesSource, ImageContent, TextContent, UserMessage
from zett_agent.resume import ResumePoint

from zettcode.engine.relay import Relayed

from ..dialogue.side import SIDE, question
from .base import AgentBase
from .prompt import MentionPart, PromptPart, carries_image, model_text_part, plain_text


class TurnsMixin(AgentBase):
    """Turn the reader's parts into a request, stream what comes back, and steer it."""

    def set_event_dispatcher(self, dispatcher: AgentEventDispatcher) -> None:
        """Send streamed agent events to the application's transcript projector."""
        self.runtime.set_event_dispatcher(dispatcher)

    async def stream(
        self,
        parts: Sequence[PromptPart],
        *,
        hint: str | None = None,
        side: bool = False,
        relayed: Relayed | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn with the selected session, model, and reasoning effort.

        Args:
            parts: The user turn in the order it was written: text runs and the
                images the composer interleaved with them. A turn without
                images is simply one text part.
            hint: Text appended after the turn, for the instructions a ``@``
                reference contributes. The text the user typed then rides along
                as the message's ``prompt`` attribute, so the stored message is
                what was typed and a restored session shows it.
            side: Ask without letting the exchange join the conversation; see
                :mod:`zettcode.app.agent.side`.
            relayed: The turn is a message another session sent. It is what the model reads
                (with where it came from), and ``parts`` and ``hint`` are not used.

        Raises:
            SessionLocked: Another process has the session open. Checked before anything else, and a side
                question is no exception: the store records it even though it never replays it.
        """
        self.require_session()
        await self.runtime.start()
        client = self.runtime.started
        used = self.runtime.active_model.shown_name
        session_id = self.session_id
        try:
            # Closed here, not left to the garbage collector: a consumer that stops early (a `break`, `aclose()`)
            # throws GeneratorExit in at the `yield`, and the library's stream must unwind then, or the agent is
            # left in its "generating" phase and refuses the next request.
            async with aclosing(
                cast(
                    "AsyncGenerator[AgentEvent]",
                    client.stream(
                        self.request(parts, hint=hint, side=side) if relayed is None else relayed.message(),
                        config=AgentRunConfig(session_id=session_id),
                        model=self.runtime.provider,
                        reasoning_effort=self.runtime.effort,
                    ),
                )
            ) as events:
                async for event in events:
                    yield event
        finally:
            if not side:
                self._remember_model(session_id, used)

    async def resume_point(self) -> ResumePoint | None:
        """Report where the active session was interrupted, or ``None`` when there is nothing to pick up.

        Nothing is written and no model is called. A session another process has open is refused, as a turn is.

        Raises:
            SessionLocked: Another process has the session open.
        """
        self.require_session()
        await self.runtime.start()
        return await self.runtime.started.resume_point(
            config=AgentRunConfig(session_id=self.session_id), model=self.runtime.provider
        )

    async def resume_blocker(self) -> str | None:
        """Say why the active session cannot be picked up, in the library's own words; ``None`` when it can.

        :meth:`resume_point` answers only that there is none. The reason is one the reader can act on — a finished
        request, a refusal that would be declined again, a context window that is full — and the library says it when
        a resume is asked for, so it is asked for here and stopped before it starts.
        """
        self.require_session()
        await self.runtime.start()
        stream = self.runtime.started.stream_resume(
            config=AgentRunConfig(session_id=self.session_id), model=self.runtime.provider
        )
        try:
            async for _event in stream:
                return None  # it can be resumed after all; the first event is as far as this looks
        except AgentResumeError as error:
            return str(error)
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        return None

    async def stream_resume(self) -> AsyncIterator[AgentEvent]:
        """Pick the interrupted request up where it stopped, with the model and effort the next turn would use.

        The library takes none of these from the session, so the same ones a turn would carry are given.

        Raises:
            SessionLocked: Another process has the session open.
            AgentResumeError: There is nothing to pick up; :meth:`resume_point` says whether there is.
        """
        self.require_session()
        await self.runtime.start()
        client = self.runtime.started
        used = self.runtime.active_model.shown_name
        session_id = self.session_id
        try:
            async with aclosing(
                cast(
                    "AsyncGenerator[AgentEvent]",
                    client.stream_resume(
                        config=AgentRunConfig(session_id=session_id),
                        model=self.runtime.provider,
                        reasoning_effort=self.runtime.effort,
                    ),
                )
            ) as events:
                async for event in events:
                    yield event
        finally:
            self._remember_model(session_id, used)

    def _remember_model(self, session_id: str, model: str) -> None:
        """Record the model a turn used in its session, so resuming the session starts on it.

        Done when the turn ends, however it ends — a stopped or failed turn used the model too —
        and not before it, because a session's folder does not exist until its first message is
        written. A side question is not part of the conversation and records nothing. Metadata is
        never worth failing a conversation for, so a store that cannot be written or read here is
        passed over; the next turn tries again.
        """
        try:
            self.runtime.persistence.set_model(session_id, model)
        except (OSError, ValueError):
            pass

    @staticmethod
    def request(parts: Sequence[PromptPart], *, hint: str | None = None, side: bool = False) -> str | UserMessage:
        """Return the user turn those ordered parts make up.

        Text and images keep the order they were written in inside one
        ``UserMessage``, so a picture is read where its writer placed it rather
        than after the whole prompt. A turn with no image stays a plain string.
        ``hint`` is appended last — as a trailing part when an image is in the
        turn — and the typed text then rides along as the message's ``prompt``
        attribute, so storage and a restored session keep it.

        Args:
            parts: The turn in the order it was written.
            hint: Instructions a ``@`` reference contributes.
            side: Mark the turn as a side question, which the store records but
                never replays.
        """
        message = TurnsMixin.turn(parts, hint=hint)
        if not side:
            return message
        if isinstance(message, UserMessage):
            return replace(message, attributes={**message.attributes, SIDE: True}, include_in_messages=False)
        return question(message)

    @staticmethod
    def turn(parts: Sequence[PromptPart], *, hint: str | None = None) -> str | UserMessage:
        """Return the message those parts make up, before any side marking."""
        if not carries_image(parts):
            text = plain_text(parts)
            if hint is None:
                return text
            said = "".join(model_text_part(part) for part in parts)
            return UserMessage(content=f"{said}\n\n{hint}", attributes={"prompt": text})
        content: list[TextContent | ImageContent] = []
        for part in parts:
            if isinstance(part, (str, MentionPart)):
                text = model_text_part(part)
                if text:
                    content.append(TextContent(text))
                continue
            data, media_type = part
            content.append(ImageContent(source=ImageBytesSource(data=data, media_type=media_type)))
        if hint is not None:
            content.append(TextContent(hint))
        message = UserMessage(content=content)
        if hint is not None:
            message.attributes["prompt"] = plain_text(parts)
        return message

    def tasks(self) -> tuple[tuple[str, str], ...]:
        """Return the current session's plan as display-ready status/content pairs."""
        todos = self.runtime.todos
        progress = todos.todos(self.session_id) if todos is not None else None
        return tuple((item.status.value, item.content) for item in progress.todos) if progress else ()

    def steer(self, message: str | UserMessage) -> bool:
        """Queue an urgent user message for the request that is running.

        The agent adopts it at the next model or tool boundary and drops the
        rest of the current task, so the shell offers this only while a turn is
        in flight. Returns whether a running request accepted the message, which
        is what tells the shell it may show the message as queued.

        Args:
            message: What the user typed, as text, or as a message when it carries
                pictures (see :meth:`turn`): zett-agent's steering inbox takes either.
                An empty one is refused without asking the agent, and a request that
                is not running refuses it here.
        """
        if isinstance(message, str):
            if not message.strip():
                return False
            payload: dict[str, object] = {"content": message}
        else:
            if not message.text.strip() and not message.parts:
                return False
            payload = {"message": message}
        try:
            agent = self.runtime.started.agent
        except RuntimeError:
            return False
        accepted = agent.emit_external_event(
            ExternalEvent(name=STEERING_MESSAGE_EVENT_NAME, payload=payload),
            config=AgentRunConfig(session_id=self.session_id),
        )
        return bool(accepted)
