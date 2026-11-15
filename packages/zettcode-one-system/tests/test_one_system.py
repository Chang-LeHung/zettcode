"""One system message: what a request's instructions become before a provider sees them."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.events import AgentEventType
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import AssistantMessage, SystemMessage, UserMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from zettcode.one_system import OneSystem
from zettcode.one_system.extension import OneSystemMessage, merge_system


class _Call:
    """Records the request the provider would be handed, and answers with one event."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def __call__(self, request):  # noqa: ANN001, ANN204 - a stand-in for the provider stream
        self.seen.append(request)

        async def stream():
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))

        return stream()


def run(extension: OneSystemMessage, messages: tuple) -> tuple[tuple, Any]:
    """Return the messages the provider receives, and the request itself, through a real call of the hook."""
    call = _Call()
    request = replace(_request(), messages=messages)

    async def go() -> None:
        stream = extension.on_model_request(None, request, call)  # type: ignore[arg-type]
        async for _event in stream:
            pass

    asyncio.run(go())
    return call.seen[0].messages, call.seen[0]


def _request():  # noqa: ANN202 - the parts a merge does not touch are defaults
    from zett_agent.model import ModelRequest

    return ModelRequest(messages=[], tools=[], server_tools=[], reasoning_effort=None)


def test_two_instructions_become_one_in_the_order_they_were_in():
    messages = (
        SystemMessage(content="You are ZettCode."),
        UserMessage(content="hello"),
        SystemMessage(content="The project uses tabs."),
    )

    assert merge_system(messages) == (
        SystemMessage(content="You are ZettCode.\n\nThe project uses tabs."),
        UserMessage(content="hello"),
    )


def test_the_joined_message_sits_where_the_first_one_was():
    messages = (
        UserMessage(content="before"),
        SystemMessage(content="one"),
        UserMessage(content="middle"),
        SystemMessage(content="two"),
    )

    merged = merge_system(messages)

    assert [type(message).__name__ for message in merged] == ["UserMessage", "SystemMessage", "UserMessage"]
    assert merged[1].content == "one\n\ntwo", "the instructions move up to the first of them, not past a message"
    assert merged[0] is messages[0] and merged[2] is messages[2], "everything else is the object it was"


def test_one_instruction_is_handed_on_untouched():
    messages = (SystemMessage(content="only"), UserMessage(content="hi"))

    assert merge_system(messages) is messages, "nothing to join costs nothing, not even a copy"


def test_a_request_without_instructions_is_untouched():
    messages = (UserMessage(content="hi"),)

    assert merge_system(messages) is messages


def test_blank_instructions_are_dropped_rather_than_joined():
    messages = (SystemMessage(content="  \n "), SystemMessage(content="real one"), SystemMessage(content="\t"))

    merged = merge_system(messages)

    assert len(merged) == 1 and merged[0].content == "real one"


def test_a_request_of_nothing_but_blanks_is_left_as_it_was():
    messages = (SystemMessage(content="  "), SystemMessage(content="\n"))

    assert merge_system(messages) is messages


def test_the_first_messages_own_flags_and_attributes_survive():
    messages = (
        SystemMessage(content="kept", include_in_messages=True, persist=False, attributes={"from": "the app"}),
        SystemMessage(content="also kept"),
    )

    merged = merge_system(messages)

    assert isinstance(merged[0], SystemMessage)
    assert merged[0].include_in_messages is True and merged[0].persist is False
    assert merged[0].attributes == {"from": "the app"}
    assert messages[0].content == "kept", "the message the runtime keeps is not rewritten in place"


def test_the_hook_hands_the_provider_one_instruction():
    messages, _ = run(
        OneSystemMessage(), (SystemMessage(content="a"), UserMessage(content="hi"), SystemMessage(content="b"))
    )

    assert [type(message).__name__ for message in messages] == ["SystemMessage", "UserMessage"]
    assert messages[0].content == "a\n\nb"


def test_the_hook_passes_the_same_request_through_when_there_is_nothing_to_join():
    messages, request = run(OneSystemMessage(), (SystemMessage(content="only"), UserMessage(content="hi")))

    assert messages is request.messages, "the request object itself is reused"


@pytest.mark.parametrize("count", [0, 1])
def test_a_request_that_already_has_at_most_one_instruction_is_cheap(count: int):
    given = tuple(SystemMessage(content=f"s{n}") for n in range(count)) + (UserMessage(content="hi"),)

    assert merge_system(given) is given


class _Late(AgentExtension):
    """A part that adds an instruction while the request is being built, the way the harness's guidance does."""

    async def on_model_request(self, context, request, call_next):  # noqa: ANN001
        added = replace(request, messages=[*request.messages, SystemMessage(content="added late")])
        async for event in call_next(added):
            yield event


