"""Token accounting: the usage extension, its event payload, and its summary."""

from __future__ import annotations

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage
from zett_agent.model import ModelResponse, ModelUsage

from zettcode.app.agent.usage import (
    USAGE_EVENT_NAME,
    UsageExtension,
    UsageSnapshot,
    compact_tokens,
    usage_text,
)


class _Config:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


class _Context:
    """Stand-in for the runtime context: one session and an event sink."""

    def __init__(self, session_id: str = "s-1") -> None:
        self.config = _Config(session_id)
        self.emitted: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.emitted.append(event)


class _Clock:
    """Return canned monotonic readings, one per call."""

    def __init__(self, *moments: float) -> None:
        self.moments = iter(moments)

    def __call__(self) -> float:
        return next(self.moments)


def _response(*, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> ModelResponse:
    """Build the assistant response one model call returns."""
    return ModelResponse(
        message=AssistantMessage(content="done"),
        usage=ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        ),
    )


async def test_the_extension_accumulates_each_call_and_publishes_the_total():
    extension = UsageExtension(clock=_Clock(1.0, 3.5, 10.0, 12.0))
    context = _Context()

    await extension.before_model(context, None)
    await extension.after_model(context, _response(input_tokens=1_000, output_tokens=100, cache_read_tokens=600))
    await extension.before_model(context, None)
    await extension.after_model(context, _response(input_tokens=2_000, output_tokens=300, cache_read_tokens=1_500))

    snapshot = extension.snapshot("s-1")
    assert (snapshot.input_tokens, snapshot.output_tokens) == (3_000, 400)
    assert snapshot.cache_read_tokens == 2_100
    assert snapshot.requests == 2
    assert snapshot.seconds == pytest.approx(4.5)
    assert snapshot.cache_hit_rate == pytest.approx(0.7)
    assert snapshot.output_rate == pytest.approx(400 / 4.5)

    event = context.emitted[-1]
    assert event.type is AgentEventType.CUSTOM
    assert event.name == USAGE_EVENT_NAME
    assert event.payload == snapshot.to_payload()
    assert UsageSnapshot.from_payload(event.payload) == snapshot


async def test_each_session_keeps_its_own_totals():
    extension = UsageExtension(clock=_Clock(0.0, 1.0, 0.0, 2.0))
    first, second = _Context("a"), _Context("b")

    await extension.before_model(first, None)
    await extension.after_model(first, _response(input_tokens=10, output_tokens=1))
    await extension.before_model(second, None)
    await extension.after_model(second, _response(input_tokens=20, output_tokens=2))

    assert extension.snapshot("a").input_tokens == 10
    assert extension.snapshot("b").input_tokens == 20
    assert extension.snapshot("missing").requests == 0


def test_seeding_replaces_totals_instead_of_adding_to_them():
    extension = UsageExtension()
    seeded = UsageSnapshot(input_tokens=500, output_tokens=50, seconds=5.0, requests=1)

    extension.seed("s-1", seeded)
    extension.seed("s-1", seeded)

    assert extension.snapshot("s-1") == seeded


def test_payloads_with_junk_fall_back_to_zero():
    snapshot = UsageSnapshot.from_payload({"input_tokens": "many", "seconds": None, "requests": 3})

    assert snapshot.input_tokens == 0
    assert snapshot.seconds == 0.0
    assert snapshot.requests == 3


def test_usage_text_stays_quiet_until_a_model_call_lands():
    assert usage_text(UsageSnapshot()) == ""


def test_usage_text_reports_totals_cache_share_and_rate():
    snapshot = UsageSnapshot(
        input_tokens=22_000,
        output_tokens=600,
        cache_read_tokens=17_000,
        seconds=6.0,
        requests=2,
    )

    assert usage_text(snapshot) == "  \u219122.0k \u2193600 \u00b7 77% cached \u00b7 100 tok/s"


def test_compact_tokens_rounds_into_the_next_unit():
    assert compact_tokens(0) == "0"
    assert compact_tokens(999) == "999"
    assert compact_tokens(1_000) == "1.0k"
    assert compact_tokens(12_345) == "12.3k"
    assert compact_tokens(999_999) == "1.0M"
