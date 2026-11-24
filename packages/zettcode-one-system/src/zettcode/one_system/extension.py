"""The hook that turns a request's instructions into one system message, and stops there.

A request reaches the provider with several system messages: the agent's own prompt, the working directory, the
project's instructions, skills, MCP notices, and whatever guidance an extension added for this request. Every one of
them is an instruction, and every provider has its own way of taking them: the Anthropic-compatible one collects them
and joins them with a blank line, an OpenAI-compatible one sends a message per entry, and an endpoint that accepts a
single system message refuses the rest.

Joining them here makes the shape the same everywhere, and does it on the text the model was going to read anyway: the
parts are concatenated in the order they were already in, separated by a blank line, and the result sits in the first
instruction slot, where the first system message was. Nothing that has text is dropped, and a request that already has
one system message is handed on untouched. What the parts carried comes along: the joined message inherits the
attributes of every part that had text, and sets both flags — stored, replayed — only when every part agreed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from typing import Any

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension, ModelRequestNext
from zett_agent.messages import AnyMessage, SystemMessage
from zett_agent.model import ModelEvent, ModelRequest

__all__ = ["OneSystemMessage", "merge_system"]


def merge_system(messages: Sequence[AnyMessage]) -> Sequence[AnyMessage]:
    """Return ``messages`` with every system message joined into the first one's place.

    The joined message inherits what every part carried, not only the first one's — and only from the parts that had
    text: a blank instruction contributes nothing, neither text nor attributes nor flags.

    ``attributes`` are merged flat, a key two parts set keeping the earliest part's value; a nested mapping under one
    key is replaced, not combined. The direction is deliberate: a key in here names where a block came from, so the
    part that wrote it first keeps it, and no later part relabels a message that now speaks with everyone's words.
    Every key survives, so the joined message carries the markers of parts its text is not limited to — nothing may
    read one as naming the whole message. That is a rule for whoever adds an extension, not a property of the merge:
    the framework marks its own instructions with ``jit_harness:guidance`` and ``tool_guidelines``, and its harness,
    when it wants guidance, drops request system messages carrying either, so an attribute filter has to keep running
    before this hook. The harness does, at ``900_000``: below the ``1_000_001`` this extension takes, and held there by
    a test rather than by a version number someone remembers.

    Both flags hold only when every part agreed: true when every part said so and false when one did not. Replay is
    why that is the safe direction — the parts are rebuilt into every request, so a joined block replayed because one
    part asked for it would put the system prompt, the project's instructions and the working directory at the head of
    every later request a second time, and break the provider's prefix cache from there on. Storing is the same
    argument from the other side: a stored block would hold the text of a part that asked not to be stored.

    A request with fewer than two system messages, or with nothing but blank text between them, is returned as it was —
    the same object, so a caller can tell that nothing was joined without comparing contents.

    Args:
        messages: The request's messages, in the order the provider would see them.

    Returns:
        The messages with one :class:`~zett_agent.messages.SystemMessage` where the first one was, or ``messages``
        itself when there was nothing to join.
    """
    found = [(index, message) for index, message in enumerate(messages) if isinstance(message, SystemMessage)]
    if len(found) < 2:
        return messages
    parts = [message for _index, message in found if message.content.strip()]
    if not parts:
        return messages
    # The slot is the first system message's, blank or not — not the first part's, which would put an instruction behind
    # a question. What the base carries is not inherited either: every field is set below, and a field a later version of
    # the message adds has to be set here too, or it comes from the message whose slot this is — a blank one, in the case
    # this exists for. `dataclasses.replace` gives a new message, so the parts the runtime holds are left as they were.
    where, first_message = found[0]
    merged = replace(
        first_message,
        content="\n\n".join(message.content.strip() for message in parts),
        attributes=_inherited_attributes(parts),
        persist=all(part.persist for part in parts),
        include_in_messages=all(part.include_in_messages for part in parts),
    )
    removed = {index for index, _message in found}
    kept = [message for index, message in enumerate(messages) if index not in removed]
    # Every removed place is at or after the first, so the first's index still counts among the ones that remain.
    kept.insert(where, merged)
    return tuple(kept)


def _inherited_attributes(parts: Sequence[SystemMessage]) -> dict[str, Any]:
    """Return every part's attributes, the earliest part's value winning a key two of them set."""
    inherited: dict[str, Any] = {}
    for part in parts:
        # The map collected so far is spread last, so the value an earlier part set survives this one's.
        inherited = {**part.attributes, **inherited}
    return inherited


class OneSystemMessage(AgentExtension):
    """Join a request's system messages into one, just before the provider is handed the request.

    The priority is above every number the framework's own extensions claim today, so that this runs innermost among
    them: a part that adds an instruction while the request is being built — the harness's guidance, for one — has
    already been added by the time this sees the request, and none is left behind to reach the provider on its own. A
    caller may still register above it; the number is a claim about the framework's, not about everyone's.
    """

    #: Innermost among the framework's own: the JIT harness runs at 900_000 and does add a system message while the
    #: request is being built, so this has to clear that. It also clears 1_000_000, the highest number the framework
    #: claims today — a margin rather than a requirement, since whoever holds it cannot nest inside anything: plan mode
    #: changes the state's instructions in `before_model` and never wraps the request. Strictly above, because a tie
    #: goes to registration order.
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
