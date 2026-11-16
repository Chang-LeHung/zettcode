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
            await backend.send(sender.session.session_id, "x", images=[object()])  # type: ignore[list-item]

        # The peer does not take direct prompts, so a raw ask arrives the ordinary way and says so.
        asked = await backend.send(sender.session.session_id, "raw", direct=True)
        assert asked.direct is False
        await eventually(lambda: inbox.messages)
        inbox.messages.clear()

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


async def test_stopping_a_daemon_keeps_its_record_so_it_can_be_started_again(tmp_path, monkeypatch):
    """The page says a stopped daemon stays listed as offline and can be started again; that needs its record."""
    asked: list[dict[str, object]] = []

    async def stop_daemon(session_id: str, *, force: bool = False, keep: bool = False) -> str:
        asked.append({"session_id": session_id, "force": force, "keep": keep})
        return "stopped; its record was kept"

    from zettcode.sdk import daemons as sdk_daemons

    monkeypatch.setattr(sdk_daemons, "stop_daemon", stop_daemon)

    said = await ExternalBackend(tmp_path / "gw").stop("01d", force=True)

    assert said == "stopped; its record was kept"
    assert asked == [{"session_id": "01d", "force": True, "keep": True}]


async def test_a_watched_session_s_pieces_reach_the_gateway_as_stream_events(host, tmp_path):
    heard = []
    backend = ExternalBackend(tmp_path / "gw")
    await backend.start(lambda message: Receipt(True, disposition="delivered"), lambda: None)
    try:
        backend.on_stream(heard.append)
        streamer = client_for(host.directory, on_message=Inbox())
        streamer.set_session(session(A, "Streamer"))
        await streamer.start()
        assert await streamer.wait_connected(3)
        assert await streamer.wait_registered(3)
        backend.watch(A)
        await eventually(lambda: streamer.watched)
        streamer.publish({"t": "text", "text": "hel"})
        streamer.publish({"t": "tool", "id": "c1", "name": "read", "brief": "a.py"})
        streamer.publish({"t": "tool_end", "id": "c1", "ok": True})
        await eventually(lambda: len(heard) == 3)
        assert [(item.kind, item.text, item.call_id, item.ok) for item in heard] == [
            ("text", "hel", "", None),
            ("tool", "", "c1", None),
            ("tool_end", "", "c1", True),
        ]
        await streamer.close()
    finally:
        await backend.close()


async def test_a_session_the_broker_has_never_heard_of_has_an_empty_conversation(host, tmp_path):
    backend = ExternalBackend(tmp_path / "gw")
    await backend.start(lambda message: Receipt(True, disposition="delivered"), lambda: None)
    try:
        assert await backend.history("01a1df6b-5f00-7596-8270-a5103e5ddf18", "") == []
    finally:
        await backend.close()


async def test_a_stopped_daemon_with_no_stored_conversation_has_nothing_to_resume(host, tmp_path):
    backend = ExternalBackend(tmp_path / "gw", tmp_path / "sessions")
    await backend.start(lambda message: Receipt(True, disposition="delivered"), lambda: None)
    try:
        with pytest.raises(SessionNotFoundError):
            await backend.history("01a1df6b-5f00-7596-8270-a5103e5ddf18", str(tmp_path))
    finally:
        await backend.close()


async def test_a_broker_refusal_that_is_not_about_the_session_still_raises(host, tmp_path):
    backend = ExternalBackend(tmp_path / "gw")
    await backend.start(lambda message: Receipt(True, disposition="delivered"), lambda: None)
    try:
        backend._owner = None  # the owner client is gone: the read is refused as "broker", not as an unknown session
        with pytest.raises(GatewayError) as refused:
            await backend.history("01a1df6b-5f00-7596-8270-a5103e5ddf18", "")
        assert refused.value.code == "broker"
    finally:
        await backend.close()
