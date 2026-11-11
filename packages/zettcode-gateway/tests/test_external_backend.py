"""The gateway's external backend: register, receive, send, and read without owning a ZettCode session."""

from __future__ import annotations

import pathlib

import pytest

from broker_helpers import Host, Inbox, client_for, eventually, session
from zettcode.gateway.external_backend import ExternalBackend
from zettcode.sdk.types import IncomingMessage, Receipt

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


@pytest.fixture
async def host(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_BROKER_DIR", str(tmp_path / "broker"))
    server = Host(tmp_path / "broker")
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_the_backend_registers_receives_and_replies(host, tmp_path):
    seen: list[IncomingMessage] = []

    def receive(message: IncomingMessage) -> Receipt:
        seen.append(message)
        return Receipt(True, disposition="delivered")

    backend = ExternalBackend(tmp_path / "gw")
    await backend.start(receive, lambda: None)
    try:
        assert backend.reachable
        assert backend.gateway_id.startswith("web-")

        inbox = Inbox()
        sender = client_for(host.directory, on_message=inbox)
        sender.set_session(session(A, "Sender"))
        await sender.start()
        assert await sender.wait_connected(3)
        assert await sender.wait_registered(3)

        delivered = await sender.send(backend.gateway_id, "hello")
        assert delivered.disposition == "delivered"
        await eventually(lambda: seen)
        assert seen[0].text == "hello"

        await backend.send(sender.session.session_id, "back")
        await eventually(lambda: inbox.messages)
        assert inbox.messages[0].text == "back"
        await sender.close()
    finally:
        await backend.close()
