"""The gateway's external backend: register, receive, send, and read without owning a ZettCode session."""

from __future__ import annotations

import pathlib

import pytest
from zett_agent.messages import AssistantMessage, UserMessage

from broker_helpers import Host, Inbox, client_for, eventually, session
from zettcode.engine.storage.store import SessionStore
from zettcode.gateway.external_backend import ExternalBackend
from zettcode.gateway.service import GatewayError
from zettcode.sdk.errors import SendError, SessionNotFoundError
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
        assert backend.stamp(sender.session.session_id, "") is None
        assert [message.text for message in await backend.history(sender.session.session_id, "")] == ["hello"]
        assert [peer.session_id for peer in backend.peers()] == [sender.session.session_id]

        with pytest.raises(SendError):
            await backend.send(sender.session.session_id, "x", direct=True)

        await backend.send(sender.session.session_id, "back")
        await eventually(lambda: inbox.messages)
        assert inbox.messages[0].text == "back"
        await sender.close()
    finally:
        await backend.close()


async def test_history_is_the_session_store_not_the_gateway_pair(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    root = tmp_path / "sessions"
    store = SessionStore(root, workspace)
    await store.append(B, "request", UserMessage(content="question"))
    await store.append(B, "request", AssistantMessage(content="answer", model="m"))

    backend = ExternalBackend(tmp_path / "gw", sessions_root=root)
    history = await backend.history(B, str(workspace))
    assert [message.text for message in history] == ["question", "answer"]
    assert backend.stamp(B, str(workspace)) == (
        store.session_path(B).stat().st_mtime_ns,
        store.session_path(B).stat().st_size,
    )


async def test_a_damaged_transcript_is_not_replaced_by_the_broker_pair(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    root = tmp_path / "sessions"
    store = SessionStore(root, workspace)
    await store.append(B, "request", UserMessage(content="question"))
    await store.append(B, "request", AssistantMessage(content="answer", model="m"))
    path = store.session_path(B)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n{not json\n" + "\n".join(lines[1:]) + "\n", encoding="utf-8")

    backend = ExternalBackend(tmp_path / "gw", sessions_root=root)
    with pytest.raises(SessionNotFoundError):
        await backend.history(B, str(workspace))


async def test_owner_reads_report_a_closed_broker(tmp_path):
    backend = ExternalBackend(tmp_path / "gw")
    with pytest.raises(GatewayError):
        await backend.graph()
