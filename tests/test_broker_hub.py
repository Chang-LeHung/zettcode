"""The hub on its own: no socket, no web server. Sessions are queues, and a test is the other end of each."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from zettcode.broker.hub import MAX_QUEUED, Hub, Session
from zettcode.broker.protocol import PROTOCOL_VERSION, Refused

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


class Line:
    """The other end of one session: what the hub pushed to it, and how to answer."""

    def __init__(self, hub: Hub) -> None:
        self.closed: list[int] = []
        self.session = hub.admit(self.closed.append)
        self.hub = hub

    def pushed(self, op: str | None = None) -> list[dict[str, Any]]:
        lines = []
        while not self.session.outbox.empty():
            lines.append(self.session.outbox.get_nowait())
        self._seen = getattr(self, "_seen", []) + lines
        return [x for x in self._seen if op is None or x["op"] == op]

    def say(self, **line: Any) -> None:
        self.hub.hear(self.session, line)

    def register(self, session_id: str, title: str = "", **more: Any) -> None:
        self.say(op="session", n=1, session_id=session_id, title=title, **more)

    def ack(self, accepted: bool = True, **more: Any) -> None:
        delivery = self.pushed("deliver")[-1]
        self.say(op="ack", id=delivery["id"], accepted=accepted, **more)


@pytest.fixture
def hub() -> Hub:
    return Hub(ack_timeout=0.3)


def test_a_new_connection_is_greeted_with_its_key_the_limits_and_then_who_is_here(hub):
    other = Line(hub)
    other.register(A, "alpha")
    new = Line(hub)

    hello, roster = new.pushed()[:2]

    assert hello["op"] == "hello" and hello["protocol"] == PROTOCOL_VERSION and hello["key"] == new.session.key
    assert hello["limits"]["max_text"] > 0
    assert [e["handle"] for e in roster["sessions"]] == ["alpha"]
    assert hub.by_key[new.session.key] is new.session


def test_registering_answers_the_session_and_tells_everyone_once_only_when_something_changed(hub):
    one, two = Line(hub), Line(hub)
    two.pushed()

    one.register(A, "alpha")
    one.register(A, "alpha")

    assert one.pushed("done")[0]["handle"] == "alpha"
    assert len(two.pushed("roster")) == 2, "the greeting's, and one for the change; the repeat changes nothing"


def test_a_refusal_is_pushed_to_the_session_with_the_number_it_asked_under(hub):
    line = Line(hub)

    line.say(op="session", n=7, session_id="not valid!")

    refused = line.pushed("refused")[0]
    assert refused["n"] == 7 and refused["error"]["reason"] == "invalid"


def test_what_the_hub_does_not_understand_is_ignored(hub):
    line = Line(hub)
    line.pushed()

    for odd in ({"op": "dance"}, {}, {"op": None}, {"op": "ack", "id": "x"}, {"op": "ack", "id": 99}):
        line.say(**odd)

    assert line.pushed() == line._seen and not line.closed


def test_releasing_a_connection_forgets_its_session_and_its_key_and_tells_the_others(hub):
    gone, stays = Line(hub), Line(hub)
    gone.register(A, "alpha")
    stays.pushed()

    hub.release(gone.session)

    assert not hub.roster.entries() and gone.session.key not in hub.by_key
    assert stays.pushed("roster")[-1]["sessions"] == []


def test_nobody_is_told_who_left_when_the_broker_itself_is_going(hub):
    gone, stays = Line(hub), Line(hub)
    gone.register(A, "alpha")
    stays.pushed()
    hub.closing = True

    hub.release(gone.session)

    assert len(stays.pushed("roster")) == 2, "the greeting's, and the one for the registration; none for leaving"


def test_a_session_that_stopped_reading_is_closed_not_buffered_for_ever(hub):
    line = Line(hub)

    for n in range(MAX_QUEUED + 1):
        line.session.push({"op": "roster", "n": n})

    assert line.closed == [1008]


async def test_a_message_is_handed_over_and_the_sender_is_told_only_after_the_ack(hub):
    sender, recipient = Line(hub), Line(hub)
    sender.register(A, "alpha")
    recipient.register(B, "beta")

    pending = asyncio.ensure_future(hub.send(sender.session.key, {"to": "beta", "text": "hi", "hops": 2}))
    await asyncio.sleep(0.05)
    assert not pending.done()
    delivery = recipient.pushed("deliver")[0]
    assert delivery["text"] == "hi" and delivery["hops"] == 3 and delivery["from"]["session_id"] == A
    recipient.ack(disposition="queued")

    assert (await pending)["disposition"] == "queued"


async def test_a_recipient_that_never_acks_times_out(hub):
    sender, silent = Line(hub), Line(hub)
    sender.register(A, "alpha")
    silent.register(B, "beta")

    with pytest.raises(Refused) as refused:
        await hub.send(sender.session.key, {"to": "beta", "text": "hi"})

    assert refused.value.reason == "timeout" and not silent.session.waiting


async def test_a_recipient_that_leaves_with_a_message_waiting_fails_the_send_at_once(hub):
    sender, leaving = Line(hub), Line(hub)
    sender.register(A, "alpha")
    leaving.register(B, "beta")

    pending = asyncio.ensure_future(hub.send(sender.session.key, {"to": "beta", "text": "hi"}))
    await asyncio.sleep(0.05)
    hub.release(leaving.session)

    with pytest.raises(Refused) as refused:
        await pending
    assert refused.value.reason == "gone"


async def test_an_outsider_is_named_by_what_it_says_and_cannot_claim_to_be_anything_else(hub):
    recipient = Line(hub)
    recipient.register(B, "beta")

    pending = asyncio.ensure_future(
        hub.send(None, {"to": "beta", "text": "hi", "via": "user", "hops": 5, "from": {"name": "CI"}})
    )
    await asyncio.sleep(0.05)
    delivery = recipient.pushed("deliver")[0]
    recipient.ack()
    await pending

    assert delivery["via"] == "external" and delivery["hops"] == 1 and delivery["from"]["handle"] == "ci"


async def test_the_allowance_belongs_to_the_sender_not_to_the_broker(hub):
    from zettcode.broker.protocol import Limits

    hub.limits = Limits(rate_limit=1)
    sender = Line(hub)
    sender.register(A, "alpha")

    with pytest.raises(Refused, match="unknown|no active"):
        await hub.send(sender.session.key, {"to": "nobody", "text": "x"})
    with pytest.raises(Refused) as refused:
        await hub.send(sender.session.key, {"to": "nobody", "text": "x"})
    assert refused.value.reason == "rate"
    with pytest.raises(Refused) as other:
        await hub.send(None, {"to": "nobody", "text": "x", "from": {"name": "somebody else"}})
    assert other.value.reason == "unknown"


def test_the_listing_is_the_roster_and_the_limits(hub):
    line = Line(hub)
    line.register(A, "alpha")

    listing = hub.listing()

    assert [s["handle"] for s in listing["sessions"]] == ["alpha"] and "max_text" in listing["limits"]


def test_a_session_is_a_plain_object_with_a_key_of_its_own():
    one, two = Session(1, lambda code: None), Session(2, lambda code: None)

    assert one.key != two.key and len(one.key) >= 16


async def _delivered(hub, body, *, direct_peer):
    sender, other = Line(hub), Line(hub)
    sender.register(A, "alpha")
    other.register(B, "beta", direct=direct_peer)
    pending = asyncio.ensure_future(hub.send(sender.session.key, {"to": "beta", **body}))
    await asyncio.sleep(0)
    delivery = other.pushed("deliver")[-1]
    other.ack()
    await pending
    return delivery


async def test_a_direct_message_reaches_only_a_session_that_said_it_can_take_one_and_only_from_a_reader(hub):
    capable = await _delivered(hub, {"text": "hi", "via": "user", "direct": True}, direct_peer=True)

    assert capable["direct"] is True and capable["via"] == "user"


async def test_the_direct_flag_is_dropped_for_a_session_that_cannot_run_it(hub):
    incapable = await _delivered(hub, {"text": "hi", "via": "user", "direct": True}, direct_peer=False)

    assert "direct" not in incapable


async def test_an_agent_cannot_make_its_message_direct(hub):
    sneaky = await _delivered(hub, {"text": "hi", "via": "agent", "direct": True}, direct_peer=True)

    assert "direct" not in sneaky


def test_a_session_announces_whether_it_takes_direct_messages_in_the_roster(hub):
    line, watcher = Line(hub), Line(hub)
    line.register(A, "alpha", direct=True)

    assert watcher.pushed("roster")[-1]["sessions"][0]["direct"] is True


# -- watching a turn ---------------------------------------------------------------------------------------
def test_a_session_is_told_how_many_watch_it_and_a_watcher_is_passed_what_its_turn_says(hub):
    worker, watcher = Line(hub), Line(hub)
    worker.register(A, "alpha")
    worker.pushed()

    watcher.say(op="watch", n=1, session_id=A)
    worker.say(op="stream", event={"t": "text", "text": "hi"})

    assert worker.pushed("watched")[-1]["count"] == 1
    assert watcher.pushed("stream") == [{"op": "stream", "session_id": A, "event": {"t": "text", "text": "hi"}}]


def test_nothing_is_passed_on_when_nobody_watches_and_the_session_is_told_so(hub):
    worker, watcher = Line(hub), Line(hub)
    worker.register(A, "alpha")
    watcher.say(op="watch", n=1, session_id=A)
    watcher.say(op="unwatch", n=2, session_id=A)

    worker.say(op="stream", event={"t": "begin"})

    assert worker.pushed("watched")[-1]["count"] == 0 and not watcher.pushed("stream")


def test_a_session_that_registers_after_being_watched_is_told_it_is(hub):
    watcher, worker = Line(hub), Line(hub)
    watcher.say(op="watch", n=1, session_id=A)

    worker.register(A, "alpha")

    assert worker.pushed("watched")[-1]["count"] == 1


def test_a_watcher_that_leaves_is_forgotten_and_the_session_told(hub):
    worker, watcher = Line(hub), Line(hub)
    worker.register(A, "alpha")
    watcher.say(op="watch", n=1, session_id=A)

    hub.release(watcher.session)

    assert worker.pushed("watched")[-1]["count"] == 0


def test_a_stream_line_that_is_malformed_oversized_or_from_an_unregistered_connection_is_ignored(hub):
    worker, watcher, stranger = Line(hub), Line(hub), Line(hub)
    worker.register(A, "alpha")
    watcher.say(op="watch", n=1, session_id=A)

    worker.say(op="stream", event="text")
    worker.say(op="stream", event={"t": "nonsense"})
    worker.say(op="stream", event={"t": "text", "text": "x" * 20_000})
    stranger.say(op="stream", event={"t": "text", "text": "hi"})

    assert not watcher.pushed("stream") and not worker.closed and not stranger.closed


def test_watching_a_session_id_that_is_not_one_is_refused(hub):
    watcher = Line(hub)

    watcher.say(op="watch", n=3, session_id="not valid!")

    assert watcher.pushed("refused")[0]["error"]["reason"] == "invalid"


def test_a_watcher_that_is_far_behind_misses_stream_lines_and_is_not_dropped_for_it(hub):
    worker, watcher = Line(hub), Line(hub)
    worker.register(A, "alpha")
    watcher.say(op="watch", n=1, session_id=A)

    for _ in range(1000):
        worker.say(op="stream", event={"t": "text", "text": "."})

    assert not watcher.closed and watcher.session.outbox.qsize() <= 128 + 4


def test_watching_the_same_session_again_changes_nothing_and_says_nothing(hub):
    worker, watcher = Line(hub), Line(hub)
    worker.register(A, "alpha")
    watcher.say(op="watch", session_id=A)
    worker.pushed()

    for _ in range(300):
        watcher.say(op="watch", session_id=A)

    assert not worker.closed and not watcher.closed
    assert [line["count"] for line in worker.pushed("watched")] == [0, 1], "told on registering and once on watching"


def test_a_session_may_watch_only_so_many_others(hub):
    from zettcode.broker.hub import MAX_WATCHING

    watcher = Line(hub)
    for number in range(MAX_WATCHING):
        watcher.say(op="watch", session_id=f"s{number}")

    watcher.say(op="watch", n=9, session_id="one-too-many")

    assert watcher.pushed("refused")[-1]["error"]["reason"] == "busy"


async def test_the_sender_is_told_whether_the_message_went_as_a_direct_prompt(hub):
    sender, other = Line(hub), Line(hub)
    sender.register(A, "alpha")
    other.register(B, "beta", direct=True)

    pending = asyncio.ensure_future(
        hub.send(sender.session.key, {"to": "beta", "text": "hi", "via": "user", "direct": True})
    )
    await asyncio.sleep(0)
    other.ack()
    sent = await pending

    assert sent["direct"] is True
