"""What arrives from another session, and what this one does about it.

The broker hands one message at a time to the front end that owns the session's connection, and the answer is a
receipt the sender's agent reads. The decision has three parts and this class owns the two the inbox cannot know:

* whether the message can steer the request that runs — the front end supplies that answer, because steering a message
  from another session goes through the framing a plain prompt does not have;
* whether it was adopted, so a steer the run never read waits for the next turn instead of being lost;
* what the sender is told, and what a front end draws while it waits.

Everything else — the queue, the order, the per-message cap and starting the turns — is the inbox's
(:class:`zettcode.messaging.inbox.Inbox`), so a message from another session and an event from elsewhere wait in one
place and a front end has one starter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zettcode.broker.client import Receipt
from zettcode.modes import MODE_STEER
from zettcode.relay import Relayed

from .inbox import FULL, QUEUED, STARTED, Inbox, Waiting

__all__ = ["PREVIEW", "Relay"]

#: Characters of a waiting message a front end shows, so a reader can tell which one it is.
PREVIEW = 60

#: Hand a message to the request in flight: the text the run will report it by, or ``None`` when it was not taken.
Steer = Callable[[Relayed], "str | None"]

#: The inbox to put messages in; ``None`` in a process whose messaging part did not load.
InboxOf = Callable[[], "Inbox | None"]


@dataclass(frozen=True, slots=True)
class _Steered:
    """A message handed to the running request, and the text that run will report it by."""

    key: str
    relayed: Relayed


class Relay:
    """The receipt a message from another session gets, and the record of what the running request took.

    Args:
        busy: Whether a request is running here.
        steer: Hands one message to that request; the text it reports the message by, or ``None`` when it refused.
        inbox: The runtime's inbox, read when a message is delivered (a front end may build its client lazily).
        start: Runs one message as a turn now; only used while the front end says nothing runs.
        on_waiting: Told about each message that starts waiting, so a front end can draw it.
    """

    def __init__(
        self,
        *,
        busy: Callable[[], bool],
        steer: Steer,
        inbox: InboxOf,
        start: Callable[[Relayed], None] = lambda relayed: None,
        on_waiting: Callable[[Relayed], None] = lambda relayed: None,
    ) -> None:
        self._busy = busy
        self._steer = steer
        self._inbox_of = inbox
        self._start = start
        self._on_waiting = on_waiting
        self._steered: list[_Steered] = []

    @property
    def waiting(self) -> tuple[Relayed, ...]:
        """Return the messages from other sessions waiting for the request in flight, oldest first."""
        inbox = self._inbox_of()
        if inbox is None:
            return ()
        return tuple(item.payload for item in inbox.waiting if isinstance(item.payload, Relayed))

    @property
    def steered(self) -> tuple[tuple[str, Relayed], ...]:
        """Return the messages handed to the request in flight, each with the text it will report it by."""
        return tuple((item.key, item.relayed) for item in self._steered)

    def receive(self, relayed: Relayed) -> Receipt:
        """Take one message another session sent: start a turn, steer the running one, or hold it.

        Called on the loop with the sender waiting for the answer; it must not block.
        """
        inbox = self._inbox_of()
        if inbox is None and not self._busy():
            # No queue to hand it to, and nothing running: the front end starts it, the way it starts a prompt.
            self._start(relayed)
            return Receipt(True, disposition="started")
        if inbox is None:
            return Receipt(False, "this session has no inbox: the messaging plugin did not load")
        if self._busy() and relayed.mode == MODE_STEER:
            key = self._steer(relayed)
            if key is not None:
                self._steered.append(_Steered(key, relayed))
                return Receipt(True, disposition="steered")
        outcome = self._queue(inbox, relayed)
        if outcome == FULL:
            return Receipt(
                False,
                f"this session already has {len(inbox.waiting)} messages waiting; try again when it is less busy",
                busy=True,
            )
        if outcome == QUEUED:
            self._on_waiting(relayed)
        return Receipt(True, disposition="started" if outcome == STARTED else "queued")

    def hold(self, key: str, relayed: Relayed) -> None:
        """Record a message handed to the request in flight, for a front end that steered it itself."""
        self._steered.append(_Steered(key, relayed))

    def adopted(self, text: str) -> Relayed | None:
        """Take the message the running request just adopted, so a front end can draw it as one."""
        for index, item in enumerate(self._steered):
            if item.key == text:
                del self._steered[index]
                return item.relayed
        return None

    def settle(self) -> tuple[Relayed, ...]:
        """Put back what the run never adopted, after it ended, and return them in the order handed over.

        A message a run adopted is not here — it left when the run reported it — so nothing the model has read is run
        again. They go back into the inbox in the order they were handed over, and the next turn answers them.
        """
        if not self._steered:
            return ()
        inbox = self._inbox_of()
        waiting = [item.relayed for item in self._steered]
        self._steered.clear()
        if inbox is not None:
            # Already accepted, so the cap does not apply: only a new sender is refused when the queue is full.
            inbox.requeue([Waiting(relayed.text, None, "session", relayed) for relayed in waiting])
        for relayed in waiting:
            self._on_waiting(relayed)
        return tuple(waiting)

    def start_next(self) -> bool:
        """Ask the inbox to start the next waiting turn, and say whether it did.

        The front end's own chain calls this after a turn ends, as a second chance for the runtime's wake-up, which
        arrives before the front end is idle.
        """
        inbox = self._inbox_of()
        if inbox is None:
            return False
        before = len(inbox.waiting)
        inbox.drain()
        return len(inbox.waiting) < before

    def _queue(self, inbox: Inbox, relayed: Relayed) -> str:
        """Put one message in the inbox as a follow-up, whatever the sender asked for."""
        return inbox.deliver(relayed.text, mode="followup", payload=relayed, origin="session")
