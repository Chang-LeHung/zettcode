"""One conversion between the relayed message and the value the SDK hands out: every field crosses both ways."""

from __future__ import annotations

from zettcode.messaging.relayed import Relayed
from zettcode.sdk.relay import incoming_of, relayed_of
from zettcode.wire import ImageData


def test_a_merged_message_round_trips_with_every_sender_and_field():
    picture = ImageData("image/png", b"pixels")
    first = Relayed(
        "id-alice",
        "alice",
        "one",
        hops=2,
        direct=True,
        mode="followup",
        group="team",
        images=(picture,),
    )
    second = Relayed("id-bob", "bob", "two")
    merged = Relayed(
        sender_id="id-alice",
        sender="alice, bob",
        text="alice: one\n\nbob: two",
        hops=2,
        batch=(first, second),
    )

    incoming = incoming_of(merged)

    assert [item.sender for item in incoming.batch] == ["alice", "bob"]
    assert incoming.batch[0].mode == "followup" and incoming.batch[0].direct
    assert incoming.batch[0].images[0].data == picture.data
    assert incoming.batch[0].images[0].media_type == picture.media_type

    back = relayed_of(incoming)

    assert [item.sender for item in back.batch] == ["alice", "bob"]
    assert back.batch[0].mode == "followup" and back.batch[0].direct
    assert back.batch[0].images[0].data == picture.data
    assert back.text == merged.text
