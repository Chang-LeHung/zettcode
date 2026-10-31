"""The broker, spoken to over a real socket: a WebSocket for each session, and plain HTTP for sending.

Every corner a peer can reach is here: a request without the token, a session that sends garbage or a message that
is too long, a recipient that never answers or that disappears while it is being handed a message, a sender that
goes while its message is in flight, an external source that is not a session, and a message that would never stop
being forwarded.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from websockets.exceptions import InvalidStatus

from broker_helpers import TOKEN, RawPeer, eventually, http, reason, started
from zettcode.broker.hub import MAX_WAITING, Session
from zettcode.broker.protocol import MAX_BODY, MAX_HOPS, MAX_TEXT, PROTOCOL_VERSION, RATE_LIMIT, Limits

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"
C = "03c30d97-cccc-7000-8000-000000000003"


@pytest.fixture
async def running():
    server = await started(idle_exit=60)
    yield server
    await server.aclose()


def message(to: str, text: Any, **more: Any) -> dict[str, Any]:
    return {"to": to, "text": text, **more}


async def sent(sender: RawPeer, recipient: RawPeer, to: str, text: str, **more: Any) -> dict[str, Any]:
    """Send a message, have the recipient take it, and return the sender's answer."""
    pending = asyncio.ensure_future(sender.post(**message(to, text, **more)))
    await recipient.accept()
    return await pending


# -- who is let in -----------------------------------------------------------------------------------------


async def test_a_session_with_the_token_is_let_in_and_told_what_is_allowed_and_then_who_is_here(running):
    peer = await running.peer()

    hello = peer.lines[0]
    assert hello["op"] == "hello" and hello["protocol"] == PROTOCOL_VERSION and hello["key"] == peer.key
    assert hello["limits"]["max_text"] == MAX_TEXT and hello["limits"]["max_hops"] == MAX_HOPS
    await eventually(lambda: peer.rosters() == [[]])
    assert peer.lines[1]["op"] == "roster", "the greeting comes before the roster"


@pytest.mark.parametrize("token", ["wrong", None])
async def test_a_websocket_without_the_token_is_turned_away_before_it_is_accepted(running, token):
    with pytest.raises(InvalidStatus) as refused:
        await RawPeer.connect(running.port, token=token, hello=False)

    assert refused.value.response.status_code == 403
    assert not running.broker.hub.sessions


@pytest.mark.parametrize("token", ["wrong", None])
@pytest.mark.parametrize(("method", "path"), [("GET", "/sessions"), ("POST", "/messages")])
async def test_an_http_request_without_the_token_is_refused_and_says_what_it_wants(running, token, method, path):
    response = await http(running.port, method, path, token=token, json={"to": "x", "text": "y"})

    assert response.status_code == 401 and response.json()["error"]["reason"] == "auth"
    assert "Bearer" in response.json()["error"]["message"] and TOKEN not in response.text


async def test_the_health_route_needs_no_token_and_says_nothing_else(running):
    response = await http(running.port, "GET", "/health", token=None)

    assert response.status_code == 200 and response.json() == {"ok": True}


async def test_sessions_are_listed_for_anyone_with_the_token(running):
    await running.peer(A, "alpha")

    body = (await http(running.port, "GET", "/sessions")).json()

    assert [s["handle"] for s in body["sessions"]] == ["alpha"] and body["limits"]["max_text"] == MAX_TEXT


async def test_connections_past_the_limit_are_turned_away_and_the_registered_sessions_are_unharmed():
    server = await started(idle_exit=60, max_connections=2)
    try:
        one = await server.peer(A, "one")
        await server.peer(B, "two")

        with pytest.raises(InvalidStatus):
            await RawPeer.connect(server.port, hello=False)

        assert "error" not in await one.register(A, "still here")
        assert len(server.broker.roster.entries()) == 2
    finally:
        await server.aclose()


# -- what comes over the websocket --------------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["not json", "[1, 2]", "5", "null", '"text"', b"\xff\xfe"])
async def test_a_message_that_is_not_a_json_object_ends_the_connection_and_the_roster_forgets_the_session(
    running, junk
):
    peer = await running.peer(A, "a")
    other = await running.peer(B, "b")

    await peer.send_raw(junk)

    assert await peer.ended()
    await eventually(lambda: [e.session_id for e in running.broker.roster.entries()] == [B])
    assert "error" not in await other.register(B, "b")


