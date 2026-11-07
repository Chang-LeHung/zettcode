"""The contract between a front end's turn loop and the queue of events from outside the conversation.

The runtime knows whether a request is running and how to steer it (:class:`~zettcode.engine.delivery.Delivery`); a
front end owns the loop that starts turns, so only it can take a waiting message and begin one. The queue in between is
a plugin's: it decides how many may wait, when a batch is answered as one turn, and what a sender is told. This module
is what the two agree on, so a plugin can type the ``INBOX`` service and a front end can call it without either
importing the other's distribution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zettcode.modes import MODE_STEER

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.messages import UserMessage

__all__ = ["FULL", "INBOX", "QUEUED", "STARTED", "STEERED", "Inbox", "Waiting", "WaitingLike"]

#: The service name the queue is provided under, for a front end that delivers into the agent.
INBOX = "inbox"

#: What ``deliver`` did: the running request took it, it was queued, a turn was started with it, or there was no room.
STEERED = "steered"
QUEUED = "queued"
STARTED = "started"
FULL = "full"


class WaitingLike(ABC):
    """What batching reads of a message that waits: whether it stands alone, and what it says.

    The relayed message and the SDK's incoming message are the two that wait together; both inherit this, so the
    batching policy can name one type without either side importing the other. A class-level attribute, a property
    or a slotted dataclass field satisfies the abstract properties; an instance attribute set in ``__init__`` does
    not, because it is not visible to the abstract class.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def direct(self) -> bool:
        """Whether it is a chat window's message, which has to be answered on its own."""

    @property
    @abstractmethod
    def text(self) -> str:
        """What it says."""


@dataclass(frozen=True, slots=True)
class Waiting:
    """One message the queue holds for the next turn.

    Attributes:
        message: What to run: text, or a message when it carries pictures.
        hint: Text appended after it, as for a prompt.
        origin: Where it came from, for the transcript and the stored message.
        payload: What the front end needs to run it its own way — the object the sender attached, or ``None`` for a
            plain event. The engine does not look inside it.
    """

    message: str | UserMessage
    hint: str | None = None
    origin: str = "event"
    payload: object | None = None


class Inbox(ABC):
    """Hand a message to the request in flight, or hold it until a front end can start the next turn.

    Implemented by the ``messaging`` plugin, read by a front end through the ``INBOX`` service. The guarantee a front
    end relies on is one turn at a time: a message that arrives while a request runs either steers it or waits, and
    only the front end's starter begins a turn.
    """

    @property
    @abstractmethod
    def waiting(self) -> tuple[Waiting, ...]:
        """Return the messages held for the next turn, in the order they arrived."""

    @property
    @abstractmethod
    def full(self) -> bool:
        """Return whether the queue is at its cap, so a new message would be refused."""

    @abstractmethod
    def start_with(self, starter: Callable[[Waiting], bool]) -> None:
        """Register what starts a turn from a waiting message, and drain anything already waiting.

        Args:
            starter: Called with one :class:`Waiting`; ``True`` once a turn is under way. A starter that returns
                ``False`` could not start one now, and the message stays waiting for the next end of a request.
        """

    @abstractmethod
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
            message: Text, or a message when it carries pictures.
            mode: ``"steer"`` (the default) hands it to the request that runs, so it changes course;
                ``"followup"`` waits until that request ends. An idle agent starts a turn either way.
            hint: Text appended after a follow-up turn, as for a normal prompt.
            origin: Where it came from, for the transcript and the stored message.
            payload: What a front end needs to run it its own way; returned with the item :meth:`start_with` starts.

        Returns:
            :data:`STEERED`, :data:`QUEUED`, :data:`STARTED` or :data:`FULL`.
        """

    @abstractmethod
    def requeue(self, items: Sequence[Waiting]) -> None:
        """Put messages back that were already accepted, keeping their place at the end, in order."""

    @abstractmethod
    def drain(self) -> bool:
        """Start the next waiting turn if the front end is free; say whether anything is left waiting."""
