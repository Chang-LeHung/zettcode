"""What an event outside the conversation uses to reach the agent: steer the request that runs, or wait for the next.

A message that arrives while nothing asked for it — another session's, a timer's, a webhook's — has the same two ways
in as one a reader types during a request: it can **steer** the request in flight (the agent takes it at its next model
or tool boundary and drops the rest of the task), or it can wait and become the **next turn** (a follow-up). Which one
applies is the sender's choice and the runtime's state: only a running request can be steered.

The runtime implements this and hands it to the plugins by name (``DELIVERY``); the agent's own part builds the queue on
top (:class:`zettcode.messaging.inbox.Inbox`), so the policy is a plugin's and the machinery is the engine's, which is
the one that owns the running request. A process with no runtime yet provides nothing under the name.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.messages import UserMessage

__all__ = ["DELIVERY", "Delivery"]

#: The service name the runtime provides the delivery of external events under.
DELIVERY = "delivery"


class Delivery(ABC):
    """Reaching the agent from something that is not the reader: steer a request in flight, and know when it ends."""

    @property
    @abstractmethod
    def busy(self) -> bool:
        """Return whether a request is running, which is the only time a message can steer."""

    @abstractmethod
    def steer(self, message: str | UserMessage) -> str | None:
        """Hand a message to the request in flight.

        Returns:
            The text the run reports the message by, or ``None`` when no request took it.
        """

    @abstractmethod
    def when_idle(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback`` once when no request is running, and return what forgets it again.

        A front end that has a follow-up queue waiting calls this to be told the moment the last request ends; a
        callback registered while nothing runs is called at once, so a caller never waits for an ending that already
        happened.
        """
