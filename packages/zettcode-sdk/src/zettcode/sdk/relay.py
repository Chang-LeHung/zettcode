"""The one conversion between the message a session sends and the value the SDK hands out.

A relayed message has two shapes: :class:`~zettcode.messaging.relayed.Relayed`, which the messaging part frames and
stores, and :class:`~zettcode.sdk.types.IncomingMessage`, which a program sees. They are the same message, so every
field crosses both ways here — including the batch that stands for several messages which waited — and no caller
keeps a second copy that can drift.

This module is the SDK's internal bridge, not part of the documented API: the SDK imports it lazily so that naming a
public class still loads neither the agent nor the messaging part.
"""

from __future__ import annotations

from zettcode.messaging.relayed import Relayed
from zettcode.sdk.types import Image, IncomingMessage
from zettcode.wire import ImageData

__all__ = ["incoming_of", "relayed_of"]


def incoming_of(relayed: Relayed) -> IncomingMessage:
    """Return the value this SDK hands a program for one message another session sent."""
    return IncomingMessage(
        sender_id=relayed.sender_id,
        sender=relayed.sender,
        text=relayed.text,
        via=relayed.via,
        hops=relayed.hops,
        direct=relayed.direct,
        mode=relayed.mode,
        group=relayed.group,
        images=tuple(Image(item.data, item.media_type) for item in relayed.images),
        batch=tuple(incoming_of(each) for each in relayed.batch),
    )


def relayed_of(message: IncomingMessage) -> Relayed:
    """Return the message the messaging part frames and stores for one the SDK was handed."""
    return Relayed(
        sender_id=message.sender_id,
        sender=message.sender,
        text=message.text,
        via=message.via,
        hops=message.hops,
        direct=message.direct,
        mode=message.mode,
        group=message.group,
        images=tuple(ImageData(item.media_type, item.data) for item in message.images),
        batch=tuple(relayed_of(each) for each in message.batch),
    )
