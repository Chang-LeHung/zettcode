"""The client: connecting, registering, sending, receiving, and surviving a broker that comes and goes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from broker_helpers import Host, Inbox, RawPeer, Spawns, client_for, eventually, hold_lock, session
from zettcode.broker.client import BrokerClient, Incoming, Receipt, RosterEntry, SendError
from zettcode.broker.files import LOCK_FILE, NOTE_FILE, Note, write_note
from zettcode.broker.protocol import MAX_HOPS, MAX_TEXT, PROTOCOL_VERSION

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"
C = "03c30d97-cccc-7000-8000-000000000003"


@pytest.fixture
async def host(tmp_path: Path):
    server = Host(tmp_path)
    await server.start()
    clients: list[BrokerClient] = []
    server.clients = clients  # type: ignore[attr-defined]
    yield server
    for client in clients:
        await client.close()
    await server.stop()


async def connected(host: Host, info, **options) -> BrokerClient:
    client = client_for(host.directory, **options)
    host.clients.append(client)  # type: ignore[attr-defined]
    client.set_session(info)
    await client.start()
    assert await client.wait_connected(3), client.last_error
    if info is not None:  # connected is not yet registered: the session is pushed just after the hello
        await eventually(lambda: any(e.session_id == info.session_id for e in host.broker.roster.entries()))
    return client


async def registered(client: BrokerClient, host: Host) -> None:
    await eventually(lambda: host.broker is not None and host.broker.roster.entries())


# -- connecting and registering -----------------------------------------------------------------------------


async def test_a_client_connects_registers_and_sees_the_roster(host):
    rosters: list[tuple[RosterEntry, ...]] = []
    client = await connected(host, session(A, "Alpha job"), on_roster=rosters.append)

    await eventually(lambda: client.roster)

    assert [e.handle for e in client.roster] == ["alpha-job"]
    assert rosters and rosters[-1][0].session_id == A
    assert client.connected and client.last_error is None


async def test_the_clients_own_session_is_not_among_the_others(host):
    one = await connected(host, session(A, "one"))
    two = await connected(host, session(B, "two"))
    await eventually(lambda: len(one.roster) == 2 and len(two.roster) == 2)

    assert [e.session_id for e in one.others()] == [B]
    assert [e.session_id for e in two.others()] == [A]


async def test_a_session_set_before_connecting_is_registered_on_connecting(host):
    client = client_for(host.directory)
    host.clients.append(client)
    client.set_session(session(A, "early bird"))

    await client.start()
    await client.wait_connected(3)

    await eventually(lambda: [e.title for e in host.broker.roster.entries()] == ["early bird"])


async def test_a_client_with_no_session_stays_connected_but_unregistered(host):
    client = client_for(host.directory)
    host.clients.append(client)
    await client.start()
    await client.wait_connected(3)

    await asyncio.sleep(0.05)

    assert client.connected and host.broker.roster.entries() == []


async def test_the_title_and_status_follow_the_session(host):
    client = await connected(host, session(A, "old"))

    client.set_session(session(A, "new name", "working"))

    await eventually(lambda: [(e.title, e.status) for e in host.broker.roster.entries()] == [("new name", "working")])


async def test_a_burst_of_changes_ends_with_the_last_one_at_the_broker(host):
    client = await connected(host, session(A, "t0"))

    for n in range(1, 30):
        client.set_session(session(A, f"t{n}", "working" if n % 2 else "idle"))

    await eventually(lambda: [e.title for e in host.broker.roster.entries()] == ["t29"])
    assert host.broker.roster.entries()[0].status == "working"


async def test_switching_to_another_session_moves_the_registration(host):
    client = await connected(host, session(A, "first"))

    client.set_session(session(B, "second"))

    await eventually(lambda: [e.session_id for e in host.broker.roster.entries()] == [B])


async def test_clearing_the_session_unregisters_without_disconnecting(host):
    client = await connected(host, session(A, "x"))
    await registered(client, host)

    client.set_session(None)

    await eventually(lambda: host.broker.roster.entries() == [])
    assert client.connected


async def test_a_second_process_holding_the_same_session_is_told_so_and_it_clears_when_it_moves_on(host):
    notices: list[str | None] = []
    first = await connected(host, session(A, "mine"))
    second = await connected(host, session(A, "also mine"), on_conflict=notices.append)

    await eventually(lambda: second.conflict)
    assert "already registered" in notices[-1] and first.conflict is None

    second.set_session(session(B, "my own"))
    await eventually(lambda: second.conflict is None)
    assert notices[-1] is None


# -- sending and receiving -----------------------------------------------------------------------------------


async def test_a_message_goes_from_one_client_to_another_and_the_answer_says_what_happened(host):
    inbox = Inbox(Receipt(True, "", "queued"))
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "Receiver Two"), on_message=inbox)
    await eventually(lambda: [e.handle for e in sender.others()])

    delivered = await sender.send("receiver-two", "hello there", hops=1, via="agent")

    assert delivered.disposition == "queued" and delivered.to.handle == "receiver-two"
    (message,) = inbox.messages
    assert (message.text, message.hops, message.via) == ("hello there", 2, "agent")
    assert message.sender.session_id == A and message.sender.handle == "sender"


async def test_a_send_right_after_connecting_waits_for_the_registration_it_depends_on(host, monkeypatch):
    inbox = Inbox()
    await connected(host, session(B, "receiver"), on_message=inbox)
    original = BrokerClient._tell

    async def slowly(self, line):
        await asyncio.sleep(0.3)
        return await original(self, line)

    monkeypatch.setattr(BrokerClient, "_tell", slowly)
    sender = client_for(host.directory)
    host.clients.append(sender)  # type: ignore[attr-defined]
    sender.set_session(session(A, "sender"))
    await sender.start()
    assert await sender.wait_connected(3)
    assert not any(e.session_id == A for e in host.broker.roster.entries()), "the registration is still in flight"
    await eventually(lambda: [e.handle for e in sender.others()])

    delivered = await sender.send("receiver", "as soon as connected")

    assert delivered.to.handle == "receiver" and inbox.messages[-1].text == "as soon as connected"


async def test_a_message_a_reader_typed_says_so(host):
    inbox = Inbox()
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=inbox)

    await sender.send("target", "typed by a person", via="user")

    assert inbox.messages[0].via == "user" and inbox.messages[0].hops == 1


async def test_a_refusal_carries_the_reason_to_the_sender(host):
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=Inbox(Receipt(False, "inbox full (8 waiting)")))

    with pytest.raises(SendError) as refused:
        await sender.send("target", "hi")

    assert refused.value.reason == "rejected" and "inbox full" in str(refused.value)


async def test_a_session_whose_handler_raises_refuses_and_stays_connected(host):
    def broken(incoming: Incoming) -> Receipt:
        raise RuntimeError("bug in the shell")

    sender = await connected(host, session(A, "sender"))
    target = await connected(host, session(B, "target"), on_message=broken)

    with pytest.raises(SendError) as refused:
        await sender.send("target", "hi")

    assert refused.value.reason == "rejected" and "RuntimeError" in str(refused.value)
    assert target.connected, "one bad handler does not cost the session its connection"


async def test_a_session_that_takes_no_messages_says_so(host):
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "deaf"))

    with pytest.raises(SendError) as refused:
        await sender.send("deaf", "hi")

    assert refused.value.reason == "rejected" and "not taking messages" in str(refused.value)


async def test_a_message_to_a_session_that_is_not_there_says_which_names_were_tried(host):
    sender = await connected(host, session(A, "sender"))

    with pytest.raises(SendError) as refused:
        await sender.send("ghost", "hi")

    assert refused.value.reason == "unknown" and "ghost" in str(refused.value)


async def test_a_message_to_oneself_is_refused(host):
    sender = await connected(host, session(A, "me"))

    with pytest.raises(SendError) as refused:
        await sender.send("me", "hi")

    assert refused.value.reason == "self"


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\x1b[0m"])
async def test_an_empty_message_is_refused_before_it_is_sent(host, text):
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=Inbox())

    with pytest.raises(SendError) as refused:
        await sender.send("target", text)

    assert refused.value.reason == "empty"


async def test_a_message_too_long_is_refused_before_it_is_sent(host):
    sender = await connected(host, session(A, "sender"))
    inbox = Inbox()
    await connected(host, session(B, "target"), on_message=inbox)

    with pytest.raises(SendError) as refused:
        await sender.send("target", "x" * (MAX_TEXT + 1))

    assert refused.value.reason == "too_long" and inbox.messages == []


async def test_the_chain_limit_reaches_the_sender_as_a_loop_error(host):
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=Inbox())

    with pytest.raises(SendError) as refused:
        await sender.send("target", "again", hops=MAX_HOPS)

    assert refused.value.reason == "loop"


async def test_text_with_a_lone_surrogate_is_sent_with_a_replacement_instead_of_failing(host):
    inbox = Inbox()
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=inbox)

    await sender.send("target", "broken \ud800 paste")

    assert inbox.messages[0].text == "broken \ufffd paste"


async def test_unicode_and_newlines_arrive_exactly(host):
    inbox = Inbox()
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=inbox)
    text = "第一行\n  second\twith tab\n\U0001f600 emoji — dash"

    await sender.send("target", text)

    assert inbox.messages[0].text == text


async def test_several_sends_at_once_are_each_answered_to_the_right_caller(host):
    inbox = Inbox(lambda incoming: Receipt(True, "", f"got {incoming.text}"))
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=inbox)

    results = await asyncio.gather(*(sender.send("target", f"m{n}") for n in range(10)))

    assert sorted(r.disposition for r in results) == sorted(f"got m{n}" for n in range(10))


async def test_a_handler_runs_on_the_loop_and_messages_are_handled_one_at_a_time_in_order(host):
    order: list[str] = []

    def handler(incoming: Incoming) -> Receipt:
        order.append(incoming.text)
        return Receipt(True, "", "started")

    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=handler)

    for n in range(6):
        await sender.send("target", f"n{n}")

    assert order == [f"n{n}" for n in range(6)]


# -- not connected -------------------------------------------------------------------------------------------


async def test_sending_without_a_connection_fails_at_once_and_says_offline(tmp_path: Path):
    client = client_for(tmp_path)

    with pytest.raises(SendError) as refused:
        await client.send("anyone", "hi")

    assert refused.value.reason == "offline"


async def test_sending_after_close_is_offline(host):
    client = await connected(host, session(A, "a"))
    await client.close()

    with pytest.raises(SendError) as refused:
        await client.send("b", "hi")

    assert refused.value.reason == "offline" and not client.connected


async def test_closing_is_quick_idempotent_and_leaves_no_task_behind(host):
    before = {t for t in asyncio.all_tasks() if not t.done()}
    client = await connected(host, session(A, "a"))

    await asyncio.wait_for(client.close(), 1)
    await asyncio.wait_for(client.close(), 1)
    await asyncio.sleep(0.05)

    leaked = [t for t in asyncio.all_tasks() if not t.done() and t not in before and "pytest" not in repr(t).lower()]
    assert [t for t in leaked if "BrokerClient" in repr(t) or "_supervise" in repr(t) or "_read_loop" in repr(t)] == []


async def test_a_client_that_is_closed_does_not_come_back(host):
    client = await connected(host, session(A, "a"))
    await client.close()

    await client.start()
    await asyncio.sleep(0.2)

    assert not client.connected


async def test_closing_while_still_trying_to_connect_is_quick(tmp_path: Path):
    client = client_for(tmp_path, spawn_wait=30)
    await client.start()
    await asyncio.sleep(0.1)

    await asyncio.wait_for(client.close(), 1)


# -- the broker comes and goes -------------------------------------------------------------------------------


async def test_when_the_broker_dies_the_client_says_so_and_empties_the_roster(host):
    rosters: list[int] = []
    client = await connected(host, session(A, "a"), on_roster=lambda r: rosters.append(len(r)))
    await eventually(lambda: client.roster)

    await host.stop()

    await eventually(lambda: not client.connected)
    assert client.roster == () and rosters[-1] == 0


async def test_a_client_reconnects_to_a_new_broker_and_registers_what_the_session_is_now(host):
    client = await connected(host, session(A, "before"))
    await host.stop()
    await eventually(lambda: not client.connected)
    client.set_session(session(A, "changed while offline", "working"))

    await host.start()

    await eventually(lambda: client.connected)
    await eventually(
        lambda: [(e.title, e.status) for e in host.broker.roster.entries()] == [("changed while offline", "working")]
    )


async def test_messages_work_again_after_a_reconnect(host):
    inbox = Inbox()
    sender = await connected(host, session(A, "sender"))
    await connected(host, session(B, "target"), on_message=inbox)
    await host.stop()
    await eventually(lambda: not sender.connected)

    await host.start()
    await eventually(lambda: sender.connected and any(e.handle == "target" for e in sender.others()))

    await sender.send("target", "after the restart")
    assert inbox.messages[-1].text == "after the restart"


async def test_a_send_in_flight_when_the_broker_dies_fails_instead_of_hanging(host):
    sender = await connected(host, session(A, "sender"))
    silent = await RawPeer.connect(host.broker.port, token=host.token)  # takes a delivery and never answers it
    try:
        await silent.register(B, "silent")
        pending = asyncio.ensure_future(sender.send("silent", "hi"))
        await silent.waiting()

        await host.stop()

        with pytest.raises(SendError) as failed:
            await asyncio.wait_for(pending, 3)
        assert failed.value.reason == "lost" and "may or may not" in str(failed.value)
    finally:
        await silent.close()


async def test_a_stale_note_pointing_at_nothing_starts_a_broker(tmp_path: Path):
    write_note(tmp_path, Note(pid=1, port=1, token="stale", version=PROTOCOL_VERSION))
    host = Host(tmp_path)
    spawns = Spawns(host)
    client = client_for(tmp_path, spawner=spawns, spawn_wait=2)
    client.set_session(session(A, "a"))
    try:
        await client.start()

        assert await client.wait_connected(5)
        assert len(spawns.calls) == 1
    finally:
        await client.close()
        await host.stop()


async def test_with_no_note_at_all_a_broker_is_started_and_joined(tmp_path: Path):
    host = Host(tmp_path)
    spawns = Spawns(host)
    client = client_for(tmp_path, spawner=spawns, spawn_wait=2)
    try:
        await client.start()

        assert await client.wait_connected(5)
        assert spawns.calls == [tmp_path]
    finally:
        await client.close()
        await host.stop()


async def test_a_broker_that_is_already_there_is_not_started_again(host):
    spawns = Spawns()
    client = client_for(host.directory, spawner=spawns)
    host.clients.append(client)  # type: ignore[attr-defined]
    await client.start()

    assert await client.wait_connected(3)
    assert spawns.calls == []


async def test_a_broker_that_cannot_be_started_is_retried_slowly_and_reported(tmp_path: Path):
    spawns = Spawns(fail=True)
    client = client_for(tmp_path, spawner=spawns, spawn_wait=0.1, backoff=(0.02,))
    try:
        await client.start()
        await asyncio.sleep(0.5)

        assert not client.connected and "could not start the session broker" in (client.last_error or "")
        assert len(spawns.calls) == 1, (
            "not once per attempt: a broker that dies at once must not be restarted in a loop"
        )
    finally:
        await client.close()


async def test_a_note_with_the_wrong_token_is_refused_and_a_corrected_note_is_picked_up(tmp_path: Path):
    host = Host(tmp_path)
    await host.start()
    write_note(tmp_path, Note(pid=1, port=host.broker.port, token="not the token", version=PROTOCOL_VERSION))
    client = client_for(tmp_path)
    client.set_session(session(A, "a"))
    try:
        await client.start()
        await asyncio.sleep(0.3)
        assert not client.connected

        write_note(tmp_path, Note(pid=1, port=host.broker.port, token=host.token, version=PROTOCOL_VERSION))

        assert await client.wait_connected(3)
    finally:
        await client.close()
        await host.stop()


async def test_a_note_that_vanishes_while_connected_does_not_disturb_the_connection(host):
    client = await connected(host, session(A, "a"))

    (host.directory / NOTE_FILE).unlink()
    await asyncio.sleep(0.2)

    assert client.connected


# -- a broker that misbehaves --------------------------------------------------------------------------------


class FakeBroker:
    """A broker that greets properly and then does whatever a test's script says: a real WebSocket, no rules."""

    def __init__(self, directory: Path, script=None, *, answer_hello: bool = True, version: int = PROTOCOL_VERSION):
        self.directory = directory
        self.script = script
        self.answer_hello = answer_hello
        self.version = version
        self.received: list[dict] = []
        self.sockets: list[Any] = []
        self.server: Any = None
        self.attempts = 0

    async def start(self) -> None:
        from websockets.asyncio.server import serve

        self.server = await serve(self._serve, "127.0.0.1", 0, ping_interval=None, compression=None)
        port = self.server.sockets[0].getsockname()[1]
        write_note(self.directory, Note(pid=1, port=port, token="fake", version=self.version))

    async def _serve(self, ws: Any) -> None:
        from websockets.exceptions import ConnectionClosed

        self.attempts += 1
        self.sockets.append(ws)
        try:
            if self.answer_hello:
                await self.say(ws, {"op": "hello", "protocol": PROTOCOL_VERSION, "key": "k", "limits": {}})
                if self.script is not None:
                    await self.script(ws)
            async for raw in ws:
                try:
                    received = json.loads(raw)
                except ValueError:
                    continue
                self.received.append(received)
                if received.get("op") in ("session", "leave"):
                    await self.say(ws, {"op": "done", "n": received["n"], "handle": "h"})
        except ConnectionClosed:
            pass

    @staticmethod
    async def say(ws: Any, line: Any) -> None:
        await ws.send(line if isinstance(line, (str, bytes)) else json.dumps(line))

    def answers(self) -> list[dict]:
        """Everything the client said that was an answer to a delivery."""
        return [x for x in self.received if x.get("op") == "ack"]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.fixture
