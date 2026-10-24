"""The messenger and the two tools the model reaches the other sessions with."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.messages import SystemMessage

from broker_helpers import Host, Inbox, client_for, eventually, session
from zettcode.app.agent.dialogue.side import SideQuestions, question
from zettcode.app.agent.extensions.messaging import (
    LIST_SESSIONS_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    SessionMessagingExtension,
)
from zettcode.broker.client import BrokerClient, Receipt, SendError
from zettcode.broker.protocol import MAX_HOPS, MAX_TEXT
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.engine.messenger import Messenger
from zettcode.engine.relay import Relayed

ME = "01a10b75-aaaa-7000-8000-000000000001"
BOB = "02b20c86-bbbb-7000-8000-000000000002"
CAL = "03c30d97-cccc-7000-8000-000000000003"


@pytest.fixture
async def host(tmp_path: Path):
    server = Host(tmp_path)
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def world(host: Host):
    """This session's messenger, and a way to bring other sessions up beside it."""
    closers: list[BrokerClient] = []
    me = Messenger(client_for(host.directory), workspace="/work/me")
    me.describe(ME, "My session", busy=False)
    await me.start()
    assert await me.client.wait_connected(3)

    async def other(session_id: str, title: str, *, inbox: Inbox | None = None, status: str = "idle"):
        inbox = inbox or Inbox()
        client = client_for(host.directory, on_message=inbox)
        client.set_session(session(session_id, title, status))
        closers.append(client)
        await client.start()
        assert await client.wait_connected(3)
        await eventually(lambda: any(e.session_id == session_id for e in me.peers()), 3)
        return client, inbox

    me.other = other  # type: ignore[attr-defined]
    yield me
    await me.close()
    for client in closers:
        await client.close()


def context() -> AgentRunContext:
    state = AgentState()
    state._messages.append(SystemMessage(content="instructions"))
    return AgentRunContext(AgentRunConfig(session_id="s1"), state, {})


async def tools_of(messenger: Messenger):
    ctx = context()
    await SessionMessagingExtension(messenger).on_tool(ctx)
    return ctx


async def call(ctx, name: str, **arguments):
    return await ctx.tools[name].handler(**arguments)


# -- the tools themselves ------------------------------------------------------------------------------


async def test_both_tools_are_registered_with_what_a_model_needs_to_use_them(world):
    ctx = await tools_of(world)

    assert set(ctx.tools) == {LIST_SESSIONS_TOOL_NAME, SEND_MESSAGE_TOOL_NAME}
    send = ctx.tools[SEND_MESSAGE_TOOL_NAME]
    assert send.parameters["required"] == ["to", "message"]
    assert "cannot see this conversation" in send.parameters["properties"]["message"]["description"]
    assert any("stands on its own" in g for g in send.guidelines)
    assert ctx.tools[LIST_SESSIONS_TOOL_NAME].parameters["properties"] == {}


async def test_the_list_says_who_is_running_with_the_name_to_use_and_the_id(world):
    await world.other(BOB, "Fix the parser")
    await world.other(CAL, "", status="working")
    ctx = await tools_of(world)

    text = await call(ctx, LIST_SESSIONS_TOOL_NAME)

    assert text.splitlines()[0] == "2 other sessions:"
    assert f'- fix-the-parser (id {BOB}) "Fix the parser", idle, in /work' in text
    assert f"(id {CAL}) untitled, working, in /work" in text
    assert "My session" not in text, "this session is not among the others"


async def test_the_list_says_so_when_nobody_else_is_running(world):
    ctx = await tools_of(world)

    assert await call(ctx, LIST_SESSIONS_TOOL_NAME) == "No other ZettCode session is running."


async def test_the_list_says_the_broker_is_not_running_when_it_is_not(host):
    await host.stop()
    offline = Messenger(client_for(host.directory))
    ctx = await tools_of(offline)

    text = await call(ctx, LIST_SESSIONS_TOOL_NAME)

    assert "broker is not running" in text


async def test_a_message_is_delivered_and_the_model_is_told_what_the_other_session_will_do(world):
    _, inbox = await world.other(BOB, "bob")
    ctx = await tools_of(world)

    said = await call(ctx, SEND_MESSAGE_TOOL_NAME, to=BOB, message="rerun the tests please")

    assert said == f"Delivered to bob (id {BOB}); it started on it now."
    (message,) = inbox.messages
    assert (message.text, message.via, message.hops, message.sender.session_id) == (
        "rerun the tests please",
        "agent",
        1,
        ME,
    )


