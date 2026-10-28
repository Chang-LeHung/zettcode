"""The words a session and the rest of the application use about the broker: what goes in, what comes out."""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import KIND_ZETTCODE, PeerInfo

#: Another word for a registered session, as the rest of the application knows it.
RosterEntry = PeerInfo


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What a session tells the broker about itself."""

    session_id: str
    title: str = ""
    workspace: str = ""
    status: str = "idle"
    kind: str = KIND_ZETTCODE
    direct: bool = False


@dataclass(frozen=True, slots=True)
class Incoming:
    """A message another session (or an external source) sent to this one.

    Attributes:
        sender: Who sent it, as the roster describes them now.
        text: The message, already cleaned of escape sequences.
        hops: How many sessions it has passed through, this one included.
        via: ``"user"`` when a reader typed it into the other session, ``"agent"`` when its tool did, ``"external"``
            when the sender is not a ZettCode session.
        direct: Set when the sender is a reader's one-to-one chat window: run the text as that reader's own prompt,
            not as a message from another session, and send the final answer back to the sender.
    """

    sender: PeerInfo
    text: str
    hops: int
    via: str
    direct: bool = False


@dataclass(frozen=True, slots=True)
class Receipt:
    """What this session says about a message it was handed.

    Attributes:
        accepted: Whether it took the message. A refusal carries its reason to the sender.
        reason: Why not, in words the sender's model can act on.
        disposition: What will happen to it: ``"started"`` (a turn began), or ``"queued"`` (it waits
            for the current request to end).
    """

    accepted: bool
    reason: str = ""
    disposition: str = ""


@dataclass(frozen=True, slots=True)
class Delivered:
    """The answer to a send: who took it, and what they will do with it."""

    to: PeerInfo
    disposition: str
    direct: bool = False


class SendError(Exception):
    """A message that did not arrive, and why.

    Attributes:
        reason: ``offline`` when there is no broker, ``lost`` when the connection ended with the message
            in flight (it may or may not have been delivered), otherwise the broker's own reason
            (``unknown``, ``ambiguous``, ``rejected``, ``timeout``, ``loop``, ``rate``…).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
