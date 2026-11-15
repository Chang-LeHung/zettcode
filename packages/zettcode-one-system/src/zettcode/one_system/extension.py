"""The hook that turns a request's instructions into one system message, and stops there.

A request reaches the provider with several system messages: the agent's own prompt, the working directory, the
project's instructions, skills, MCP notices, and whatever guidance an extension added for this request. Every one of
them is an instruction, and every provider has its own way of taking them: the Anthropic-compatible one collects them
and joins them with a blank line, an OpenAI-compatible one sends a message per entry, and an endpoint that accepts a
single system message refuses the rest.

Joining them here makes the shape the same everywhere, and does it on the text the model was going to read anyway: the
parts are concatenated in the order they were already in, separated by a blank line, and the result sits where the first
one was. Nothing is reordered past a conversation message, nothing is dropped, and a request that already has one
system message is handed on untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension, ModelRequestNext
from zett_agent.messages import AnyMessage, SystemMessage
from zett_agent.model import ModelEvent, ModelRequest

__all__ = ["OneSystemMessage", "merge_system"]


def merge_system(messages: Sequence[AnyMessage]) -> Sequence[AnyMessage]:
    """Return ``messages`` with every system message joined into the first one's place.

    A request with fewer than two system messages, or with nothing but blank text between them, is returned as it was —
    the same object, so a caller can tell the two cases apart without comparing contents.

    Args:
        messages: The request's messages, in the order the provider would see them.

    Returns:
        The messages with one :class:`~zett_agent.messages.SystemMessage` where the first one was, or ``messages``
        itself when there was nothing to join.
    """
    found = [(index, message) for index, message in enumerate(messages) if isinstance(message, SystemMessage)]
    if len(found) < 2:
        return messages
    joined = "\n\n".join(message.content.strip() for _index, message in found if message.content.strip())
    if not joined:
        return messages
    # The first message's own flags and attributes are kept: only its text changes. `dataclasses.replace` gives a
    # new message, so the one the runtime holds for later requests is left as it was.
    where, first_message = found[0]
    merged = replace(first_message, content=joined)
    removed = {index for index, _message in found}
    kept = [message for index, message in enumerate(messages) if index not in removed]
    # Every removed place is at or after the first, so the first's index still counts among the ones that remain.
    kept.insert(where, merged)
    return tuple(kept)


class OneSystemMessage(AgentExtension):
    """Join a request's system messages into one, just before the provider is handed the request.

    The priority is higher than any other extension's so that this runs innermost: a part that adds an instruction while
    the request is being built — the harness's guidance, for one — has already been added by the time this sees the
    request, and none is left behind to reach the provider on its own.
    """

    #: Innermost: the last extension to change the request, and the one closest to the provider. It has to clear the
    #: two the framework itself runs late — the JIT harness's guidance at 900_000 and plan mode at 1_000_000 — because
    #: both add a system message while the request is being built, and a tie is broken by registration order.
    priority = 1_000_001

    async def on_model_request(
        self, context: AgentRunContext, request: ModelRequest, call_next: ModelRequestNext
    ) -> AsyncIterator[ModelEvent]:
        """Hand the provider one system message, or the very request it was given when there is nothing to join."""
        merged = merge_system(request.messages)
        if merged is request.messages:
            async for event in call_next(request):
                yield event
            return
        async for event in call_next(replace(request, messages=merged)):
            yield event
