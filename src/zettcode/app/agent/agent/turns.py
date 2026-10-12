"""Running a turn: building the message, streaming the agent's events, and steering one in flight."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace

from zett_agent.agent import AgentRunConfig
from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.steering import STEERING_MESSAGE_EVENT_NAME
from zett_agent.messages import ImageBytesSource, ImageContent, TextContent, UserMessage

from ..dialogue.side import SIDE, question
from .base import AgentBase
from .prompt import MentionPart, PromptPart, carries_image, plain_text, plain_text_part


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
        """
        await self.runtime.start()
        client = self.runtime.started
        used = self.runtime.active_model.shown_name
        session_id = self.session_id
        try:
            async for event in client.stream(
                self.request(parts, hint=hint, side=side),
                config=AgentRunConfig(session_id=session_id),
                model=self.runtime.provider,
                reasoning_effort=self.runtime.effort,
            ):
                yield event
        finally:
            if not side:
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
            return UserMessage(content=f"{text}\n\n{hint}", attributes={"prompt": text})
        content: list[TextContent | ImageContent] = []
        for part in parts:
            if isinstance(part, (str, MentionPart)):
                text = plain_text_part(part)
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
        progress = self.runtime.todos.todos(self.session_id)
        return tuple((item.status.value, item.content) for item in progress.todos) if progress else ()

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