async def test_a_session_that_queued_the_message_says_so_to_the_model(world):
    await world.other(BOB, "bob", inbox=Inbox(Receipt(True, "", "queued")))
    ctx = await tools_of(world)

    said = await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="when you can")

    assert "queued it until its current request ends" in said


@pytest.mark.parametrize("address", [BOB, BOB[:8], "bob-builder", "Bob Builder"])
async def test_a_session_can_be_addressed_by_id_prefix_name_or_title(world, address):
    _, inbox = await world.other(BOB, "Bob Builder")
    ctx = await tools_of(world)

    await call(ctx, SEND_MESSAGE_TOOL_NAME, to=address, message="hello")

    assert inbox.messages[-1].text == "hello"


async def test_a_session_that_is_not_there_is_an_error_the_model_can_act_on(world):
    ctx = await tools_of(world)

    with pytest.raises(ValueError) as failure:
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="nobody", message="hello")

    assert "list_sessions" in str(failure.value)


async def test_a_message_to_oneself_is_an_error_that_says_so(world):
    ctx = await tools_of(world)

    with pytest.raises(ValueError) as failure:
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to=ME, message="hello")

    assert "this session" in str(failure.value)


async def test_a_name_two_sessions_share_is_ambiguous_and_the_model_is_told_to_use_the_id(world):
    await world.other(BOB, "Parser work")
    await world.other(CAL, "Parser Work")
    ctx = await tools_of(world)

    with pytest.raises(ValueError) as failure:
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="Parser work", message="hello")

    assert "session id" in str(failure.value)


async def test_a_refusal_reaches_the_model_with_the_other_sessions_own_reason(world):
    await world.other(BOB, "bob", inbox=Inbox(Receipt(False, "bob has 16 messages waiting")))
    ctx = await tools_of(world)

    with pytest.raises(ValueError, match="16 messages waiting"):
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="hello")


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
async def test_an_empty_message_is_refused_before_anything_is_sent(world, message):
    _, inbox = await world.other(BOB, "bob")
    ctx = await tools_of(world)

    with pytest.raises(ValueError):
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message=message)

    assert inbox.messages == []


async def test_a_message_over_the_limit_is_refused_and_one_at_the_limit_is_not(world):
    _, inbox = await world.other(BOB, "bob")
    ctx = await tools_of(world)

    await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="x" * MAX_TEXT)
    with pytest.raises(ValueError, match="limited to"):
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="x" * (MAX_TEXT + 1))

    assert len(inbox.messages) == 1


async def test_with_no_broker_a_send_says_so_plainly(host):
    await host.stop()
    offline = Messenger(client_for(host.directory))
    ctx = await tools_of(offline)

    with pytest.raises(ValueError, match="broker is not running"):
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="hello")


async def test_a_side_question_keeps_the_listing_and_loses_the_sending(world):
    ctx = await tools_of(world)
    ctx.input_message = question("who else is running?")

    await SideQuestions().before_turn(ctx)

    assert set(ctx.tools) == {LIST_SESSIONS_TOOL_NAME, "glob", "grep"}


# -- hops: what keeps two agents from answering each other for ever ------------------------------------


async def test_a_reply_to_a_message_carries_its_hops_so_a_conversation_between_agents_ends(world):
    bob, inbox = await world.other(BOB, "bob")
    ctx = await tools_of(world)
    world.answering = Relayed(BOB, "bob", "question", hops=MAX_HOPS - 1)

    await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="reply")  # hop MAX_HOPS: allowed
    world.answering = Relayed(BOB, "bob", "question", hops=MAX_HOPS)
    with pytest.raises(ValueError) as failure:
        await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="reply to the reply")

    assert inbox.messages[-1].hops == MAX_HOPS
    assert "stop replying" in str(failure.value)


async def test_a_message_sent_with_nothing_being_answered_starts_the_count_over(world):
    _, inbox = await world.other(BOB, "bob")
    ctx = await tools_of(world)
    world.answering = None

    await call(ctx, SEND_MESSAGE_TOOL_NAME, to="bob", message="fresh")

    assert inbox.messages[-1].hops == 1


async def test_what_a_reader_sends_is_never_counted_against_the_chain(world):
    _, inbox = await world.other(BOB, "bob")
    world.answering = Relayed(BOB, "bob", "question", hops=MAX_HOPS)

    await world.send(BOB, "typed by the reader", via="user")

    assert inbox.messages[-1].hops == 1 and inbox.messages[-1].via == "user"


