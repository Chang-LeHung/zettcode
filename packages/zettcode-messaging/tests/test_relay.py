"""The relay: a message from another session starts a turn, steers one, or waits in the inbox, and says which."""

from __future__ import annotations

from collections.abc import Callable

from zettcode.engine.delivery import Delivery
from zettcode.messaging.inbox import Inbox, Waiting
from zettcode.messaging.relay import Relay
from zettcode.modes import MODE_FOLLOWUP, MODE_STEER
from zettcode.relay import Relayed


def relayed(name: str = "peer", *, text: str | None = None, mode: str = MODE_STEER, direct: bool = False) -> Relayed:
    """Return a message as another session sends it."""
    return Relayed(sender_id=f"id-{name}", sender=name, text=text or f"from {name}", mode=mode, direct=direct)


class FakeDelivery(Delivery):
    """A runtime that runs nothing until told to."""

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
        self.running = False
        waiters, self.waiters = self.waiters, []
        for callback in waiters:
            callback()


class Front:
    """A front end with nothing running, and an inbox its starter drains into turns."""

    def __init__(self, *, cap: int = 64) -> None:
        self.delivery = FakeDelivery()
        self.inbox = Inbox(self.delivery, cap=cap)
        self.started: list[Waiting] = []
        self.waiting: list[Relayed] = []
        self.refuse_steer = False
        self.inbox.start_with(self._start)
        self.relay = Relay(
            busy=lambda: self.delivery.running,
            steer=self._steer,
            inbox=lambda: self.inbox,
            start=self._start_relayed,
            on_waiting=self.waiting.append,
        )

    def _start(self, item: Waiting) -> bool:
        self.started.append(item)
        self.delivery.running = True
        return True

    def _start_relayed(self, message: Relayed) -> None:
        """Run one message as a turn now, as a front end does when nothing runs."""
        self.started.append(Waiting(message.text, None, "session", message))
        self.delivery.running = True

    def _steer(self, message: Relayed) -> str | None:
        if self.refuse_steer:
            return None
        self.delivery.steered.append(message)
        return message.text


def test_an_idle_session_starts_a_turn_with_the_message():
    front = Front()

    receipt = front.relay.receive(relayed("bob"))

    assert receipt.accepted and receipt.disposition == "started"
    assert [item.message for item in front.started] == ["from bob"]
    assert isinstance(front.started[0].payload, Relayed), "the front end gets the message back, to frame it its way"


def test_a_busy_session_steers_a_message_that_asks_to_steer():
    front = Front()
    front.delivery.running = True

    receipt = front.relay.receive(relayed("bob", text="change course"))

    assert receipt.accepted and receipt.disposition == "steered"
    assert front.inbox.waiting == ()
    assert front.relay.steered[0][0] == "change course"


def test_a_follow_up_waits_in_the_inbox_while_a_request_runs():
    front = Front()
    front.delivery.running = True

    receipt = front.relay.receive(relayed("bob", text="later", mode=MODE_FOLLOWUP))

    assert receipt.accepted and receipt.disposition == "queued"
    assert [item.payload.text for item in front.inbox.waiting] == ["later"]
    assert [item.text for item in front.waiting] == ["later"], "the front end was told, so it can draw it"


def test_a_steer_a_request_refuses_waits_instead():
    front = Front()
    front.delivery.running = True
    front.refuse_steer = True

    receipt = front.relay.receive(relayed("bob", text="cannot be steered"))

    assert receipt.accepted and receipt.disposition == "queued"
    assert [item.payload.text for item in front.inbox.waiting] == ["cannot be steered"]


def test_a_full_inbox_is_refused_with_busy_so_the_broker_offers_it_again():
    front = Front(cap=2)
    front.delivery.running = True
    for index in range(2):
        front.relay.receive(relayed("bob", text=f"m{index}", mode=MODE_FOLLOWUP))

    receipt = front.relay.receive(relayed("bob", text="one more", mode=MODE_FOLLOWUP))

    assert not receipt.accepted and receipt.busy
    assert "waiting" in (receipt.reason or "")
    assert len(front.inbox.waiting) == 2