async def fake(tmp_path: Path):
    brokers: list[FakeBroker] = []
    clients: list[BrokerClient] = []

    async def make(script=None, **options) -> tuple[FakeBroker, BrokerClient]:
        broker = FakeBroker(
            tmp_path, script, **{k: options.pop(k) for k in ("answer_hello", "version") if k in options}
        )
        await broker.start()
        client = client_for(tmp_path, **options)
        brokers.append(broker)
        clients.append(client)
        return broker, client

    yield make
    for client in clients:
        await client.close()
    for broker in brokers:
        await broker.stop()


async def test_a_line_of_junk_from_the_broker_is_ignored_and_the_connection_survives(fake):
    async def script(ws):
        for junk in ("not json at all", "[1, 2]", "5", b"\xff", '{"op": "mystery"}', '{"op": "done", "n": 999}'):
            await FakeBroker.say(ws, junk)
        await FakeBroker.say(ws, {"op": "roster", "sessions": [{"session_id": "a", "handle": "ok"}]})

    broker, client = await fake(script)
    await client.start()

    await eventually(lambda: [e.handle for e in client.roster] == ["ok"])
    assert client.connected and broker.attempts == 1


async def test_a_roster_in_a_strange_shape_is_read_without_failing(fake):
    async def script(ws):
        for roster in ("not a list", [1, None, {"session_id": "a", "handle": "ok"}, {"handle": "x"}]):
            await FakeBroker.say(ws, {"op": "roster", "sessions": roster})

    broker, client = await fake(script)
    await client.start()

    await eventually(lambda: [e.handle for e in client.roster] == ["ok"])
    assert client.connected


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"from": None, "text": "x", "hops": 1},
        {"from": {"session_id": "s", "handle": "h"}, "hops": 1},
        {"from": {"session_id": "s", "handle": "h"}, "text": 5, "hops": 1},
        {"from": {"session_id": "s", "handle": "h"}, "text": "x"},
        {"from": {"session_id": "s", "handle": "h"}, "text": "x", "hops": True},
    ],
)
async def test_a_malformed_delivery_is_refused_and_never_reaches_the_session(fake, params):
    inbox = Inbox()

    async def script(ws):
        await FakeBroker.say(ws, {"op": "deliver", "id": 77, **params})

    broker, client = await fake(script, on_message=inbox)
    await client.start()

    answer = await eventually(lambda: next((x for x in broker.answers() if x["id"] == 77), None))
    assert answer["accepted"] is False and answer["reason"] and not inbox.messages
    assert client.connected