async def test_two_agents_that_keep_answering_each_other_are_stopped_by_the_broker(host):
    """The whole loop, with the two shells' real wiring: each answer carries on the count."""
    a = Messenger(client_for(host.directory))
    b = Messenger(client_for(host.directory))
    a.describe(ME, "a", busy=False)
    b.describe(BOB, "b", busy=False)
    seen: list[int] = []
    stopped: list[str] = []

    def answer(me: Messenger, to: str):
        def receiver(relayed: Relayed) -> Receipt:
            seen.append(relayed.hops)
            me.answering = relayed

            async def reply() -> None:
                try:
                    await me.send(to, "and again")
                except SendError as error:
                    stopped.append(error.reason)

            asyncio.ensure_future(reply())
            return Receipt(True, "", "started")

        return receiver

    a.receiver, b.receiver = answer(a, BOB), answer(b, ME)
    await a.start()
    await b.start()
    try:
        assert await a.client.wait_connected(3) and await b.client.wait_connected(3)
        await eventually(lambda: a.peers() and b.peers(), 3)
        await a.send(BOB, "start", via="user")
        await eventually(lambda: stopped, 5)

        assert stopped == ["loop"]
        assert seen == list(range(1, MAX_HOPS + 1))
    finally:
        await a.close()
        await b.close()


# -- the messenger ---------------------------------------------------------------------------------------


async def test_describing_the_same_session_twice_tells_the_broker_once(host):
    pushes: list[object] = []
    messenger = Messenger(client_for(host.directory))
    original = messenger.client.set_session
    messenger.client.set_session = lambda info: (pushes.append(info), original(info))[1]  # type: ignore[method-assign]

    messenger.describe(ME, "title", busy=False)
    messenger.describe(ME, "title", busy=False)
    messenger.describe(ME, "title", busy=True)
    messenger.describe(ME, None, busy=True)
    messenger.describe(ME, "", busy=True)

    assert [(p.title, p.status) for p in pushes] == [("title", "idle"), ("title", "working"), ("", "working")]


async def test_a_message_when_nothing_has_taken_the_receiver_is_refused_not_lost_silently(world):
    bob, _ = await world.other(BOB, "bob")
    world.receiver = None

    with pytest.raises(SendError, match="not taking messages yet"):
        await bob.send(ME, "hello")


async def test_a_receiver_that_raises_is_a_refusal_not_a_crash_of_the_connection(world):
    bob, _ = await world.other(BOB, "bob")

    def broken(relayed: Relayed) -> Receipt:
        raise RuntimeError("bug")

    world.receiver = broken

    with pytest.raises(SendError):
        await bob.send(ME, "hello")
    assert world.connected


async def test_closing_leaves_the_broker_and_forgets_the_receiver_and_can_be_done_twice(world, host):
    await world.close()
    await world.close()

    assert world.receiver is None and not world.started
    await eventually(lambda: not any(e.session_id == ME for e in host.broker.roster.entries()), 3)


def test_the_configuration_decides_whether_there_is_a_messenger(tmp_path):
    models = (ModelConfig(model="m", token="t"),)
    on = ZettCodeConfig(workspace=tmp_path, models=models)
    off = ZettCodeConfig(workspace=tmp_path, models=models, sessions_enabled=False)

    assert isinstance(Messenger.create(on), Messenger)
    assert Messenger.create(off) is None


def test_the_sessions_table_is_read_and_is_on_by_default(tmp_path):
    def load(text: str):
        path = tmp_path / "config.toml"
        path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n' + text, encoding="utf-8")
        return load_config(tmp_path, path=path)

    assert load("").sessions_enabled is True
    assert load("[sessions]\nenabled = false\n").sessions_enabled is False
    with pytest.raises(ValueError, match="enabled"):
        load('[sessions]\nenabled = "no"\n')
    with pytest.raises(ValueError, match="nobody"):
        load("[sessions]\nnobody = 1\n")


# -- how the runtime hands the tools to the agent ----------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
async def test_the_runtime_gives_the_agent_the_tools_only_when_the_configuration_asks_for_them(
    tmp_path, monkeypatch, enabled
):
    from test_runtime_models import _config_with
    from zettcode.app.agent import runtime as runtime_module

    given: list[object] = []

    async def fake_create_agent(model, **kwargs):
        given.extend(kwargs["extensions"])
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path, sessions_enabled=enabled))
    assert (runtime.messenger is not None) is enabled
    await runtime.start()
    try:
        extension = [e for e in given if isinstance(e, SessionMessagingExtension)]
        assert bool(extension) is enabled
        if enabled:
            assert extension[0].messenger is runtime.messenger
    finally:
        await runtime.aclose()
