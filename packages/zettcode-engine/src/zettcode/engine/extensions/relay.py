"""What a child agent has to say to the person: the shell approvals it cannot decide for itself.

A subagent runs in its own session, and nothing watches its event stream, so a command that needs approval would be
put to nobody and wait for ever. That one kind of event is handed to the parent run instead, which is the one the
person is watching. It goes out under the parent's session id, because the parent's stream refuses an event that
belongs to another session, but the payload still names the child's session and the tool call: the shell and the SDK
answer with those, the answer is routed to the extension that is waiting for it (the same instance serves parent and
child), and the child's tool call carries on. Everything else a child does stays in its own log.

A question (``ask_user``) is deliberately not relayed: a child does not have that tool, because a child works until it
has finished and a question put to the person in the middle of it would be a conversation the person never started.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing
from typing import cast

from zett_agent.agent import Agent, AgentRunConfig, AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.json_types import JsonValue
from zett_agent.messages import UserMessage
from zett_agent.model import AgentModel, ReasoningEffort

#: The one extension event a person has to see to let a child go on.
RELAYED = frozenset({SHELL_APPROVAL_EVENT_NAME})

#: Where one such event is sent.
Relay = Callable[[AgentEvent], Awaitable[None]]


def relay_to(parent: AgentRunContext) -> Relay:
    """Return the function that hands a child's event to ``parent``'s run, under the parent's session id."""

    async def relay(event: AgentEvent) -> None:
        await parent.emit(
            AgentEvent(
                AgentEventType.CUSTOM,
                parent.session_id,
                tool_calls=list(event.tool_calls),
                name=event.name,
                payload=dict(event.payload or {}),
            )
        )

    return relay


class RelayingAgent(Agent):
    """An agent that passes the events a person has to answer to :attr:`relay` as they are emitted.

    Attributes:
        relay: Where such an event goes; ``None`` drops them, as an agent nobody watches does.
    """

    relay: Relay | None = None

    async def stream(
        self,
        message: UserMessage | str,
        *,
        config: AgentRunConfig | None = None,
        model: AgentModel | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        parallel_tool_call: bool | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
        tags: Mapping[str, JsonValue] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream one run, relaying approvals and questions on the way; the events themselves are unchanged."""
        # ``Agent.stream`` is declared as an iterator and is an async generator: closing it is what stops the run
        # underneath when the caller stops reading.
        events = cast(
            AsyncGenerator[AgentEvent, None],
            super().stream(
                message,
                config=config,
                model=model,
                reasoning_effort=reasoning_effort,
                parallel_tool_call=parallel_tool_call,
                metadata=metadata,
                tags=tags,
            ),
        )
        async with aclosing(events):
            async for event in events:
                if self.relay is not None and event.type is AgentEventType.CUSTOM and event.name in RELAYED:
                    await self.relay(event)
                yield event


__all__ = ["RELAYED", "Relay", "RelayingAgent", "relay_to"]