async def test_a_delivery_is_cleaned_again_on_arrival_whatever_the_broker_did(fake):
    inbox = Inbox()

    async def script(ws):
        sender = {"session_id": "s", "handle": "h", "title": "t\x1b[31m", "kind": "external"}
        await FakeBroker.say(ws, {"op": "deliver", "id": 5, "from": sender, "text": "a\x1b[2Jb\x00", "hops": 1})
        await FakeBroker.say(ws, {"op": "deliver", "id": 6, "from": sender, "text": "x", "hops": 1, "via": "external"})
        await FakeBroker.say(
            ws, {"op": "deliver", "id": 7, "from": sender, "text": "y", "hops": 1, "via": "carrier pigeon"}
        )

    broker, client = await fake(script, on_message=inbox)
    await client.start()

    await eventually(lambda: len(inbox.messages) == 3)
    assert inbox.messages[0].text == "ab" and inbox.messages[0].sender.title == "t"
    assert [m.via for m in inbox.messages] == ["agent", "external", "agent"]
    assert inbox.messages[0].sender.kind == "external"
    assert all(a["accepted"] is True for a in broker.answers())


async def test_a_session_whose_handler_raises_is_refused_without_its_detail_and_stays_connected(fake):
    def explode(incoming):
        raise RuntimeError("secret detail")

    async def script(ws):
        sender = {"session_id": "s", "handle": "h"}
        await FakeBroker.say(ws, {"op": "deliver", "id": 5, "from": sender, "text": "x", "hops": 1})

    broker, client = await fake(script, on_message=explode)
    await client.start()

    answer = await eventually(lambda: next((x for x in broker.answers() if x["id"] == 5), None))
    assert answer["accepted"] is False and "secret detail" not in answer["reason"] and client.connected


