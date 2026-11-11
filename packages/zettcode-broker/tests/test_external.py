"""The high-level external session: register, receive, answer, publish, and refuse a duplicate id."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from broker_helpers import Host, Inbox, client_for, eventually, session
from zettcode.broker.client import BrokerClient
from zettcode.broker.external import (
    ExternalConflict,
    ExternalNotConnected,
    ExternalPublisher,
    ExternalSession,
)
from zettcode.broker.models import Incoming, Receipt, SendError

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


@pytest.fixture
async def host(tmp_path: pathlib.Path):
    server = Host(tmp_path)
    await server.start()
    clients: list[BrokerClient] = []

    def track(client: BrokerClient) -> BrokerClient:
        clients.append(client)
        return client

    server.track = track  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        for client in clients:
            await client.close()
        await server.stop()


async def sender(host, inbox: Inbox) -> BrokerClient:
    client = host.track(client_for(host.directory, on_message=inbox))  # type: ignore[attr-defined]
    client.set_session(session(B, "Sender"))
    await client.start()
    assert await client.wait_connected(3)
    assert await client.wait_registered(3)
    return client


async def test_an_external_session_registers_receives_and_replies(host):
    seen: list[Incoming] = []

    def handle(message: Incoming) -> Receipt:
        seen.append(message)
        return Receipt(True, disposition="started")

    async with ExternalSession(A, "Build bot", directory=host.directory, on_message=handle) as external:
        await eventually(lambda: external.handle)
        other = await sender(host, Inbox())

        delivered = await other.send(external.handle, "build failed")
        assert delivered.disposition == "started"

        await eventually(lambda: seen)
        assert seen[0].sender.handle == "sender"
        assert seen[0].text == "build failed"

        await external.reply(seen[0], "looking")
        await eventually(lambda: other.roster and other.others())


async def test_a_string_from_a_handler_is_sent_back(host):
    async def handle(message: Incoming) -> str:
        return f"echo: {message.text}"

    async with ExternalSession(A, "Echo", directory=host.directory, on_message=handle) as external:
        await eventually(lambda: external.handle)
        inbox = Inbox()
        other = await sender(host, inbox)

        delivered = await other.send(external.handle, "ping")
        assert delivered.disposition == "queued"
        await eventually(lambda: inbox.messages)
        assert inbox.messages[0].text == "echo: ping"


async def test_the_default_handler_queues_and_receives(host):
    async with ExternalSession(A, "Queue", directory=host.directory) as external:
        await eventually(lambda: external.handle)
        other = await sender(host, Inbox())
        await other.send(external.handle, "queued")

        message = await asyncio.wait_for(external.receive(), 3)
        assert message.text == "queued"


async def test_two_external_sessions_are_two_roster_entries(host):
    async with (
        ExternalSession(A, "Build bot", directory=host.directory) as first,
        ExternalSession(B, "Alert bot", directory=host.directory) as second,
    ):
        await eventually(lambda: len(first.roster) == 2 and len(second.roster) == 2)
        assert {entry.session_id for entry in first.roster} == {A, B}
        assert first.handle != second.handle


async def test_a_duplicate_id_is_reported(host):
    async with ExternalSession(A, "First", directory=host.directory):
        second = ExternalSession(A, "Second", directory=host.directory)
        with pytest.raises(ExternalConflict):
            await second.connect()
        await second.close()


async def test_a_missing_broker_is_reported(tmp_path):
    with pytest.raises(ExternalNotConnected):
        await ExternalSession(
            A, "Nowhere", directory=tmp_path, spawner=lambda path: None, connect_timeout=0.1
        ).connect()


async def test_a_handler_that_raises_is_refused(host):
    def handle(message: Incoming) -> None:
        raise RuntimeError("bad handler")

    async with ExternalSession(A, "Broken", directory=host.directory, on_message=handle) as external:
        await eventually(lambda: external.handle)
        other = await sender(host, Inbox())

        with pytest.raises(SendError, match="the handler failed"):
            await other.send(external.handle, "hello")


async def test_the_publisher_reports_a_broker_refusal(host):
    await sender(host, Inbox())

    async with ExternalPublisher("ci", directory=host.directory) as publisher:
        with pytest.raises(SendError) as caught:
            await publisher.send("@nobody", "hello")

    assert caught.value.reason == "unknown"


async def test_the_publisher_sends_without_registering(host):
    inbox = Inbox()
    receiver = await sender(host, inbox)

    async with ExternalPublisher("ci", directory=host.directory) as publisher:
        delivered = await publisher.send(receiver.session.session_id, "one way")

    assert delivered.disposition == "started"
    await eventually(lambda: inbox.messages)
    assert inbox.messages[0].text == "one way"
    assert inbox.messages[0].via == "external"
