"""Property tests: how input is split must never change how it decodes."""

from __future__ import annotations

import random

from zettcode.tui import InputDecoder, InputEvent

CORPUS = [
    b"a",
    "你".encode(),
    "\U0001f642".encode(),
    b"\x1b[A",
    b"\x1b[1;5D",
    b"\x1b[3~",
    b"\x1b[<64;10;8M",
    b"\x1b[<0;3;4m",
    b"\x1b[200~paste\nmore\x1b[201~",
    b"\x01\x02\x05",
    b"\x1b\x7f",
    b"\x1b[Z",
    b"\r",
    b"\t",
    b"\x1f",
    b"\x1b",
]


def decode_in_chunks(chunks: list[bytes]) -> list[InputEvent]:
    decoder = InputDecoder()
    events: list[InputEvent] = []
    for chunk in chunks:
        events.extend(decoder.feed(chunk))
    trailing = decoder.flush_escape()
    if trailing is not None:
        events.append(trailing)
    return events


def random_chunks(rng: random.Random, stream: bytes) -> list[bytes]:
    cuts = sorted({0, len(stream), *(rng.randrange(len(stream) + 1) for _ in range(10))})
    return [stream[start:end] for start, end in zip(cuts[:-1], cuts[1:], strict=True) if end > start]


def test_fragmented_streams_decode_exactly_like_whole_streams():
    checked = 0
    for seed in range(80):
        rng = random.Random(seed)
        stream = b"".join(rng.choice(CORPUS) for _ in range(12))
        whole = decode_in_chunks([stream])

        assert decode_in_chunks(random_chunks(rng, stream)) == whole
        checked += len(whole)

    assert checked > 0


def test_single_byte_splits_never_lose_or_reorder_events():
    stream = b"".join(CORPUS)

    whole = decode_in_chunks([stream])
    byte_by_byte = decode_in_chunks([bytes([byte]) for byte in stream])

    assert byte_by_byte == whole