async def test_a_broker_that_never_greets_times_out_the_attempt_not_the_client(fake):
    broker, client = await fake(answer_hello=False, request_timeout=0.2)
    await client.start()

    await eventually(lambda: broker.attempts >= 2, 5)
    assert not client.connected and "does not answer" in (client.last_error or "")


async def test_a_broker_that_closes_right_after_the_greeting_is_reconnected_to(fake):
    async def script(ws):
        await ws.close()

    broker, client = await fake(script)
    await client.start()

    await eventually(lambda: broker.attempts >= 3, 5)


async def test_a_broker_that_says_goodbye_is_looked_for_again_at_once_not_after_the_backoff(fake):
    async def script(ws):
        await ws.close(1012)

    broker, client = await fake(script, backoff=(30.0,))
    await client.start()

    await eventually(lambda: broker.attempts >= 3, 3)


async def test_a_broker_that_just_closes_is_waited_for_by_the_backoff(fake):
    async def script(ws):
        await ws.close(1000)

    broker, client = await fake(script, backoff=(30.0,))
    await client.start()
    await eventually(lambda: broker.attempts >= 1)
    await asyncio.sleep(0.5)

    assert broker.attempts == 1


async def test_a_broker_that_speaks_another_protocol_in_its_greeting_is_reported_and_waited_out(fake):
    problems: list[str | None] = []

    async def script(ws):
        pass

    broker, client = await fake(script, on_problem=problems.append, incompatible_delay=30.0)
    original = FakeBroker.say

    async def other(ws, line):
        if isinstance(line, dict) and line.get("op") == "hello":
            line = {**line, "protocol": PROTOCOL_VERSION + 1}
        await original(ws, line)

    FakeBroker.say = staticmethod(other)  # type: ignore[method-assign]
    try:
        await client.start()
        await eventually(lambda: problems, 3)
    finally:
        FakeBroker.say = staticmethod(original)  # type: ignore[method-assign]

    assert "another protocol" in str(problems[0]) and not client.connected


