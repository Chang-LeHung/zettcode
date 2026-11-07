"""What the store keeps of a message another session sent: the attribute a session reads back.

The message itself — who sent it, what the model reads, how it is framed — is the ``messaging`` part's
(:mod:`zettcode.messaging.relayed`). The engine keeps only the one fact it needs without the broker or the session
message: the name of the key a stored message's sender is written under, so an export can say whose message it was.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["RELAY", "relay_sender"]

#: Attribute of a stored message that came from another session. Its value is the sender's mark.
RELAY = "relay"


def relay_sender(attributes: object) -> str | None:
    """Return the session named in a stored message's relay mark, or ``None`` when it did not come from one.

    Written to survive a store that was edited or written by another version: anything that is not the shape the
    sending session writes is an ordinary message, never an error.

    Args:
        attributes: The stored message's attributes.
    """
    if not isinstance(attributes, Mapping):
        return None
    mark = attributes.get(RELAY)
    if not isinstance(mark, Mapping):
        return None
    sender_id, name = mark.get("id"), mark.get("name")
    if not isinstance(sender_id, str) or not isinstance(name, str):
        return None
    return name