class _Model:
    """A model that answers once and remembers what each request carried."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def stream(self, request):  # noqa: ANN001
        self.requests.append(request)
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))


async def test_an_instruction_added_to_the_request_itself_is_joined_too():
    """The hook runs innermost: an instruction added while the request is built must not reach the provider alone."""
    model = _Model()
    agent = await Agent.create(
        model,  # type: ignore[arg-type]
        config=AgentRunConfig(session_id="s"),
        extensions=[OneSystemMessage(), _Late()],
    )

    events = [event async for event in agent.stream("hi", config=AgentRunConfig(session_id="s"))]

    assert events[-1].type is AgentEventType.RUN_COMPLETED
    system = [message for message in model.requests[0].messages if isinstance(message, SystemMessage)]
    assert len(system) == 1, "one system message reaches the provider"
    assert "added late" in system[0].content


def test_the_part_says_its_name_and_registers_a_factory():
    from zettcode.engine.plugins import PluginContext  # noqa: F401 - the type of what a plugin is handed

    assert OneSystem.name == "one-system"
    assert "one system message" in OneSystem.description


class _Instructions(AgentExtension):
    """Two instructions of the state's own: one the store keeps, one it does not (the harness's guidance is the second)."""

    async def on_state(self, context) -> None:  # noqa: ANN001
        context.add_message(SystemMessage(content="durable instruction"), index=0)
        context.add_message(SystemMessage(content="ephemeral instruction", persist=False), index=1)


async def stored_texts(tmp_path, extensions) -> list[tuple[str, str]]:
    """Run one turn and return what the store wrote: the kind and text of every message, in order."""
    from zettcode.engine.storage.store import SessionStore

    store = SessionStore(tmp_path / "sessions", workspace=tmp_path)
    agent = await Agent.create(
        _Model(),  # type: ignore[arg-type]
        config=AgentRunConfig(session_id="s"),
        extensions=[_Instructions(), store, *extensions],
    )

    async for _event in agent.stream("hi", config=AgentRunConfig(session_id="s")):
        pass

    session = store.read("s")
    return [(type(line.message[0]).__name__, line.message[0].content) for line in session.messages]


async def test_the_stored_conversation_is_the_same_with_and_without_the_merge(tmp_path):
    """The merge is for the provider only: what the session keeps, and what it leaves out, does not change."""
    plain = await stored_texts(tmp_path / "plain", [])
    merged = await stored_texts(tmp_path / "merged", [OneSystemMessage()])

    assert plain == merged
    assert ("SystemMessage", "ephemeral instruction") not in merged, "a part that asked not to be stored still is not"
    assert ("SystemMessage", "durable instruction") in merged, "and one that asked to be is kept as it was"


async def test_the_provider_sees_one_message_while_the_state_keeps_both(tmp_path):
    """The same turn: one system message at the provider, the two the state holds untouched."""
    from zettcode.engine.storage.store import SessionStore

    store = SessionStore(tmp_path / "sessions", workspace=tmp_path)
    model = _Model()
    state_texts: list[list[str]] = []

    class _Count(AgentExtension):
        priority = 2_000_000

        async def on_model_request(self, context, request, call_next):  # noqa: ANN001
            state_texts.append([m.content for m in context.state.messages if isinstance(m, SystemMessage)])
            async for event in call_next(request):
                yield event

    agent = await Agent.create(
        model,  # type: ignore[arg-type]
        config=AgentRunConfig(session_id="s"),
        extensions=[_Instructions(), store, OneSystemMessage(), _Count()],
    )
    async for _event in agent.stream("hi", config=AgentRunConfig(session_id="s")):
        pass

    seen = model.requests[0].messages
    assert sum(isinstance(m, SystemMessage) for m in seen) == 1, "one at the provider"
    (message,) = [m for m in seen if isinstance(m, SystemMessage)]
    assert "durable instruction" in message.content and "ephemeral instruction" in message.content
    # The state the request was built from is untouched: the framework's own instruction and both of ours.
    assert "durable instruction" in state_texts[0] and "ephemeral instruction" in state_texts[0]
    assert len([line for line in store.read("s").messages if isinstance(line.message[0], SystemMessage)]) == 2


async def test_a_part_that_ties_with_the_framework_plan_mode_still_runs_after_it():
    """A tie is broken by registration order, so the hook has to sit above 1_000_000 (plan mode) to be innermost."""
    model = _Model()

    class _PlanLike(AgentExtension):
        priority = 1_000_000

        async def on_model_request(self, context, request, call_next):  # noqa: ANN001
            added = replace(request, messages=[*request.messages, SystemMessage(content="plan mode note")])
            async for event in call_next(added):
                yield event

    # Registered after ours, which is the order that would win a tie.
    agent = await Agent.create(
        model,  # type: ignore[arg-type]
        config=AgentRunConfig(session_id="s"),
        extensions=[OneSystemMessage(), _PlanLike()],
    )
    async for _event in agent.stream("hi", config=AgentRunConfig(session_id="s")):
        pass

    system = [m for m in model.requests[0].messages if isinstance(m, SystemMessage)]
    assert len(system) == 1 and "plan mode note" in system[0].content
