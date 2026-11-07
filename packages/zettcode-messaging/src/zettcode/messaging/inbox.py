"""The inbox: what an event outside the conversation hands the agent, steered in or queued for the next turn.

The engine's :class:`~zettcode.engine.delivery.Delivery` knows two things — whether a request is running, and how to
hand a message to it — but not what to do with a message that arrives when nothing runs. That is this class: a steer
goes straight into the request; anything else waits, in order, and the front end that owns the turn loop starts the next
one when the inbox says so (``start_with``), which is the same starter it uses for a reader's prompt.

This is the one queue. A message another session sent (see :mod:`zettcode.messaging.relay`) is a :class:`Waiting` whose
``payload`` is that message: the front-end starter hands it back to the code that knows how to run it, and messages that
waited in a window that was busy are answered together, as one turn, the way the broker has always done it.

The queue is one per runtime, provided as the ``INBOX`` service, so the broker's incoming path, a trigger and a program
using the SDK all deliver the same way and cannot start two turns at once. The contract a front end and this class
share — the name, :class:`Waiting` and the abstract base — is :mod:`zettcode.engine.inbox`, so neither side imports the
other's distribution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from zettcode.engine.delivery import Delivery
from zettcode.engine.inbox import FULL, INBOX, QUEUED, STARTED, STEERED, Waiting
from zettcode.engine.inbox import Inbox as InboxContract
from zettcode.modes import MODE_STEER, MODES
from zettcode.relay import Relayed, batch_size, merge

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.messages import UserMessage

__all__ = ["FULL", "INBOX", "MAX_WAITING", "QUEUED", "STARTED", "STEERED", "Inbox", "Waiting"]

#: How many messages may wait; the rest are refused (:data:`FULL`) and the broker offers them again later.
MAX_WAITING = 64


class Inbox(InboxContract):
    """Steer the request in flight, or hold messages until one ends and a front end can start the next turn.

    Args:
        delivery: The runtime's delivery: whether a request runs, and how a message reaches it.
        cap: How many may wait. The rest are refused with :data:`FULL`, which the broker turns into "busy, offer it
            again", so a front end never holds an unbounded list.
    """

    def __init__(self, delivery: Delivery, *, cap: int = MAX_WAITING) -> None:
        self._delivery = delivery
        self._cap = cap
        self._waiting: list[Waiting] = []
        self._starter: Callable[[Waiting], bool] | None = None
        self._forget: Callable[[], None] | None = None

    @property
    def waiting(self) -> tuple[Waiting, ...]:
        """Return the messages held for the next turn, in the order they arrived."""
        return tuple(self._waiting)

    @property
    def full(self) -> bool:
        """Return whether the queue is at its cap, so a new message would be refused."""
        return len(self._waiting) >= self._cap

    def start_with(self, starter: Callable[[Waiting], bool]) -> None:
        """Register what starts a turn from a waiting message, and drain anything already waiting.

        The front end that owns the turn loop passes its own starter — the one a reader's prompt goes through — so a
        follow-up is an ordinary turn and not a second kind of run. A starter that returns ``False`` says it could not
        start one now; the message then stays waiting for the next end of a request.

        Args:
            starter: Called with one :class:`Waiting`; ``True`` once a turn is under way.
        """
        self._starter = starter
        if self._waiting and not self._delivery.busy:
            self._drain()

    def deliver(
        self,
        message: str | UserMessage,
        *,
        mode: str = MODE_STEER,
        hint: str | None = None,
        origin: str = "event",
        payload: object | None = None,
    ) -> str:
        """Hand one message to the agent, as a steer or as the next turn.

        Args:
            message: Text, or a message when it carries pictures (see :meth:`zettcode.engine.agent.ZettCodeAgent.turn`).
            mode: ``"steer"`` (the default) hands it to the request that runs, so it changes course;
                ``"followup"`` waits until that request ends. An idle agent starts a turn either way.
            hint: Text appended after a follow-up turn, as for a normal prompt.
            origin: Where it came from, for the transcript and the stored message.
            payload: What a front end needs to run it its own way; a message from another session passes the
                :class:`~zettcode.relay.Relayed`, which the starter hands back to the code that frames it.

        Returns:
            :data:`STEERED`, :data:`QUEUED`, :data:`STARTED` or :data:`FULL`.

        Raises:
            ValueError: When ``mode`` is neither ``"steer"`` nor ``"followup"``.
        """
        if mode not in MODES:
            raise ValueError(f"mode is 'steer' or 'followup' (got {mode!r})")
        if mode == MODE_STEER and self._delivery.busy and self._delivery.steer(message) is not None:
            return STEERED
        if self.full:
            return FULL
        self._waiting.append(Waiting(message, hint, origin, payload))
        if self._delivery.busy:
            self._arm()
            return QUEUED
        return STARTED if self._drain() else QUEUED

    def requeue(self, items: Sequence[Waiting]) -> None:
        """Put messages back that were already accepted, past the cap if it takes it.

        The cap is for what new senders may add; a message the front end had already taken — a steer the running
        request never read — must not be lost to a full queue. They keep their place at the end, in order.
        """
        self._waiting.extend(items)
        if self._delivery.busy:
            self._arm()
        else:
            self._drain()

    def drain(self) -> bool:
        """Start the next waiting turn if the front end is free; say whether anything is left waiting."""
        return self._drain()

    def _arm(self) -> None:
        """Ask the runtime to tell the inbox when the last request ends, once — only while one runs.

        Arming while nothing runs would be the same as calling back at once, and the drain that follows would arm
        again: the queue waits for the next end of a request, which is what ``start_with`` and the next ``deliver``
        look at instead.
        """
        if self._forget is None and self._delivery.busy:
            self._forget = self._delivery.when_idle(self._woke)

    def _woke(self) -> None:
        """The request ended: drain what waited, and arm again if anything is left."""
        self._forget = None
        self._drain()

    def _drain(self) -> bool:
        """Start one turn from the queue, if a starter exists and nothing runs.

        One at a time, and not one per call of this method only: a starter that schedules the turn instead of running
        it (the SDK's creates a task) returns before the runtime is busy, so the loop must not look at ``busy`` again —
        the next start waits for the next request to end, as the queue's ``waiting`` order promises.

        Two messages another session sent, waiting one after the other, start as one turn: a window that was busy
        answers them together instead of once per message (see :func:`~zettcode.relay.batch_size`). A plain event is
        always a turn of its own.
        """
        while self._waiting and self._starter is not None and not self._delivery.busy:
            item, taken = self._next()
            if not self._starter(item):
                break
            del self._waiting[:taken]
            break
        if self._waiting:
            self._arm()
        return not self._waiting

    def _next(self) -> tuple[Waiting, int]:
        """Return the waiting item to start next, and how many of the queue's head it stands for."""
        head = self._waiting[0]
        if not isinstance(head.payload, Relayed):
            return head, 1
        run: list[Relayed] = []
        for item in self._waiting:
            if not isinstance(item.payload, Relayed):
                break
            run.append(item.payload)
        count = batch_size(run)
        if count <= 1:
            return head, 1
        merged = merge(run[:count])
        return Waiting(merged.text, head.hint, head.origin, merged), count