async def test_a_wrong_token_is_reported_with_the_status_the_broker_answered(tmp_path: Path):
    host = Host(tmp_path)
    await host.start()
    write_note(tmp_path, Note(pid=1, port=host.broker.port, token="not the token", version=PROTOCOL_VERSION))
    client = client_for(tmp_path, spawn_wait=0.2)
    try:
        await client.start()
        await eventually(lambda: client.last_error, 3)

        assert "403" in client.last_error and not client.connected
    finally:
        await client.close()
        await host.stop()


async def test_the_client_never_goes_through_a_proxy_named_in_the_environment(host, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    receiver = Inbox()
    await connected(host, session(B, "receiver"), on_message=receiver)
    sender = await connected(host, session(A, "sender"))

    delivered = await sender.send("receiver", "straight to the broker")

    assert delivered.to.handle == "receiver" and receiver.messages[0].text == "straight to the broker"


async def test_a_send_that_the_broker_never_answers_fails_with_a_timeout_and_the_client_stays_up(host, monkeypatch):
    await connected(host, session(B, "receiver"))
    sender = await connected(host, session(A, "sender"), reply_timeout=0.3)

    async def never(self, key, body):
        await asyncio.sleep(30)

    monkeypatch.setattr(type(host.broker.hub), "send", never)
    with pytest.raises(SendError) as failed:
        await sender.send("receiver", "hi")

    assert failed.value.reason == "timeout" and "may or may not" in str(failed.value) and sender.connected


async def test_a_session_does_not_import_the_web_libraries_until_it_connects():
    import subprocess
    import sys

    code = (
        "import sys; import zettcode.broker.client; "
        "print(*(name in sys.modules for name in ('websockets', 'httpx', 'starlette', 'uvicorn')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert out.stdout.split() == ["False", "False", "False", "False"], out.stderr


async def test_a_broker_out_of_reach_for_a_while_is_reported_once_and_its_return_is_reported_too(tmp_path: Path):
    problems: list[str | None] = []
    client = client_for(tmp_path, on_problem=problems.append, problem_after=0.2, spawn_wait=0.1)
    broker = FakeBroker(tmp_path)
    try:
        await client.start()
        await eventually(lambda: problems, 5)
        await asyncio.sleep(0.3)
        assert len(problems) == 1 and problems[0]

        await broker.start()
        await eventually(lambda: problems[-1] is None, 5)
        assert client.connected and len(problems) == 2
    finally:
        await client.close()
        await broker.stop()


async def test_a_broker_that_holds_the_lock_but_does_not_answer_is_not_replaced_and_is_reported(tmp_path: Path):
    spawns, problems = Spawns(), []
    holder = hold_lock(tmp_path / LOCK_FILE)
    write_note(tmp_path, Note(pid=holder.pid, port=1, token="x", version=PROTOCOL_VERSION))
    client = client_for(tmp_path, spawner=spawns, on_problem=problems.append, problem_after=0.1, spawn_wait=0.2)
    try:
        await client.start()
        await eventually(lambda: problems, 5)

        assert f"pid {holder.pid}" in problems[0] and "does not answer" in problems[0]
        assert spawns.calls == [], "a second broker would only exit, and would hide that the first is stuck"
    finally:
        await client.close()
        holder.kill()
        holder.wait()


async def test_a_broker_of_a_newer_protocol_is_reported_at_once_and_not_hammered(tmp_path: Path):
    holder = hold_lock(tmp_path / LOCK_FILE)
    write_note(tmp_path, Note(pid=holder.pid, port=1, token="x", version=PROTOCOL_VERSION + 1))
    spawns, problems = Spawns(), []
    reads = []
    client = client_for(
        tmp_path, spawner=spawns, on_problem=problems.append, spawn_wait=0.1, incompatible_delay=0.3, problem_after=60
    )
    from zettcode.broker import finder as client_module

    real_read = client_module.read_note
    client_module.read_note = lambda directory: (reads.append(1), real_read(directory))[1]  # type: ignore[assignment]
    try:
        await client.start()
        await eventually(lambda: problems, 3)
        await asyncio.sleep(0.7)

        assert "another protocol" in problems[0] and spawns.calls == []
        assert len(reads) < 40, "one look each half second or so, not fifty a second"
    finally:
        client_module.read_note = real_read  # type: ignore[assignment]
        await client.close()
        holder.kill()
        holder.wait()


async def test_a_note_of_another_protocol_whose_broker_is_gone_is_replaced(tmp_path: Path):
    write_note(tmp_path, Note(pid=1, port=1, token="x", version=PROTOCOL_VERSION - 1))
    spawns = Spawns()
    client = client_for(tmp_path, spawner=spawns, spawn_wait=0.2)
    try:
        await client.start()
        await eventually(lambda: spawns.calls, 3)
    finally:
        await client.close()


async def test_a_replacement_that_did_not_free_the_lock_is_tried_again_and_then_left_alone(tmp_path: Path, monkeypatch):
    """Recognising the process can fail for a reason that is not its own: the command-line lookup on Windows is a
    PowerShell call that can time out on a busy machine. One such failure must not leave the pid marked as tried, so
    that the session reports "another protocol" for ever while the old broker keeps the next one out."""
    from zettcode.broker import finder as broker_finder

    holder = hold_lock(tmp_path / LOCK_FILE)
    write_note(tmp_path, Note(pid=holder.pid, port=1, token="x", version=PROTOCOL_VERSION - 1))
    attempts: list[int] = []

    def never_ends(pid: int, module: str, *, released: Any) -> bool:
        attempts.append(pid)
        return False

    monkeypatch.setattr(broker_finder.process, "end", never_ends)
    monkeypatch.setattr(broker_finder, "REPLACE_RETRY", 0.0)
    finder = broker_finder.Finder(directory=tmp_path, spawn_wait=0.05)
    try:
        for _ in range(broker_finder.REPLACE_ATTEMPTS):
            with pytest.raises(ConnectionError):
                await finder.open(lambda: True)
        assert attempts == [holder.pid] * broker_finder.REPLACE_ATTEMPTS
        assert not finder.incompatible, "an older broker that is being ended is not a protocol to wait on"

        with pytest.raises(ConnectionError):
            await finder.open(lambda: True)
        assert len(attempts) == broker_finder.REPLACE_ATTEMPTS, "a process that has refused this often is left alone"
    finally:
        holder.kill()
        holder.wait()


async def test_reconnecting_over_and_over_leaves_no_tasks_or_connections_behind(host):
    before = {t for t in asyncio.all_tasks() if not t.done()}
    client = await connected(host, session(A, "a"))
    for _ in range(4):
        for open_session in list(host.broker.hub.sessions.values()):
            open_session.close(1012)
        await eventually(lambda: not client.connected, 2)
        assert await client.wait_connected(3)
    await client.close()
    await asyncio.sleep(0.1)

    leaked = [t for t in asyncio.all_tasks() if not t.done() and t not in before and "pytest" not in repr(t).lower()]
    assert [t for t in leaked if "BrokerClient" in repr(t)] == []
    assert len(host.broker.hub.sessions) == 0


async def test_a_session_that_is_closed_leaves_the_roster_at_once_not_after_a_timeout(host):
    client = await connected(host, session(A, "a"))
    watcher = await connected(host, session(B, "b"))
    await eventually(lambda: len(watcher.roster) == 2)

    await client.close()

    await eventually(lambda: [e.session_id for e in watcher.roster] == [B], 1)