def test_a_message_the_request_adopted_is_not_queued_again():
    front = Front()
    front.delivery.running = True
    front.relay.receive(relayed("bob", text="adopted"))

    found = front.relay.adopted("adopted")

    assert found is not None and found.text == "adopted"
    assert front.relay.settle() == (), "it was read, so nothing comes back"


def test_a_steer_the_request_never_adopted_waits_for_the_next_turn():
    front = Front()
    front.delivery.running = True
    front.relay.receive(relayed("bob", text="lost"))

    returned = front.relay.settle()

    assert [item.text for item in returned] == ["lost"]
    assert [item.payload.text for item in front.inbox.waiting] == ["lost"]
    assert front.inbox.waiting[0].payload is not None, "it stays a relayed message, not a plain event"


def test_messages_that_waited_are_answered_together():
    front = Front()
    front.delivery.running = True
    front.relay.receive(relayed("bob", text="one", mode=MODE_FOLLOWUP))
    front.relay.receive(relayed("bob", text="two", mode=MODE_FOLLOWUP))

    front.delivery.finish()

    assert len(front.started) == 1, "a window that was busy is answered once"
    merged = front.started[0].payload
    assert merged is not None and "one" in merged.text and "two" in merged.text


def test_nothing_starts_while_a_request_runs():
    front = Front()
    front.delivery.running = True
    front.relay.receive(relayed("bob", mode=MODE_FOLLOWUP))

    assert front.relay.start_next() is False
    assert len(front.inbox.waiting) == 1


def test_a_sequence_of_receipts_matches_what_the_sender_is_told():
    """The one field every sender reads: accepted, and what happened to it."""
    front = Front()
    idle = front.relay.receive(relayed("bob"))
    front.delivery.running = True
    steered = front.relay.receive(relayed("eve"))
    queued = front.relay.receive(relayed("eve", mode=MODE_FOLLOWUP))

    assert [receipt.disposition for receipt in (idle, steered, queued)] == ["started", "steered", "queued"]
    assert all(receipt.accepted for receipt in (idle, steered, queued))


def test_a_process_with_no_inbox_refuses_a_message_rather_than_dropping_it():
    """Nothing runs, so the front end could start it — but a message that has to wait has nowhere to wait."""
    relay = Relay(busy=lambda: True, steer=lambda message: None, inbox=lambda: None)

    receipt = relay.receive(relayed("bob", mode=MODE_FOLLOWUP))

    assert not receipt.accepted and "inbox" in (receipt.reason or "")


def test_an_unadopted_steer_is_not_lost_to_a_full_queue():
    """The cap is for new senders; a message the run had already taken must come back whatever the queue holds."""
    front = Front(cap=1)
    front.delivery.running = True
    front.relay.receive(relayed("bob", text="steered, not read"))
    front.relay.receive(relayed("eve", text="waiting", mode=MODE_FOLLOWUP))
    assert len(front.inbox.waiting) == 1

    returned = front.relay.settle()

    assert [item.text for item in returned] == ["steered, not read"]
    assert [item.payload.text for item in front.inbox.waiting] == ["waiting", "steered, not read"]


def test_an_idle_session_starts_through_the_queue_and_not_past_it():
    """Nothing runs, but a message already waiting is served before a new one."""
    front = Front()
    front.inbox.start_with(lambda item: False)  # the front end cannot start now, so it waits
    front.relay.receive(relayed("eve", text="first", mode=MODE_FOLLOWUP))

    front.inbox.start_with(front._start)  # the front end can start again: the queue drains in order
    front.relay.receive(relayed("bob", text="second", mode=MODE_FOLLOWUP))

    assert [item.message for item in front.started] == ["first"], "the waiting one goes first"
    assert [item.payload.text for item in front.inbox.waiting] == ["second"]
