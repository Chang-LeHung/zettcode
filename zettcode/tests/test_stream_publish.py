"""What a running turn says to the sessions watching it: batched, ordered, and nothing at all when nobody watches."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from zettcode.engine.messenger import STREAM_BATCH, Messenger
from zettcode.sdk.client import Client
from zettcode.sdk.events import ReasoningDelta, TextDelta, ToolFinished, ToolStarted
from zettcode.sdk.types import brief_of


class Wire:
    """A stand-in for the broker client: whether anybody watches, and what was published."""

    def __init__(self, watched: bool = True) -> None:
        self.watched = watched
        self.published: list[dict[str, Any]] = []
        self.on_stream = None

    def publish(self, event: dict[str, Any]) -> None:
        self.published.append(event)


async def test_pieces_of_text_go_as_one_and_anything_else_sends_what_was_gathered_first():
    wire = Wire()
    messenger = Messenger(wire)  # type: ignore[arg-type]

    for piece in ("Hel", "lo", ", wor", "ld"):
        messenger.stream("text", text=piece)
    messenger.stream("tool", id="c1", name="bash", brief="ls")
    messenger.stream("text", text="after")
    await asyncio.sleep(STREAM_BATCH * 3)

    assert wire.published == [
        {"t": "text", "text": "Hello, world"},
        {"t": "tool", "id": "c1", "name": "bash", "brief": "ls"},
        {"t": "text", "text": "after"},
    ]


async def test_reasoning_is_said_once_without_its_content():
    wire = Wire()
    messenger = Messenger(wire)  # type: ignore[arg-type]

    for _ in range(5):
        messenger.stream("thinking", text="secret thoughts")
    messenger.stream("end")

    assert wire.published == [{"t": "thinking"}, {"t": "end"}]


async def test_nothing_is_gathered_or_sent_when_nobody_watches():
    wire = Wire(watched=False)
    messenger = Messenger(wire)  # type: ignore[arg-type]

    messenger.stream("text", text="x")
    messenger.stream("begin")
    await asyncio.sleep(STREAM_BATCH * 2)

    assert wire.published == [] and messenger._piece is None


def test_the_sdk_says_text_reasoning_and_tool_events_and_nothing_else():
    said: list[tuple[str, dict[str, Any]]] = []
    messenger = SimpleNamespace(
        client=SimpleNamespace(watched=True), stream=lambda kind, **fields: said.append((kind, fields))
    )
    client = SimpleNamespace(_agent=SimpleNamespace(runtime=SimpleNamespace(messenger=messenger)))

    for event in (
        TextDelta("s", "hi"),
        ReasoningDelta("s", "hmm"),
        ToolStarted("s", "c1", "bash", {"command": "ls  -la"}),
        ToolFinished("s", "c1", "bash", "out", True),
    ):
        Client._stream_event(client, event)  # type: ignore[arg-type]

    assert said == [
        ("text", {"text": "hi"}),
        ("thinking", {}),
        ("tool", {"id": "c1", "name": "bash", "brief": "ls -la"}),
        ("tool_end", {"id": "c1", "ok": True}),
    ]
    assert brief_of({"command": "x" * 300}).endswith("...") and brief_of({}) == ""


async def test_a_long_burst_of_text_is_cut_into_lines_the_broker_will_pass_and_nothing_is_lost():
    from zettcode.engine.messenger import STREAM_CHUNK

    wire = Wire()
    messenger = Messenger(wire)  # type: ignore[arg-type]
    burst = "x" * (STREAM_CHUNK * 2 + 10)

    messenger.stream("text", text=burst)
    await asyncio.sleep(STREAM_BATCH * 3)

    assert [len(line["text"]) for line in wire.published] == [STREAM_CHUNK, STREAM_CHUNK, 10]
    assert "".join(line["text"] for line in wire.published) == burst


async def test_a_timer_left_by_a_turn_nobody_watches_any_more_does_not_hold_up_the_next():
    wire = Wire()
    messenger = Messenger(wire)  # type: ignore[arg-type]
    messenger.stream("text", text="a")
    wire.watched = False
    messenger.stream("text", text="b")
    wire.watched = True

    messenger.stream("text", text="c")
    await asyncio.sleep(STREAM_BATCH * 3)

    assert wire.published == [{"t": "text", "text": "c"}]
