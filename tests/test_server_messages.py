"""Messages from other sessions: held for this chat, then answered as a turn of its own."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from server_fakes import FakeClient, FakeRun
from zettcode.sdk.events import Steered, TextDelta
from zettcode.sdk.types import IncomingMessage
from zettcode.server.app import create_app
from zettcode.server.settings import Settings


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    """Run the application's lifespan and hand back a client that speaks to it in-process, plus the app."""
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, app


def message(text: str = "run the tests", sender: str = "api", **more: object) -> IncomingMessage:
    return IncomingMessage(sender_id=f"session-{sender}", sender=sender, text=text, via="agent", hops=1, **more)


async def until(check, timeout: float = 3.0) -> None:
    """Wait until ``check`` is true, or fail rather than hanging on a run that never started."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the run did not start")
        await asyncio.sleep(0.01)


async def test_a_steer_message_goes_into_the_run_that_is_going_and_waits_nowhere():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(client) as (http, app):
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)

        receipt = app.state.runner.received(message("change course"))

        assert receipt.accepted and receipt.disposition == "steered"
        assert (await http.get("/messages")).json() == {"messages": []}
        steered = client.session.steered[-1]
        assert "change course" in steered and "Another ZettCode session" in steered, "the model reads who sent it"

        await http.post("/runs/cancel")
        await first


async def test_a_steer_the_run_never_read_goes_back_to_the_inbox():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(client) as (http, app):
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        app.state.runner.received(message("never read"))

        await http.post("/runs/cancel")
        await first
        waiting = (await http.get("/messages")).json()["messages"]

    assert [item["text"] for item in waiting] == ["never read"]


async def test_a_follow_up_message_waits_while_a_run_is_going():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(client) as (http, app):
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)

        receipt = app.state.runner.received(message("after this", mode="followup"))

        assert receipt.accepted and receipt.disposition == "queued"
        assert client.session.steered == []
        assert [item["text"] for item in (await http.get("/messages")).json()["messages"]] == ["after this"]

        await http.post("/runs/cancel")
        await first


async def test_a_steer_waits_rather_than_joining_a_side_question():
    hold = asyncio.Event()
    client = FakeClient()
    client.session.side_hold = hold
    async with serve(client) as (http, app):
        side = asyncio.ensure_future(http.post("/sessions/current/ask/stream", json={"question": "aside"}))
        await until(lambda: client.session.asked_side == ["aside"])

        receipt = app.state.runner.received(message("change course"))

        assert receipt.accepted and receipt.disposition == "queued"
        assert client.session.steered == []
        assert [item["text"] for item in (await http.get("/messages")).json()["messages"]] == ["change course"]

        await http.post("/runs/cancel")
        await side


async def test_a_steer_the_run_reports_adopted_is_not_answered_again():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(client) as (http, app):
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        app.state.runner.received(message("change course"))
        slot = app.state.runner.slots[0]
        adopted = client.session.steered[-1]

        app.state.runner._settle_steered(slot, Steered("session-1", adopted))

        await http.post("/runs/cancel")
        await first

        assert (await http.get("/messages")).json() == {"messages": []}


async def test_two_identical_steers_are_two_and_only_the_adopted_one_is_dropped():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(client) as (http, app):
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        app.state.runner.received(message("same words"))
        app.state.runner.received(message("same words"))
        slot = app.state.runner.slots[0]
        assert len(slot.steered) == 2

        app.state.runner._settle_steered(slot, Steered("session-1", client.session.steered[-1]))
        assert len(slot.steered) == 1

        await http.post("/runs/cancel")
        await first
        assert [item["text"] for item in (await http.get("/messages")).json()["messages"]] == ["same words"]


async def test_a_message_from_another_session_waits_for_the_chat_and_is_answered_as_a_turn():
    client = FakeClient(runs=[FakeRun([TextDelta("session-1", "on it")])])
    async with serve(client) as (http, app):
        receipt = app.state.runner.received(message())

        assert receipt.accepted and receipt.disposition == "queued"
        waiting = (await http.get("/messages")).json()["messages"]
        assert waiting == [
            {
                "id": "message-1",
                "sender_id": "session-api",
                "sender": "api",
                "text": "run the tests",
                "via": "agent",
                "hops": 1,
            }
        ]

        async with http.stream("POST", "/messages/message-1") as answer:
            body = "".join([chunk async for chunk in answer.aiter_text()])

        assert answer.status_code == 200
        assert "event: result" in body and "on it" in body
        assert client.relayed[0].text == "run the tests" and client.asked == []
        assert (await http.get("/messages")).json() == {"messages": []}
        assert (await http.post("/messages/message-1")).status_code == 404


async def test_a_message_is_refused_once_too_many_are_waiting():
    from zettcode.server.runner import MAX_INBOX

    client = FakeClient()
    async with serve(client) as (http, app):
        runner = app.state.runner
        for index in range(MAX_INBOX):
            assert runner.received(message(f"message {index}")).accepted

        refused = runner.received(message("one too many"))

        assert not refused.accepted and "waiting" in refused.reason
        assert len((await http.get("/messages")).json()["messages"]) == MAX_INBOX


async def test_answering_a_message_without_a_model_says_so_before_the_stream_opens():
    client = FakeClient()
    async with serve(client) as (http, app):
        app.state.runner.received(message())
        app.state.runner._client = None

        response = await http.post("/messages/message-1")

    assert response.status_code == 409


@pytest.mark.parametrize("unknown", ["message-99"])
async def test_answering_a_message_that_never_arrived_is_a_404(unknown: str):
    async with serve(FakeClient()) as (http, _):
        response = await http.post(f"/messages/{unknown}")

    assert response.status_code == 404


async def test_a_message_to_another_session_is_sent_and_says_who_took_it():
    client = FakeClient()
    async with serve(client) as (http, _):
        response = await http.post("/sessions/current/send", json={"to": "api", "text": "run the tests"})

    assert response.status_code == 200
    assert response.json() == {"to": "api", "disposition": "started"}
    assert client.sent == [("api", "run the tests", "steer")]


async def test_a_message_says_whether_it_steers_and_defaults_to_steer():
    client = FakeClient()
    async with serve(client) as (http, _):
        await http.post("/sessions/current/send", json={"to": "api", "text": "now"})
        await http.post("/sessions/current/send", json={"to": "api", "text": "later", "mode": "followup"})
        refused = await http.post("/sessions/current/send", json={"to": "api", "text": "x", "mode": "later"})

    assert [mode for _, _, mode in client.sent] == ["steer", "followup"]
    assert refused.status_code == 422


async def test_a_message_nobody_can_take_is_a_404_with_the_reason_a_client_can_show():
    async with serve(FakeClient()) as (http, _):
        response = await http.post("/sessions/current/send", json={"to": "nobody", "text": "hello"})

    assert response.status_code == 404
    assert response.json()["error"] == "unreachable"
    assert "nobody" in response.json()["message"]


@pytest.mark.parametrize("body", [{"to": "", "text": "x"}, {"to": "api", "text": ""}, {"to": "api"}])
async def test_a_message_needs_somebody_and_something_to_say(body: dict[str, str]):
    async with serve(FakeClient()) as (http, _):
        response = await http.post("/sessions/current/send", json=body)

    assert response.status_code == 422
