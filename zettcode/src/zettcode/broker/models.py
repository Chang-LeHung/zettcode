"""The words a session and the rest of the application use about the broker: what goes in, what comes out."""

from __future__ import annotations

from dataclasses import dataclass

from ..modes import MODE_STEER
from .protocol import KIND_ZETTCODE, ImageData, PeerInfo

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
        mode: What a busy recipient should do with it: ``"steer"`` (the default) hands it to the request that is
            running, and ``"followup"`` waits until that request ends. An idle recipient starts a turn either way.
        group: The group chat it was written in (without the ``#``), or an empty string for a one-to-one message.
        images: The pictures it carries, already checked: only a ``direct`` message has any.
    """

    sender: PeerInfo
    text: str
    hops: int
    via: str
    direct: bool = False
    mode: str = MODE_STEER
    group: str = ""
    images: tuple[ImageData, ...] = ()


@dataclass(frozen=True, slots=True)
class Receipt:
    """What this session says about a message it was handed.

    Attributes:
        accepted: Whether it took the message. A refusal carries its reason to the sender.
        reason: Why not, in words the sender's model can act on.
        disposition: What will happen to it: ``"started"`` (a turn began), ``"steered"`` (the request that was
            running took it into account), ``"queued"`` (it waits for the current request to end), or
            ``"delivered"`` (a chat window kept it without starting a turn).
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


@dataclass(frozen=True, slots=True)
class GroupInfo:
    """A group chat this session may write to: its name, when it was made, and who is in it (session ids)."""

    name: str
    created: float
    members: tuple[str, ...]

    @classmethod
    def from_wire(cls, raw: object) -> GroupInfo | None:
        """Return the group a line describes, or ``None`` when it is not one."""
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            return None
        members = raw.get("members")
        created = raw.get("created")
        return cls(
            raw["name"],
            float(created) if isinstance(created, (int, float)) and not isinstance(created, bool) else 0.0,
            tuple(m for m in members if isinstance(m, str)) if isinstance(members, list) else (),
        )


@dataclass(frozen=True, slots=True)
class GroupDelivered:
    """The answer to a send to a group: who took the message, and who did not.

    Attributes:
        group: The group's name.
        delivered: The members that took it, each with what it will do with it.
        failed: The connected members that did not, as ``(handle, reason)``.
    """

    group: str
    delivered: tuple[tuple[PeerInfo, str], ...]
    failed: tuple[tuple[str, str], ...] = ()


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
