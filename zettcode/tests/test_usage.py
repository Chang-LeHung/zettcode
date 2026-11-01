"""Token accounting: the usage extension, its event payload, and its summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.events import MessageTiming
from zett_agent.messages import AssistantMessage
from zett_agent.model import ModelEvent, ModelResponse, ModelUsage, ServerToolCall

from zettcode.engine.extensions.usage import USAGE_EVENT_NAME, UsageExtension, UsageSnapshot, session_usage
from zettcode.statusline import compact_tokens, context_text, usage_text


class _Config:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


class _State:
    """The conversation the runtime has assembled so far."""

    def __init__(self, messages: tuple[object, ...] = ()) -> None:
        self.messages = messages


class _Context:
    """Stand-in for the runtime context: one session, its conversation, and an event sink."""

    def __init__(self, session_id: str = "s-1", messages: tuple[object, ...] = ()) -> None:
        self.config = _Config(session_id)
        self.state = _State(messages)
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


async def _call(
    extension: UsageExtension, context: _Context, response: ModelResponse, *, data: bool = True, deltas: int = 1
) -> list[ModelEvent]:
    """Drive one model stream and its usage update; return the events the middleware yielded."""
    events = [ModelEvent.text("token") for _ in range(deltas)] if data else []
    seen: list[ModelEvent] = []

    async def source(request):
        for event in events:
            yield event
        yield ModelEvent.completed(response)

    async for event in extension.on_model_request(context, None, source):
        seen.append(event)
    await extension.after_model(context, response)
    return seen


async def test_the_extension_accumulates_each_call_and_publishes_the_total():
    extension = UsageExtension(clock=_Clock(1.0, 3.5, 10.0, 12.0))
    context = _Context()

    await _call(extension, context, _response(input_tokens=1_000, output_tokens=100, cache_read_tokens=600))
    await _call(extension, context, _response(input_tokens=2_000, output_tokens=300, cache_read_tokens=1_500))

    snapshot = extension.snapshot("s-1")
    assert (snapshot.input_tokens, snapshot.output_tokens) == (3_000, 400)
    assert snapshot.cache_read_tokens == 2_100
    assert snapshot.requests == 2
    assert snapshot.seconds == pytest.approx(4.5)
    assert snapshot.context_tokens == 2_000  # the newest call's prompt, not the sum
    assert snapshot.cache_hit_rate == pytest.approx(0.7)
    # Each call's opening chunk carried one token and cost no measured time, so the rate leaves both out.
    assert snapshot.first_chunk_tokens == 2
    assert snapshot.output_rate == pytest.approx((400 - 2) / 4.5)

    event = context.emitted[-1]
    assert event.type is AgentEventType.CUSTOM
    assert event.name == USAGE_EVENT_NAME
    assert event.payload == snapshot.to_payload()
    assert UsageSnapshot.from_payload(event.payload) == snapshot


async def test_the_rate_starts_at_the_first_streamed_data_not_before_the_model_call():
    """The wait for a model to start talking is not generation time."""
    extension = UsageExtension(clock=_Clock(5.0, 20.0))
    context = _Context()

    await _call(extension, context, _response(input_tokens=10, output_tokens=30))

    snapshot = extension.snapshot("s-1")
    assert snapshot.seconds == pytest.approx(15.0)
    assert snapshot.output_rate == pytest.approx((30 - 1) / 15)


async def test_the_rate_leaves_out_the_tokens_the_opening_chunk_carried():
    """The opening chunk arrived when the clock started, so its tokens are not credited with speed they never cost."""
    extension = UsageExtension(clock=_Clock(5.0, 20.0), count_chunk=lambda text: 3)
    context = _Context()

    await _call(extension, context, _response(input_tokens=10, output_tokens=30))

    snapshot = extension.snapshot("s-1")
    assert snapshot.first_chunk_tokens == 3
    assert snapshot.output_rate == pytest.approx((30 - 3) / 15)


async def test_an_event_that_generated_nothing_does_not_start_the_clock():
    """A server tool starting is a wait, not generation; opening the clock there would understate the rate."""
    extension = UsageExtension(clock=_Clock(2.0, 20.0))
    context = _Context()
    response = _response(input_tokens=10, output_tokens=30)
    events = [
        ModelEvent.server_tool_started(ServerToolCall(id="c-1", name="web_search")),
        ModelEvent.text("token"),
    ]

    async def source(request):
        for event in events:
            yield event
        yield ModelEvent.completed(response)

    async for _ in extension.on_model_request(context, None, source):
        pass
    await extension.after_model(context, response)

    snapshot = extension.snapshot("s-1")
    assert snapshot.seconds == pytest.approx(18.0)
    assert snapshot.first_chunk_tokens == 1


async def test_a_reply_that_never_generated_anything_has_no_rate():
    """An opening chunk as large as the whole call leaves nothing the span measured."""
    extension = UsageExtension(clock=_Clock(5.0, 20.0), count_chunk=lambda text: 30)
    context = _Context()

    await _call(extension, context, _response(input_tokens=10, output_tokens=30))

    assert extension.snapshot("s-1").output_rate is None


async def test_a_later_delta_does_not_restart_the_clock():
    # The first delta is at 5s and the response at 7s; if the second delta
    # restarted the clock the response would be read at 20s and the span 13s.
    extension = UsageExtension(clock=_Clock(5.0, 7.0, 20.0))
    context = _Context()

    await _call(extension, context, _response(input_tokens=10, output_tokens=30), deltas=2)

    assert extension.snapshot("s-1").seconds == pytest.approx(2.0)


async def test_the_middleware_forwards_the_provider_events_unchanged():
    extension = UsageExtension(clock=_Clock(5.0, 20.0))
    context = _Context()
    response = _response(input_tokens=10, output_tokens=30)

    seen = await _call(extension, context, response)

    assert [event.type.value for event in seen] == ["text_delta", "response"]
    assert seen[-1].response is response


async def test_a_reply_with_no_streamed_data_has_no_rate():
    extension = UsageExtension(clock=_Clock())
    context = _Context()

    await _call(extension, context, _response(input_tokens=10, output_tokens=30), data=False)

    snapshot = extension.snapshot("s-1")
    assert snapshot.seconds == 0.0
    assert snapshot.output_rate is None


def test_a_stored_reply_uses_its_streamed_span_not_the_whole_call():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timing = MessageTiming(
        started_at=base,
        completed_at=base + timedelta(seconds=10),
        duration_ns=10_000_000_000,
        reasoning_started_at=base + timedelta(seconds=2),
        reasoning_completed_at=base + timedelta(seconds=7),
        reasoning_duration_ns=5_000_000_000,
        content_started_at=base + timedelta(seconds=3),
        content_completed_at=base + timedelta(seconds=8),
        content_duration_ns=5_000_000_000,
    )
    line = SimpleNamespace(usage=ModelUsage(output_tokens=60), timing=timing)

    snapshot = session_usage([line])

    assert snapshot.seconds == pytest.approx(6.0)
    assert snapshot.output_rate == pytest.approx(10.0)


def test_a_stored_reply_with_no_stream_marks_has_no_rate():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timing = MessageTiming(started_at=base, completed_at=base + timedelta(seconds=10), duration_ns=10_000_000_000)
    line = SimpleNamespace(usage=ModelUsage(output_tokens=60), timing=timing)

    snapshot = session_usage([line])

    assert snapshot.seconds == 0.0
    assert snapshot.output_rate is None


def test_a_stored_reasoning_only_reply_uses_its_reasoning_span():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timing = MessageTiming(
        started_at=base,
        completed_at=base + timedelta(seconds=10),
        duration_ns=10_000_000_000,
        reasoning_started_at=base + timedelta(seconds=2),
        reasoning_completed_at=base + timedelta(seconds=7),
        reasoning_duration_ns=5_000_000_000,
    )
    line = SimpleNamespace(usage=ModelUsage(output_tokens=30), timing=timing)

    snapshot = session_usage([line])

    assert snapshot.seconds == pytest.approx(5.0)
    assert snapshot.output_rate == pytest.approx(6.0)


def test_the_context_fragment_reports_the_newest_call_against_the_window():
    """The status line only claims a share once a request has been measured."""
    assert context_text(UsageSnapshot(), 128_000) == ""
    measured = UsageSnapshot(context_tokens=64_000, requests=1)

    assert context_text(measured, 128_000) == " \u00b7 ctx 50.0%"
    assert context_text(measured, 0) == ""  # a model without a declared window
    assert context_text(measured, 32_000) == " \u00b7 ctx 100.0%"  # never claims more than the window


async def test_each_session_keeps_its_own_totals():
    extension = UsageExtension(clock=_Clock(0.0, 1.0, 0.0, 2.0))
    first, second = _Context("a"), _Context("b")

    await _call(extension, first, _response(input_tokens=10, output_tokens=1))
    await _call(extension, second, _response(input_tokens=20, output_tokens=2))

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

    assert usage_text(snapshot) == "  \u219122.0k \u2193600 \u00b7 77.3% cached \u00b7 100 tok/s"


def test_compact_tokens_rounds_into_the_next_unit():
    assert compact_tokens(0) == "0"
    assert compact_tokens(999) == "999"
    assert compact_tokens(1_000) == "1.0k"
    assert compact_tokens(12_345) == "12.3k"
    assert compact_tokens(999_999) == "1.0M"


def test_a_call_that_reported_no_input_leaves_the_last_reading_of_the_context_in_place():
    """A gateway that drops the usage of one call must not hide the share until the next answer."""
    measured = UsageSnapshot().with_usage(ModelUsage(input_tokens=64_000, output_tokens=100), 1.0)
    silent = measured.with_usage(ModelUsage(input_tokens=0, output_tokens=0), 0.5)

    assert silent.context_tokens == 64_000
    assert silent.requests == 2
    assert context_text(silent, 128_000) == " \u00b7 ctx 50.0%"
    assert UsageSnapshot().with_usage(ModelUsage(), 0.1).context_tokens == 0, "and before any reading, none"


async def test_a_provider_that_stops_reporting_the_input_grows_the_context_instead_of_freezing_it():
    """A gateway that drops usage must not leave the share standing still while the conversation goes on."""
    counted: list[int] = []

    def count_context(messages):
        counted.append(len(messages))
        return 10 * len(messages)

    extension = UsageExtension(clock=_Clock(1.0, 2.0, 3.0, 4.0), count_context=count_context)
    # ``r1`` is the reply this very call returns: the runtime appends it before after_model runs, so the conversation
    # it leaves behind is the prompt it answered plus that answer.
    context = _Context(messages=("a", "b", "r1"))

    await _call(extension, context, _response(input_tokens=5_000, output_tokens=10))
    assert extension.snapshot("s-1").context_tokens == 5_000

    # A tool result and its follow-up answer arrive, and the next call reports no input count at all.
    context.state.messages = ("a", "b", "r1", "t1", "r2")
    await _call(extension, context, _response(input_tokens=0, output_tokens=10))

    assert extension.snapshot("s-1").context_tokens == 5_030, "the prompt and its answer, plus what arrived since"
    assert counted == [2], "only the messages after the baseline are counted"


async def test_a_compaction_throws_the_baseline_away_and_counts_the_whole_conversation():
    """After the conversation is replaced, a count taken against the messages of the old one means nothing."""
    extension = UsageExtension(
        clock=_Clock(1.0, 2.0, 3.0, 4.0, 5.0, 6.0), count_context=lambda messages: 10 * len(messages)
    )
    context = _Context(messages=("a", "b", "r1"))

    await _call(extension, context, _response(input_tokens=5_000, output_tokens=10))
    context.state.messages = ("a", "b", "r1", "t1", "r2")
    await _call(extension, context, _response(input_tokens=0, output_tokens=10))
    assert extension.snapshot("s-1").context_tokens == 5_030

    # Five messages became two: the conversation did not grow, so the baseline no longer describes it.
    context.state.messages = ("summary", "r3")
    await _call(extension, context, _response(input_tokens=0, output_tokens=10))

    assert extension.snapshot("s-1").context_tokens == 20


async def test_a_session_that_never_reported_any_input_is_counted_whole():
    extension = UsageExtension(clock=_Clock(1.0, 2.0), count_context=lambda messages: 7 * len(messages))
    context = _Context(messages=("a", "b"))

    await _call(extension, context, _response(input_tokens=0, output_tokens=10))

    assert extension.snapshot("s-1").context_tokens == 14
