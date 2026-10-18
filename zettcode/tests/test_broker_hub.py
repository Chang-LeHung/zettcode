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
