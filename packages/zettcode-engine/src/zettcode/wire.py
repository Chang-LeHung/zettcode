"""The things a message from another session, and the session itself, carry that the broker and the application share.

The broker carries a message and a roster of sessions; the application stores and draws one and completes names from
the other. Both need to say how a message arrived (``via``), carry a picture for a direct message, and describe a
session as the roster lists it. The words, the picture and the roster shape live here — a leaf with no imports of ours
— so the broker can speak them without importing the message type, which pulls in the agent runtime.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass

#: How a message reached its recipient: a reader typed it into another session, an agent used its tool, or it came
#: from something that is not a ZettCode session at all. The broker speaks the same words when it carries one, so a
#: relayed message and the wire cannot drift apart.
VIA_USER = "user"
VIA_AGENT = "agent"
VIA_EXTERNAL = "external"


class RosterPeer(ABC):
    """Another session as completion and addressing read it.

    The broker's roster entry and the SDK's plain ``Peer`` are the same shape on opposite sides of the application;
    both inherit this, so a caller can name one type without either side importing the other. The properties are
    satisfied by the slotted dataclass fields both classes define.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def session_id(self) -> str:
        """The session's id."""

    @property
    @abstractmethod
    def handle(self) -> str:
        """The word that follows an ``@`` to address it."""

    @property
    @abstractmethod
    def workspace(self) -> str:
        """The directory it works in."""

    @property
    @abstractmethod
    def title(self) -> str:
        """What the session is about, as its reader would call it."""

    @property
    @abstractmethod
    def status(self) -> str:
        """``idle`` or ``working``."""


@dataclass(frozen=True, slots=True)
class ImageData:
    """One picture a message carries: its media type and the encoded file (not decoded pixels)."""

    media_type: str
    data: bytes

    def to_wire(self) -> dict[str, str]:
        """Return the picture as a line carries it: the media type and the file in base64."""
        return {"media_type": self.media_type, "data": base64.b64encode(self.data).decode("ascii")}
