"""A message for a session whose inbox is full is kept by the broker and offered again when there is room."""

from __future__ import annotations

import asyncio
from typing import Any

from broker_helpers import eventually, reason, started
from zettcode.broker import hub as hub_module
from zettcode.broker.protocol import Limits
from zettcode.broker.store import Store

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


async def two(**options: Any):
    server = await started(idle_exit=60, **options)
    server.broker.limits = Limits(rate_limit=1000)
    server.broker.hub.retry_min = 0.02
    server.broker.hub.retry_max = 0.05
    return server, await server.peer(A, "a"), await server.peer(B, "b")


async def test_a_full_inbox_has_the_message_held_and_delivered_when_it_has_room():
    server, sender, receiver = await two()
    try:
        pending = asyncio.ensure_future(sender.post("b", "first"))
        await receiver.busy()
        answer = await pending

        assert answer["status"] == 200 and answer["disposition"] == "held"
        [stored] = server.broker.hub.store.recent()
        assert stored["status"] == "held" and server.broker.hub.store.held_count(B) == 1

        # The same message is offered again, with no second send from anyone.
        again = await receiver.busy()
        delivered = await receiver.accept("queued")

        assert delivered["text"] == "first" and again["text"] == "first"
        await eventually(lambda: server.broker.hub.store.held_count() == 0)
        [stored] = server.broker.hub.store.recent()
        assert (stored["status"], stored["disposition"]) == ("delivered", "queued")
    finally:
        await server.aclose()


async def test_messages_behind_a_held_one_wait_behind_it_and_arrive_in_order():
    server, sender, receiver = await two()
    try:
        first = asyncio.ensure_future(sender.post("b", "one"))
        await receiver.busy()
        await first
        second = await sender.post("b", "two")
        third = await sender.post("b", "three")

        assert second["disposition"] == "held" and third["disposition"] == "held"
        texts = []
        for _ in range(3):
            texts.append((await receiver.accept("queued"))["text"])

        assert texts == ["one", "two", "three"]
        await eventually(lambda: server.broker.hub.store.held_count() == 0)
    finally:
        await server.aclose()


async def test_a_refusal_that_is_not_about_room_is_still_a_refusal_and_nothing_is_held():
    server, sender, receiver = await two()
    try:
        pending = asyncio.ensure_future(sender.post("b", "no"))
        await receiver.refuse("not today")
        answer = await pending

        assert reason(answer) == "rejected" and server.broker.hub.store.held_count() == 0
    finally:
        await server.aclose()


async def test_held_messages_survive_a_restart_and_are_delivered_when_the_session_returns(tmp_path):
    path = tmp_path / "broker.db"
    server, sender, receiver = await two(store=Store(path))
    pending = asyncio.ensure_future(sender.post("b", "wait for me"))
    await receiver.busy()
    await pending
    await server.aclose()

    server = await started(idle_exit=60, store=Store(path))
    try:
        returned = await server.peer(B, "b")
        delivered = await returned.accept("started")

        assert delivered["text"] == "wait for me"
        await eventually(lambda: server.broker.hub.store.held_count() == 0)
    finally:
        await server.aclose()


async def test_a_session_that_leaves_keeps_its_held_messages_for_when_it_is_back():
    server, sender, receiver = await two()
    try:
        pending = asyncio.ensure_future(sender.post("b", "later"))
        await receiver.busy()
        await pending
        await receiver.close()
        await eventually(lambda: server.broker.roster.owner_of(B) is None)
        assert server.broker.hub.store.held_count(B) == 1

        back = await server.peer(B, "b")
        assert (await back.accept("started"))["text"] == "later"
    finally:
        await server.aclose()


async def test_a_session_may_have_only_so_many_held_and_the_sender_is_then_told_it_is_busy(monkeypatch):
    monkeypatch.setattr(hub_module, "MAX_HELD", 2)
    server, sender, receiver = await two()
    try:
        first = asyncio.ensure_future(sender.post("b", "1"))
        await receiver.busy()
        await first
        assert (await sender.post("b", "2"))["disposition"] == "held"

        answer = await sender.post("b", "3")

        assert reason(answer) == "busy" and answer["status"] == 503
    finally:
        await server.aclose()


async def test_a_group_message_is_held_for_a_member_whose_inbox_is_full():
    server, sender, receiver = await two()
    try:
        made = await sender.http.post("/groups", json={"action": "create", "name": "team", "members": ["b"]})
        assert made.status_code == 200
        pending = asyncio.ensure_future(sender.http.post("/messages", json={"group": "team", "text": "hi all"}))
        await receiver.busy()
        answer = (await pending).json()

        assert answer["delivered"][0]["disposition"] == "held" and not answer["failed"]
        assert (await receiver.accept("started"))["text"] == "hi all"
    finally:
        await server.aclose()


async def test_a_held_message_the_recipient_never_answers_is_recorded_as_unconfirmed_not_failed():
    server, sender, receiver = await two(ack_timeout=0.2)
    try:
        pending = asyncio.ensure_future(sender.post("b", "maybe"))
        await receiver.busy()
        await pending
        await receiver.waiting()  # the offer made again: it is not answered

        await eventually(lambda: server.broker.hub.store.held_count() == 0)

        [stored] = server.broker.hub.store.recent()
        assert stored["status"] == "unconfirmed" and stored["disposition"] == "timeout"
    finally:
        await server.aclose()


def test_a_history_row_that_says_held_with_nothing_linked_to_it_becomes_unconfirmed_when_a_broker_starts(tmp_path):
    store = Store(tmp_path / "broker.db")
    for text in ("lost link", "still held", "unlinked but waiting"):
        stored = store.add_message(
            sender=("a", "a", ""),
            kind="session",
            to=("b", "b", ""),
            recipients=["b"],
            text=text,
            via="agent",
            hops=1,
            mode="followup",
            status="held",
            disposition="held",
        )
        if text == "still held":
            store.link_held(store.hold("b", {"text": text}), stored["id"])
        if text == "unlinked but waiting":
            store.hold("b", {"text": text})

    hub_module.Hub(store=store)

    assert [m["status"] for m in store.recent()] == ["unconfirmed", "held", "unconfirmed"]
    assert store.held_count("b") == 2, "nothing that is still waiting is dropped"


def test_messages_held_for_longer_than_the_limit_are_dropped_when_a_broker_starts(tmp_path):
    clock = {"now": 1000.0}
    store = Store(tmp_path / "broker.db", clock=lambda: clock["now"])
    message = store.add_message(
        sender=("a", "a", ""),
        kind="session",
        to=("b", "b", ""),
        recipients=["b"],
        text="old",
        via="agent",
        hops=1,
        mode="followup",
        status="held",
        disposition="held",
    )
    row = store.hold("b", {"text": "old"})
    store.link_held(row, message["id"])
    clock["now"] = 1000.0 + hub_module.HELD_TTL / 2
    fresh = store.hold("b", {"text": "recent"})

    clock["now"] = 1000.0 + hub_module.HELD_TTL + 10
    hub_module.Hub(store=store)

    assert store.held_count() == 1 and store.next_held("b")["id"] == fresh
    assert store.recent()[0]["status"] == "expired"
