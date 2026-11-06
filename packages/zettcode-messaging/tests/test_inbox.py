"""The inbox: a steer goes into the request that runs, anything else waits for the next turn."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from zettcode.engine.delivery import Delivery
from zettcode.messaging.inbox import INBOX, QUEUED, STARTED, STEERED, Inbox, Waiting


class FakeDelivery(Delivery):
    """A runtime that runs nothing until told to, and remembers what it was handed."""

    def __init__(self) -> None:
        self.running = False
        self.steered: list[object] = []
        self.waiters: list[Callable[[], None]] = []

    @property
    def busy(self) -> bool:
        return self.running

    def steer(self, message: object) -> str | None:
        if not self.running:
            return None
        self.steered.append(message)
        return message if isinstance(message, str) else getattr(message, "text", "")

    def when_idle(self, callback: Callable[[], None]) -> Callable[[], None]:
        if not self.running:
            callback()
            return lambda: None
        self.waiters.append(callback)
        return lambda: self.waiters.remove(callback)

    def finish(self) -> None:
        """End the request, as the runtime does when its last stream is consumed."""
        self.running = False
        waiters, self.waiters = self.waiters, []
        for callback in waiters:
            callback()


def test_a_steer_goes_into_the_request_that_runs_and_is_not_queued():
    delivery = FakeDelivery()
    delivery.running = True
    inbox = Inbox(delivery)

    assert inbox.deliver("look at the diff") == STEERED
    assert delivery.steered == ["look at the diff"]
    assert inbox.waiting == ()


def test_a_followup_waits_and_starts_when_the_request_ends():
    delivery = FakeDelivery()
    delivery.running = True
    inbox = Inbox(delivery)
    started: list[Waiting] = []
    inbox.start_with(lambda item: started.append(item) or True)

    assert inbox.deliver("then run the tests", mode="followup") == QUEUED
    assert started == [], "a follow-up does not start on top of a running request"
    assert [item.message for item in inbox.waiting] == ["then run the tests"]

    delivery.finish()

    assert [item.message for item in started] == ["then run the tests"]
    assert inbox.waiting == ()


def test_messages_keep_their_order_and_one_at_a_time():
    delivery = FakeDelivery()
    delivery.running = True
    inbox = Inbox(delivery)
    started: list[str] = []

    def start(item: Waiting) -> bool:
        """Start one turn, and make the runtime busy as a real starter does (the SDK's schedules a task)."""
        started.append(str(item.message))
        delivery.running = True
        return True

    inbox.start_with(start)

    inbox.deliver("one", mode="followup")
    inbox.deliver("two", mode="followup")
    delivery.finish()

    assert started == ["one"], "the next message waits for the turn this one started"
    assert [item.message for item in inbox.waiting] == ["two"]

    delivery.finish()

    assert started == ["one", "two"]
    assert inbox.waiting == ()


def test_a_starter_that_cannot_start_now_leaves_the_message_waiting():
    delivery = FakeDelivery()
    inbox = Inbox(delivery)
    inbox.start_with(lambda item: False)

    assert inbox.deliver("hello") == QUEUED
    assert [item.message for item in inbox.waiting] == ["hello"]


def test_an_idle_agent_starts_a_turn_either_way():
    delivery = FakeDelivery()
    inbox = Inbox(delivery)
    inbox.start_with(lambda item: True)

    assert inbox.deliver("now", mode="followup") == STARTED
    assert inbox.waiting == ()


def test_a_message_that_waited_for_a_starter_starts_as_soon_as_one_registers():
    delivery = FakeDelivery()
    inbox = Inbox(delivery)
    assert inbox.deliver("early") == QUEUED

    started: list[object] = []
    inbox.start_with(lambda item: started.append(item.message) or True)

    assert started == ["early"] and inbox.waiting == ()


def test_a_mode_that_is_not_steer_or_followup_is_refused():
    inbox = Inbox(FakeDelivery())

    with pytest.raises(ValueError, match="mode is 'steer' or 'followup'"):
        inbox.deliver("hello", mode="sideways")


def test_the_plugin_provides_the_inbox_even_with_no_messenger(tmp_path):
    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine.plugins.context import PluginContext
    from zettcode.messaging.plugin import Messaging

    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
    )
    delivery = FakeDelivery()
    ctx = PluginContext(config, {DELIVERY_NAME: delivery})

    Messaging().activate(ctx)

    inbox = ctx.services[INBOX]
    assert isinstance(inbox, Inbox) and inbox.waiting == ()


#: The engine's service name, imported separately so this module's own FakeDelivery reads clearly.
DELIVERY_NAME = "delivery"