async def test_a_message_past_the_limit_ends_the_connection_with_1009_and_does_not_take_the_others_down(running):
    peer = await running.peer(A, "a")
    other = await running.peer(B, "b")

    await peer.announce_frame(MAX_BODY + 10)

    assert await peer.ended() and peer.close_code == 1009
    await eventually(lambda: [e.session_id for e in running.broker.roster.entries()] == [B])
    assert "error" not in await other.register(B, "b")


async def test_a_whole_message_past_the_limit_still_ends_only_that_connection(running):
    """The same refusal when the sender really writes the body: it may see a reset, and the others never do."""
    peer = await running.peer(A, "a")
    other = await running.peer(B, "b")

    with contextlib.suppress(Exception):  # the server hangs up mid-write, which the sender may see as a reset
        await peer.send_raw('{"op": "session", "title": "' + "x" * (MAX_BODY + 10) + '"}')

    assert await peer.ended()
    await eventually(lambda: [e.session_id for e in running.broker.roster.entries()] == [B])
    assert "error" not in await other.register(B, "b")


async def test_a_request_body_past_the_limit_is_refused_before_it_is_read_into_memory(running):
    response = await http(running.port, "POST", "/messages", content=b"x" * (MAX_BODY + 10))

    assert response.status_code == 413 and response.json()["error"]["reason"] == "too_long"


@pytest.mark.parametrize("content", [b"not json", b"[1]", b"7", b""])
async def test_a_body_that_is_not_a_json_object_is_refused(running, content):
    response = await http(running.port, "POST", "/messages", content=content)

    assert response.status_code == 400 and response.json()["error"]["reason"] == "invalid"


