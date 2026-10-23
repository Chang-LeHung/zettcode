"""Messages from other sessions: held for this chat, then answered as a turn of its own."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from server_fakes import FakeClient, FakeRun
from zettcode.sdk.events import TextDelta
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


def message(text: str = "run the tests", sender: str = "api") -> IncomingMessage:
    return IncomingMessage(sender_id=f"session-{sender}", sender=sender, text=text, via="agent", hops=1)


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
