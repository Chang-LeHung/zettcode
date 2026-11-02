"""Pictures in a one-to-one chat message: what the broker checks, hands over, and keeps (only how many there were)."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from broker_helpers import http, started
from zettcode.broker.protocol import (
    MAX_BODY,
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    MAX_IMAGES_BYTES,
    MAX_MESSAGE_BODY,
    ImageData,
    Refused,
    parse_images,
    sniff_image,
)
from zettcode.broker.store import Store

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
GIF = b"GIF89a" + b"\x00" * 24
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 24


def wire(data: bytes, media_type: str = "image/png") -> dict[str, str]:
    return {"media_type": media_type, "data": base64.b64encode(data).decode()}


# -- what a picture has to be --------------------------------------------------------------------------------------
def test_each_type_a_model_takes_is_recognised_by_its_first_bytes():
    assert [sniff_image(x) for x in (PNG, JPEG, GIF, WEBP)] == ["image/png", "image/jpeg", "image/gif", "image/webp"]
    assert sniff_image(b"<svg xmlns=...") is None and sniff_image(b"") is None
    assert sniff_image(b"RIFF\x00\x00\x00\x00WAVE") is None, "a RIFF file that is not a WebP"


def test_pictures_are_read_with_their_bytes_and_nothing_means_none():
    assert parse_images(None) == () and parse_images([]) == ()
    read = parse_images([wire(PNG), wire(JPEG, "image/jpeg")])
    assert read == (ImageData("image/png", PNG), ImageData("image/jpeg", JPEG))
    assert read[0].to_wire() == wire(PNG)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("not a list", "invalid"),
        ([("a", "b")], "invalid"),
        ([{"media_type": "image/png"}], "invalid"),
        ([{"media_type": "image/svg+xml", "data": "AAAA"}], "invalid"),
        ([{"media_type": "image/png", "data": "***not base64***"}], "invalid"),
        ([{"media_type": "image/png", "data": ""}], "invalid"),
        ([wire(JPEG, "image/png")], "invalid"),
        ([wire(b"just some text pretending", "image/png")], "invalid"),
        ([wire(PNG)] * (MAX_IMAGES + 1), "too_long"),
        ([wire(PNG + b"\x00" * MAX_IMAGE_BYTES)], "too_long"),
    ],
)
def test_what_is_not_a_picture_is_refused_with_a_reason(raw, reason):
    with pytest.raises(Refused) as caught:
        parse_images(raw)
    assert caught.value.reason == reason


def test_the_pictures_of_one_message_are_limited_together_as_well_as_each():
    big = PNG + b"\x00" * (MAX_IMAGE_BYTES - len(PNG))
    assert len(parse_images([wire(big)] * (MAX_IMAGES_BYTES // MAX_IMAGE_BYTES))) == MAX_IMAGES_BYTES // MAX_IMAGE_BYTES
    with pytest.raises(Refused) as caught:
        parse_images([wire(big)] * (MAX_IMAGES_BYTES // MAX_IMAGE_BYTES + 1))
    assert caught.value.reason == "too_long"


def test_a_message_with_all_the_pictures_it_may_have_fits_in_the_body_the_broker_reads():
    encoded = (MAX_IMAGES_BYTES + 2) // 3 * 4
    assert MAX_MESSAGE_BODY == MAX_BODY + encoded and MAX_MESSAGE_BODY > MAX_BODY


# -- over a real broker --------------------------------------------------------------------------------------------
async def test_a_picture_reaches_a_session_that_takes_chat_prompts_and_the_history_keeps_only_a_count(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        chat = await run.peer(A, "window")
        daemon = await run.peer(B, "daemon")
        assert "error" not in await daemon.register(B, "daemon", direct=True)

        task = asyncio.ensure_future(
            chat.post("daemon", "what is this?", via="user", direct=True, images=[wire(PNG), wire(JPEG, "image/jpeg")])
        )
        delivery = await daemon.accept("started")
        reply = await task

        assert reply["status"] == 200 and reply["direct"] is True
        assert delivery["direct"] is True and delivery["text"] == "what is this?"
        assert [item["media_type"] for item in delivery["images"]] == ["image/png", "image/jpeg"]
        assert base64.b64decode(delivery["images"][0]["data"]) == PNG

        stored = (await http(run.port, "GET", f"/history?a={A}&b={B}")).json()["messages"]
        assert [m["text"] for m in stored] == ["what is this?\n[2 pictures]"]
        assert "data" not in str(stored) and "iVBOR" not in str(stored), "the pictures themselves are never written"
    finally:
        await run.aclose()


async def test_pictures_alone_are_a_message_and_a_stored_one_says_so(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        chat = await run.peer(A, "window")
        daemon = await run.peer(B, "daemon")
        await daemon.register(B, "daemon", direct=True)

        task = asyncio.ensure_future(chat.post("daemon", "", via="user", direct=True, images=[wire(GIF, "image/gif")]))
        delivery = await daemon.accept("started")
        assert (await task)["status"] == 200 and delivery["text"] == ""

        stored = (await http(run.port, "GET", f"/history?a={A}&b={B}")).json()["messages"]
        assert [m["text"] for m in stored] == ["[1 picture]"]
        empty = await chat.post("daemon", "", via="user", direct=True)
        assert empty["status"] == 400 and empty["error"]["reason"] == "empty", "no words and no pictures is still empty"
    finally:
        await run.aclose()


async def test_pictures_are_refused_where_they_have_nowhere_to_go(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        chat = await run.peer(A, "window")
        plain = await run.peer(B, "plain")  # a session that does not run a chat's text as its own prompt
        pic = [wire(PNG)]

        not_direct = await chat.post("plain", "look", via="user", direct=True, images=pic)
        assert not_direct["status"] == 400 and "does not take pictures" in not_direct["error"]["message"]
        by_agent = await chat.post("plain", "look", via="agent", images=pic)
        assert by_agent["status"] == 400 and by_agent["error"]["reason"] == "invalid"
        assert plain.requests() == [], "nothing was handed to it"

        await run.peer("03c30d97-cccc-7000-8000-000000000003", "third")
        made = await http(
            run.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": chat.key},
            json={"action": "create", "name": "team", "members": ["plain"]},
        )
        assert made.status_code == 200
        grouped = await chat.post(None, "look", group="team", via="user", images=pic)
        assert grouped["status"] == 400 and "not to a group" in grouped["error"]["message"]

        bad = await chat.post("plain", "look", via="user", direct=True, images=[wire(JPEG, "image/png")])
        assert bad["status"] == 400 and bad["error"]["reason"] == "invalid"
    finally:
        await run.aclose()


async def test_a_session_that_will_not_take_the_pictures_says_why_to_the_sender(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        chat = await run.peer(A, "window")
        daemon = await run.peer(B, "daemon")
        await daemon.register(B, "daemon", direct=True)

        task = asyncio.ensure_future(
            chat.post("daemon", "see", via="user", direct=True, images=[wire(WEBP, "image/webp")])
        )
        await daemon.refuse("fast does not accept pictures")
        answer = await task

        assert answer["status"] == 409 and answer["error"]["message"] == "fast does not accept pictures"
        assert (await http(run.port, "GET", f"/history?a={A}&b={B}")).json()["messages"] == [], "nothing was delivered"
    finally:
        await run.aclose()


# -- what is refused before it costs anything -----------------------------------------------------------------------
async def test_a_message_that_may_not_carry_pictures_is_refused_before_they_are_decoded(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        chat = await run.peer(A, "window")
        await run.peer(B, "plain")
        junk = [{"media_type": "image/png", "data": "***not base64***"}]  # decoding it would say "not base64"

        refused = await chat.post("plain", "look", via="user", direct=True, images=junk)
        assert "does not take pictures" in refused["error"]["message"], "its refusal comes before the pictures are read"
        await http(
            run.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": chat.key},
            json={"action": "create", "name": "team", "members": ["plain"]},
        )
        grouped = await chat.post(None, "look", group="team", via="user", images=junk)
        assert "not to a group" in grouped["error"]["message"]
    finally:
        await run.aclose()


def test_a_session_that_stopped_answering_cannot_hold_more_pictures_than_the_budget():
    from zettcode.broker.hub import MAX_WAITING_PICTURES, Session

    session = Session(1, lambda code: None)
    size = MAX_WAITING_PICTURES // 6  # a message in flight counts as waiting and as queued
    big = {"text": "x", "images": [{"media_type": "image/png", "data": "A" * size}]}

    async def scenario() -> list[str]:
        waiting = [asyncio.ensure_future(session.deliver(big, 5)) for _ in range(3)]
        await asyncio.sleep(0)
        assert session.waiting == 3
        with pytest.raises(Refused) as caught:
            await session.deliver(big, 5)
        assert caught.value.reason == "busy" and "pictures" in str(caught.value)
        # Words alone are not weighed, so a session with pictures waiting can still be written to.
        text = asyncio.ensure_future(session.deliver({"text": "hello"}, 5))
        await asyncio.sleep(0)
        for task in [*waiting, text]:
            task.cancel()
        await asyncio.gather(*waiting, text, return_exceptions=True)
        assert session.waiting == 0 and session._weight == 0, "what was waiting is released"
        return ["ok"]

    assert asyncio.run(scenario()) == ["ok"]


def test_pictures_a_session_never_reads_count_after_their_acks_time_out_and_are_freed_when_it_reads():
    from zettcode.broker.hub import MAX_WAITING_PICTURES, Session

    session = Session(1, lambda code: None)
    size = MAX_WAITING_PICTURES // 4
    big = {"text": "x", "images": [{"media_type": "image/png", "data": "A" * size}]}

    async def scenario() -> None:
        for _ in range(4):
            with pytest.raises(asyncio.TimeoutError):
                await session.deliver(big, 0.01)  # nobody acks, and nobody reads the line
        assert session.waiting == 0 and session._weight == 0, "nothing is waiting for an ack any more"
        assert session._queued == 4 * size, "but the lines are still queued, with their pictures"
        with pytest.raises(Refused) as caught:
            await session.deliver(big, 0.01)
        assert caught.value.reason == "busy" and "pictures" in str(caught.value)

        await session.next_line()  # the writer takes one
        assert session._queued == 3 * size
        with pytest.raises(asyncio.TimeoutError):
            await session.deliver(big, 0.01)  # there is room again

    asyncio.run(scenario())