async def test_the_longest_message_in_four_byte_characters_still_fits(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    answer = await sent(sender, recipient, "b", "\U0001f600" * MAX_TEXT)

    assert "error" not in answer, answer["error"]
    assert len(recipient.requests()[0]["text"]) == MAX_TEXT


async def test_an_unknown_op_is_ignored_and_the_connection_goes_on(running):
    peer = await running.peer(A, "a")

    await peer.send({"op": "dance"})
    await peer.send({"hello": "there"})
    await peer.send({"op": "roster", "sessions": []})

    assert "error" not in await peer.call("leave")


@pytest.mark.parametrize("number", [True, 1.5, "x", [1], None])
async def test_a_strange_n_is_answered_without_it_and_does_not_hurt(running, number):
    peer = await running.peer(A, "a")

    await peer.send({"op": "leave", "n": number})

    await eventually(lambda: any(x.get("op") == "done" and x.get("n") is None for x in peer.lines))
    assert "error" not in await peer.call("leave")


async def test_a_session_that_acks_what_was_never_asked_is_ignored(running):
    peer = await running.peer(A, "a")

    await peer.send({"op": "ack", "id": 12345, "accepted": True})
    await peer.send({"op": "ack", "id": "x", "accepted": True})

    assert "error" not in await peer.call("leave")


async def test_a_request_the_broker_cannot_finish_is_an_internal_error_and_the_server_goes_on(running, monkeypatch):
    sender = await running.peer(A, "a")
    await running.peer(B, "b")

    async def explode(self, message, timeout):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(Session, "deliver", explode)
    answer = await sender.post(**message("b", "hi"))
    monkeypatch.undo()

    assert reason(answer) == "internal" and answer["status"] == 500 and "secret detail" not in str(answer)
    assert (await http(running.port, "GET", "/health", token=None)).status_code == 200


# -- registering -------------------------------------------------------------------------------------------


async def test_registering_gives_a_handle_and_tells_everyone(running):
    first = await running.peer()
    second = await running.peer()

    answer = await first.register(A, "Fix the parser")

    assert answer["handle"] == "fix-the-parser"
    for peer in (first, second):
        await eventually(lambda p=peer: [e["handle"] for e in p.listed()] == ["fix-the-parser"])
    assert second.listed()[0] == {
        "direct": False,
        "kind": "zettcode",
        "session_id": A,
        "handle": "fix-the-parser",
        "title": "Fix the parser",
        "workspace": "/w",
        "status": "idle",
    }


async def test_the_registering_session_hears_its_handle_before_the_roster_that_holds_it(running):
    peer = await running.peer()

    answer = await peer.register(A, "a")

    await eventually(lambda: any(r and r[0]["session_id"] == A for r in peer.rosters()))
    first_with_it = next(x for x in peer.lines if x.get("op") == "roster" and x["sessions"])
    assert peer.lines.index(answer) < peer.lines.index(first_with_it)


async def test_a_session_held_by_another_connection_is_refused_and_the_roster_is_unchanged(running):
    await running.peer(A, "a")
    intruder = await running.peer()

    answer = await intruder.register(A, "again")

    assert reason(answer) == "duplicate"
    assert [e.title for e in running.broker.roster.entries()] == ["a"]


@pytest.mark.parametrize("session_id", ["", "a b", "../x", "x" * 65, 5, None])
async def test_a_bad_session_id_is_refused(running, session_id):
    peer = await running.peer()

    assert reason(await peer.call("session", session_id=session_id)) == "invalid"
    assert not running.broker.roster.entries()


async def test_changing_the_title_renames_the_handle_and_tells_everyone(running):
    peer = await running.peer(A, "old name")
    watcher = await running.peer()

    answer = await peer.register(A, "new name")

    assert answer["handle"] == "new-name"
    await eventually(lambda: [e["handle"] for e in watcher.listed()] == ["new-name"])


async def test_registering_the_same_thing_again_does_not_tell_everyone_again(running):
    peer = await running.peer(A, "a")
    watcher = await running.peer()
    await eventually(lambda: watcher.rosters())
    before = len(watcher.rosters())

    await peer.register(A, "a")
    await peer.call("session", session_id=A, title="a", workspace="/w", status="idle")
    await asyncio.sleep(0.1)

    assert len(watcher.rosters()) == before


async def test_a_status_change_is_told_to_everyone(running):
    peer = await running.peer(A, "a")
    watcher = await running.peer()

    await peer.register(A, "a", status="working")

    await eventually(lambda: [e["status"] for e in watcher.listed()] == ["working"])


async def test_leaving_removes_the_session_but_keeps_the_connection(running):
    peer = await running.peer(A, "a")
    watcher = await running.peer()

    assert "error" not in await peer.call("leave")

    await eventually(lambda: watcher.rosters() and watcher.rosters()[-1] == [])
    assert "error" not in await peer.register(A, "a")


async def test_leaving_when_nothing_is_registered_is_not_an_error(running):
    peer = await running.peer()

    assert "error" not in await peer.call("leave")


async def test_a_disconnect_removes_the_session_and_tells_the_others(running):
    gone = await running.peer(A, "a")
    watcher = await running.peer(B, "b")

    await gone.close()

    await eventually(lambda: [e["session_id"] for e in watcher.listed()] == [B])


async def test_a_session_can_be_registered_again_once_its_holder_has_gone(running):
    gone = await running.peer(A, "a")
    await gone.close()
    await eventually(lambda: not running.broker.roster.entries())

    heir = await running.peer()

    assert "error" not in await heir.register(A, "a")


# -- sending -----------------------------------------------------------------------------------------------


async def test_a_message_reaches_its_recipient_with_who_sent_it_and_one_more_hop(running):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    answer = await sent(sender, recipient, "beta", "hello there", hops=2)

    delivery = recipient.requests()[0]
    assert delivery["text"] == "hello there" and delivery["hops"] == 3 and delivery["via"] == "agent"
    assert delivery["from"]["session_id"] == A and delivery["from"]["handle"] == "alpha"
    assert answer["to"]["session_id"] == B and answer["disposition"] == "started"


async def test_a_message_says_whether_it_steers_and_a_message_that_says_nothing_steers(running):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    await sent(sender, recipient, "beta", "now")
    await sent(sender, recipient, "beta", "later", mode="followup")

    steering, following = recipient.requests()
    assert steering["mode"] == "steer" and following["mode"] == "followup"


async def test_the_recipient_may_say_it_steered_the_running_request(running):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    pending = asyncio.ensure_future(sender.post(**message("beta", "change course")))
    await recipient.waiting()
    await recipient.accept("steered")

    assert (await pending)["disposition"] == "steered"


async def test_the_sender_is_answered_only_after_the_recipient_has_answered(running):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    pending = asyncio.ensure_future(sender.post(**message("beta", "hi")))
    await recipient.waiting()
    await asyncio.sleep(0.1)
    assert not [x for x in sender.lines if "re" in x and x.get("to")], "nothing is promised before it is taken"

    await recipient.accept("queued")

    assert (await pending)["disposition"] == "queued"


@pytest.mark.parametrize("name", [B, B[:8], "beta", "@beta", "BETA"])
async def test_a_message_can_be_addressed_by_id_prefix_handle_or_title(running, name):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    answer = await sent(sender, recipient, name, "hi")

    assert answer["to"]["session_id"] == B


async def test_a_sender_with_no_session_cannot_send(running):
    await running.peer(B, "beta")
    stranger = await running.peer()

    assert reason(await stranger.post(**message("beta", "hi"))) == "not_registered"


async def test_a_message_to_nobody_or_to_oneself_is_refused(running):
    sender = await running.peer(A, "alpha")

    assert reason(await sender.post(**message("nobody", "hi"))) == "unknown"
    assert reason(await sender.post(**message("alpha", "hi"))) == "self"


async def test_an_ambiguous_name_is_refused_and_lists_the_candidates(running):
    sender = await running.peer(A, "alpha")
    await running.peer(B, "same name")
    await running.peer(C, "same name")

    answer = await sender.post(**message("same name", "hi"))

    assert reason(answer) == "ambiguous"
    assert answer["error"]["message"].count("@same-name") == 2


@pytest.mark.parametrize("text", ["", " ", "\n\t ", "\x1b[31m\x07"])
async def test_a_message_with_nothing_to_say_is_refused(running, text):
    sender, _ = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", text))) == "empty"


@pytest.mark.parametrize("text", [5, None, ["x"], {"a": 1}])
async def test_a_message_that_is_not_text_is_refused(running, text):
    sender, _ = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", text))) == "invalid"


async def test_a_message_past_the_length_limit_is_refused_and_one_at_it_is_taken(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", "x" * (MAX_TEXT + 1)))) == "too_long"
    assert "error" not in await sent(sender, recipient, "b", "x" * MAX_TEXT)


async def test_escape_sequences_never_reach_the_recipient(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    await sent(sender, recipient, "b", "a\x1b[31mred\x1b[0m\x07 b")

    assert recipient.requests()[0]["text"] == "ared b"


@pytest.mark.parametrize("via", ["owl", 5, None])
async def test_an_unknown_origin_is_refused(running, via):
    sender, _ = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", "hi", via=via))) == "invalid"


@pytest.mark.parametrize("hops", [-1, True, 1.5, "2", None])
async def test_a_hop_count_that_is_not_a_count_is_refused(running, hops):
    sender, _ = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", "hi", hops=hops))) == "invalid"


async def test_a_chain_of_forwarded_messages_stops_at_the_limit(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    assert "error" not in await sent(sender, recipient, "b", "ok", hops=MAX_HOPS - 1)
    assert reason(await sender.post(**message("b", "too far", hops=MAX_HOPS))) == "loop"


async def test_a_message_a_reader_typed_starts_a_new_chain_whatever_hops_it_claims(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    await sent(sender, recipient, "b", "hi", via="user", hops=99)

    assert recipient.requests()[0]["hops"] == 1 and recipient.requests()[0]["via"] == "user"


async def test_two_sessions_that_answer_each_other_cannot_do_so_for_ever(running):
    one, two = await running.peer(A, "one"), await running.peer(B, "two")
    hops, answered = 0, 0

    for turn in range(MAX_HOPS + 3):
        sender, recipient, to = (one, two, "two") if turn % 2 == 0 else (two, one, "one")
        pending = asyncio.ensure_future(sender.post(**message(to, f"turn {turn}", hops=hops)))
        done, _ = await asyncio.wait([pending], timeout=0.2)
        if done:
            assert reason(pending.result()) == "loop"
            break
        delivery = await recipient.accept()
        await pending
        hops, answered = delivery["hops"], answered + 1

    assert answered == MAX_HOPS


async def test_a_recipient_that_refuses_gives_its_reason_to_the_sender(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    pending = asyncio.ensure_future(sender.post(**message("b", "hi")))
    await recipient.refuse("my queue is full")
    answer = await pending

    assert reason(answer) == "rejected" and answer["error"]["message"] == "my queue is full"


async def test_a_refusal_with_no_reason_or_a_hostile_one_is_still_a_clean_refusal(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    pending = asyncio.ensure_future(sender.post(**message("b", "hi")))
    await recipient.refuse("\x1b[31m" + "r" * 999)
    first = await pending
    pending = asyncio.ensure_future(sender.post(**message("b", "hi")))
    await recipient.refuse("")
    second = await pending

    assert first["error"]["message"] == "r" * 300
    assert reason(second) == "rejected" and second["error"]["message"]


@pytest.mark.parametrize("accepted", ["yes", 1, None, [True]])
async def test_an_answer_that_does_not_plainly_say_yes_is_a_refusal_not_a_delivery(running, accepted):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    pending = asyncio.ensure_future(sender.post(**message("b", "hi")))
    delivery = await recipient.waiting()
    await recipient.send({"op": "ack", "id": delivery["id"], "accepted": accepted})

    assert reason(await pending) == "rejected"


async def test_a_recipient_that_never_answers_times_out():
    server = await started(idle_exit=60, ack_timeout=0.2)
    try:
        sender, silent = await server.peer(A, "a"), await server.peer(B, "b")

        answer = await sender.post(**message("b", "hi"))

        assert reason(answer) == "timeout" and "@b" in answer["error"]["message"]
        assert "may still receive" in answer["error"]["message"], "it is waiting there: the sender must not resend"
        assert await silent.waiting()
    finally:
        await server.aclose()


async def test_a_recipient_that_disconnects_while_handed_a_message_fails_the_send_at_once(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    pending = asyncio.ensure_future(sender.post(**message("b", "hi")))
    await recipient.waiting()
    await recipient.close()

    assert reason(await pending) == "gone"


async def test_a_sender_that_disconnects_mid_delivery_does_not_hurt_anyone(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    asyncio.ensure_future(sender.post(**message("b", "hi")))
    delivery = await recipient.waiting()
    await sender.close()
    await recipient.accept()

    assert delivery
    await eventually(lambda: [e.session_id for e in running.broker.roster.entries()] == [B])
    assert "error" not in await recipient.register(B, "b")


async def test_an_answer_to_nothing_the_broker_asked_is_ignored(running):
    peer = await running.peer(A, "a")

    await peer.send({"re": 12345, "accepted": True})
    await peer.send({"re": "x", "accepted": True})

    assert "error" not in await peer.call("leave")


async def test_messages_from_one_sender_arrive_in_the_order_they_were_sent(running):
    sender, recipient = await running.peer(A, "a"), await running.peer(B, "b")

    for n in range(5):
        pending = asyncio.ensure_future(sender.post(**message("b", f"m{n}")))
        await recipient.accept()
        await pending

    assert [r["text"] for r in recipient.requests()] == [f"m{n}" for n in range(5)]


async def test_many_senders_to_one_recipient_all_arrive_with_distinct_ids(running):
    recipient = await running.peer(B, "target")
    senders = [await running.peer(f"sender-{n}", f"s{n}") for n in range(6)]

    pending = [asyncio.ensure_future(s.post(**message("target", f"from {n}"))) for n, s in enumerate(senders)]
    for _ in senders:
        await recipient.accept()
    answers = await asyncio.gather(*pending)

    assert all("error" not in a for a in answers)
    ids = [r["id"] for r in recipient.requests()]
    assert len(set(ids)) == len(ids) == 6


async def test_a_sender_that_goes_over_the_rate_is_slowed_down_and_may_send_again_later():
    now = [1000.0]
    server = await started(idle_exit=60, clock=lambda: now[0])
    try:
        sender, recipient = await server.peer(A, "a"), await server.peer(B, "b")
        for n in range(RATE_LIMIT):
            assert "error" not in await sent(sender, recipient, "b", f"{n}")

        assert reason(await sender.post(**message("b", "one more"))) == "rate"

        now[0] += 61
        assert "error" not in await sent(sender, recipient, "b", "later")
    finally:
        await server.aclose()


async def test_the_rate_limit_is_per_connection():
    server = await started(idle_exit=60, clock=lambda: 0.0)
    try:
        busy, calm, recipient = await server.peer(A, "a"), await server.peer(C, "c"), await server.peer(B, "b")
        for n in range(RATE_LIMIT):
            await sent(busy, recipient, "b", f"{n}")

        assert reason(await busy.post(**message("b", "x"))) == "rate"
        assert "error" not in await sent(calm, recipient, "b", "still fine")
    finally:
        await server.aclose()


async def test_a_session_with_too_many_messages_waiting_is_told_busy_and_the_rest_are_not_queued_for_ever():
    server = await started(idle_exit=60, ack_timeout=5)
    server.broker.limits = Limits(rate_limit=1000)
    try:
        sender, silent = await server.peer(A, "a"), await server.peer(B, "b")
        waiting = [asyncio.ensure_future(sender.post(**message("b", f"m{n}"))) for n in range(MAX_WAITING)]
        await eventually(lambda: len(silent.requests()) == MAX_WAITING)

        answer = await sender.post(**message("b", "one too many"))

        assert reason(answer) == "busy" and answer["status"] == 503
        for task in waiting:
            task.cancel()
    finally:
        await server.aclose()


# -- coming and going --------------------------------------------------------------------------------------


async def test_a_broker_nobody_connects_to_exits_on_its_own():
    server = await started(idle_exit=0.15)
    try:
        await asyncio.wait_for(server.broker.wait_closed(), 2)
    finally:
        await server.aclose()


async def test_a_connected_session_keeps_the_broker_alive_and_its_departure_starts_the_clock():
    server = await started(idle_exit=0.2)
    try:
        peer = await server.peer(A, "a")
        await asyncio.sleep(0.5)
        assert not server.broker._stopped.is_set(), "still in use"

        await peer.close()

        await asyncio.wait_for(server.broker.wait_closed(), 2)
    finally:
        await server.aclose()


async def test_a_connection_that_has_registered_nothing_still_keeps_the_broker_alive():
    server = await started(idle_exit=0.2)
    try:
        idle = await RawPeer.connect(server.port)
        server.peers.append(idle)
        await asyncio.sleep(0.5)

        assert not server.broker._stopped.is_set()
        await idle.close()
        await asyncio.wait_for(server.broker.wait_closed(), 2)
    finally:
        await server.aclose()


async def test_a_session_arriving_just_before_the_deadline_cancels_the_exit():
    server = await started(idle_exit=0.3)
    try:
        await asyncio.sleep(0.2)
        await server.peer(A, "a")
        await asyncio.sleep(0.4)

        assert not server.broker._stopped.is_set()
    finally:
        await server.aclose()


async def test_stopping_and_closing_are_safe_to_repeat():
    server = await started(idle_exit=60)
    server.broker.stop()
    server.broker.stop()
    await server.broker.aclose()
    await server.broker.aclose()
    await server.aclose()


async def test_closing_drops_every_connection_and_cancels_what_was_in_flight():
    server = await started(idle_exit=60, ack_timeout=30)
    sender, recipient = await server.peer(A, "a"), await server.peer(B, "b")
    asyncio.ensure_future(sender.post(**message("b", "hi")))
    await recipient.waiting()

    await asyncio.wait_for(server.broker.aclose(), 5)

    assert await sender.ended() and await recipient.ended()
    await server.aclose()


async def test_a_connection_that_arrives_while_the_broker_is_closing_is_turned_away():
    server = await started(idle_exit=60)
    port = server.port
    await server.broker.aclose()

    with pytest.raises(OSError):
        await RawPeer.connect(port)
    await server.aclose()


# -- who a message is from ---------------------------------------------------------------------------------


async def test_a_message_from_a_session_is_from_the_session_its_key_belongs_to_whatever_the_body_says(running):
    sender, recipient = await running.peer(A, "alpha"), await running.peer(B, "beta")

    await sent(sender, recipient, "beta", "hi", **{"from": {"name": "somebody else"}})

    assert recipient.requests()[0]["from"]["session_id"] == A and recipient.requests()[0]["via"] == "agent"


async def test_a_key_that_is_not_the_brokers_is_refused(running):
    response = await http(
        running.port, "POST", "/messages", json={"to": "x", "text": "y"}, headers={"X-Session-Key": "guess"}
    )

    assert response.status_code == 401 and response.json()["error"]["reason"] == "auth"


async def test_a_session_that_has_not_said_who_it_is_cannot_send_even_with_its_key(running):
    await running.peer(B, "beta")
    stranger = await running.peer()

    answer = await stranger.post(**message("beta", "hi"))

    assert reason(answer) == "not_registered" and answer["status"] == 403


async def test_a_session_key_stops_working_when_its_connection_ends(running):
    sender, _ = await running.peer(A, "alpha"), await running.peer(B, "beta")
    key = sender.key

    await sender.close()
    await eventually(lambda: not running.broker.hub.by_key.get(key))

    response = await http(
        running.port, "POST", "/messages", json={"to": "beta", "text": "hi"}, headers={"X-Session-Key": key}
    )
    assert response.json()["error"]["reason"] == "auth"


async def test_an_external_source_with_no_session_can_send_and_is_named_as_it_says_it_is(running):
    recipient = await running.peer(B, "beta")

    pending = asyncio.ensure_future(
        http(running.port, "POST", "/messages", json={"to": "beta", "text": "build failed", "from": {"name": "CI Bot"}})
    )
    await recipient.accept()
    response = await pending

    assert response.status_code == 200 and response.json()["to"]["session_id"] == B
    delivery = recipient.requests()[0]
    assert delivery["via"] == "external" and delivery["hops"] == 1
    assert delivery["from"]["handle"] == "ci-bot" and delivery["from"]["title"] == "CI Bot"
    assert delivery["from"]["kind"] == "external"


@pytest.mark.parametrize("claim", [{"via": "user"}, {"via": "agent", "hops": 4}, {"via": "external", "hops": 9}])
async def test_an_external_source_cannot_pass_itself_off_as_a_reader_or_an_agent(running, claim):
    recipient = await running.peer(B, "beta")

    pending = asyncio.ensure_future(http(running.port, "POST", "/messages", json={"to": "beta", "text": "hi", **claim}))
    await recipient.accept()
    await pending

    assert recipient.requests()[0]["via"] == "external" and recipient.requests()[0]["hops"] == 1


async def test_a_zettcode_session_cannot_claim_to_be_external(running):
    sender, _ = await running.peer(A, "a"), await running.peer(B, "b")

    assert reason(await sender.post(**message("b", "hi", via="external"))) == "invalid"


async def test_an_external_source_without_a_name_is_called_external_and_a_hostile_name_is_cleaned(running):
    recipient = await running.peer(B, "beta")
    for sender in ({}, {"from": {"name": "\x1b[31mevil\x07" + "x" * 99}}, {"from": "not an object"}):
        pending = asyncio.ensure_future(
            http(running.port, "POST", "/messages", json={"to": "beta", "text": "hi", **sender})
        )
        await recipient.accept()
        await pending

    names = [d["from"]["title"] for d in recipient.requests()]
    assert names[0] == "external" and names[2] == "external"
    assert "\x1b" not in names[1] and len(names[1]) <= 40


async def test_an_external_program_that_registers_is_listed_and_can_be_answered(running):
    bot = await running.peer("nightly-1", "nightly bot")
    answer = await bot.register("nightly-1", "nightly bot", kind="external")
    me = await running.peer(A, "alpha")

    assert answer["handle"] == "nightly-bot"
    await eventually(lambda: any(e["kind"] == "external" for e in me.listed()))
    pending = asyncio.ensure_future(me.post(**message("nightly-bot", "report please")))
    delivery = await bot.accept()
    assert (await pending)["to"]["kind"] == "external"
    assert delivery["from"]["session_id"] == A and delivery["via"] == "agent"

    reply = asyncio.ensure_future(bot.post(**message("alpha", "here it is")))
    await me.accept()
    assert "error" not in await reply
    assert me.requests()[0]["via"] == "external" and me.requests()[0]["from"]["kind"] == "external"


async def test_a_kind_nobody_defined_is_read_as_a_zettcode_session(running):
    peer = await running.peer()

    await peer.register(A, "a", kind="robot")

    assert (
        running.broker.roster.of(running.broker.hub.sessions and next(iter(running.broker.hub.sessions))).kind
        == "zettcode"
    )


async def test_an_external_sender_is_throttled_by_the_name_it_gave(running):
    running.broker.limits = Limits(rate_limit=2)
    await running.peer(B, "beta")

    answers = [
        (
            await http(running.port, "POST", "/messages", json={"to": "nobody", "text": "x", "from": {"name": "bot"}})
        ).json()
        for _ in range(3)
    ]

    assert [a["error"]["reason"] for a in answers] == ["unknown", "unknown", "rate"]
