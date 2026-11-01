"""Token accounting for one session, published as custom events.

The runtime reports usage per model call; what the shell wants is a running
total: tokens in and out, how much input came from the provider cache, and how
fast the model is answering. :class:`UsageExtension` keeps that total per
session and emits it as one ``session_usage`` custom event after every model
call, so the status line can mirror it without polling the store.

The counter invariants are ``zett-agent``'s: ``input_tokens`` already contains
cache reads and writes, and ``output_tokens`` already contains reasoning.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, replace
from time import monotonic
from typing import TYPE_CHECKING, cast
from weakref import WeakKeyDictionary

from zett_agent.agent import AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.base import AgentExtension
from zett_agent.model import ModelEvent, ModelEventType, ModelRequest, ModelResponse, ModelUsage

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator, AsyncIterator

    from zett_agent.extensions.base import ModelRequestNext
    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import AnyMessage

    from ..storage import MessageLine

#: Custom event name for one cumulative usage update; its payload is
#: :meth:`UsageSnapshot.to_payload`.
USAGE_EVENT_NAME = "session_usage"


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """Cumulative token counters and measured generation time for one session.

    Attributes:
        input_tokens: Complete model input, including cache reads and writes.
        output_tokens: Generated tokens, including reasoning when reported.
        cache_read_tokens: Input tokens the provider served from its cache.
        cache_write_tokens: Input tokens written into the provider cache.
        reasoning_tokens: Reasoning subset of ``output_tokens``.
        first_chunk_tokens: Tokens the first streamed chunk carried, the part of
            ``output_tokens`` that arrived when the clock started and so has no
            time of its own to be measured against.
        seconds: Time from the first streamed data that generated something to
            the terminal response, the rate denominator.
        requests: Model calls counted, zero before the first answer.
        context_tokens: Input tokens the newest call carried, which is how full
            the context is right now; zero before the first answer.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    first_chunk_tokens: int = 0
    seconds: float = 0.0
    requests: int = 0
    context_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return input plus output without counting cache or reasoning twice."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float | None:
        """Return the cached share of all input, or None before any input."""
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else None

    @property
    def output_rate(self) -> float | None:
        """Return generated tokens per second of generation time, if it was measured.

        The first chunk's tokens come out of the numerator. The clock starts when that chunk arrives, so those tokens
        were generated before any time the clock could see; counting them would credit output that cost no measured
        seconds. Subtracting them leaves the rate of the tokens the span actually covers.
        """
        generated = self.output_tokens - self.first_chunk_tokens
        return generated / self.seconds if self.seconds > 0 and generated > 0 else None

    def with_usage(
        self,
        usage: ModelUsage,
        seconds: float,
        *,
        first_chunk_tokens: int = 0,
        context_tokens: int | None = None,
    ) -> UsageSnapshot:
        """Return these totals plus one model call and its measured generation time.

        Args:
            usage: Provider-reported counters for one model call.
            seconds: Time from that call's first streamed data to its terminal
                response, clamped at zero.
            first_chunk_tokens: Tokens the call's first streamed chunk carried in
                that same span's opening; zero when the call is replayed from
                storage, which does not record the boundary.
            context_tokens: How full the context is after this call; ``None``
                keeps the previous reading, which is all a call that reported no
                input can say.
        """
        return replace(
            self,
            input_tokens=self.input_tokens + usage.input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
            cache_read_tokens=self.cache_read_tokens + usage.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + usage.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + usage.reasoning_tokens,
            first_chunk_tokens=self.first_chunk_tokens + max(0, first_chunk_tokens),
            seconds=self.seconds + max(0.0, seconds),
            requests=self.requests + 1,
            # A call that reported no input says nothing about the size of the context, so the last reading stands:
            # a zero would hide the share until the next answer.
            context_tokens=(usage.input_tokens or self.context_tokens) if context_tokens is None else context_tokens,
        )

    def to_payload(self) -> dict[str, int | float]:
        """Return the JSON-serializable form carried by the custom event."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "first_chunk_tokens": self.first_chunk_tokens,
            "seconds": self.seconds,
            "requests": self.requests,
            "context_tokens": self.context_tokens,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> UsageSnapshot:
        """Rebuild a snapshot from a custom event payload, ignoring junk."""

        def count(key: str) -> int:
            value = payload.get(key)
            return int(value) if isinstance(value, (int, float)) else 0

        def seconds(key: str) -> float:
            value = payload.get(key)
            return float(value) if isinstance(value, (int, float)) else 0.0

        return cls(
            input_tokens=count("input_tokens"),
            output_tokens=count("output_tokens"),
            cache_read_tokens=count("cache_read_tokens"),
            cache_write_tokens=count("cache_write_tokens"),
            reasoning_tokens=count("reasoning_tokens"),
            first_chunk_tokens=count("first_chunk_tokens"),
            seconds=seconds("seconds"),
            requests=count("requests"),
            context_tokens=count("context_tokens"),
        )


def _generated_text(event: ModelEvent) -> str:
    """Return what one streamed event generated, empty for an event that wrote nothing.

    Reasoning, answer text, a tool's name and arguments, and hosted-tool input are all tokens the provider generated
    and charged to ``output_tokens``; a server tool starting or finishing carries none of them.
    """
    if event.type in (ModelEventType.TEXT_DELTA, ModelEventType.REASONING_DELTA):
        return event.delta
    if event.type is ModelEventType.TOOL_CALL_DELTA and event.tool_call_delta is not None:
        return event.tool_call_delta.name_delta + event.tool_call_delta.arguments_delta
    if event.type is ModelEventType.SERVER_TOOL_INPUT_DELTA and event.server_tool_input_delta is not None:
        return event.server_tool_input_delta.delta
    return ""


def _estimated_tokens(text: str) -> int:
    """Return a rough count for one streamed fragment, for a host that wired no counter.

    Only ever asked about a first chunk, a few tokens long, so four characters to the token keeps the subtraction from
    swinging the rate. The built-in usage plugin passes ``CompactionCounter.count_text`` instead, whose encoding it has
    already warmed; this default is what a test or another host gets.
    """
    return max(1, round(len(text) / 4))


def _stored_generation_seconds(timing: MessageTiming) -> float:
    """Return the span between the first and last segment a stored reply recorded.

    The store marks reasoning and content arrivals, not tool-call arguments and
    not the provider's first byte. The span is therefore shorter than the live
    one when a tool call follows reasoning, and there is no measurement at all
    when neither segment was recorded; the whole-call duration is not
    substituted, because it contains exactly the wait this change excludes.
    The live counter does start on a tool-call delta, so a stored tool-only
    reply contributes output tokens with no time, which can make a resumed
    session's rate read high.
    """
    starts = [moment for moment in (timing.reasoning_started_at, timing.content_started_at) if moment is not None]
    ends = [moment for moment in (timing.reasoning_completed_at, timing.content_completed_at) if moment is not None]
    if starts and ends:
        return max(0.0, (max(ends) - min(starts)).total_seconds())
    return 0.0


def session_usage(lines: Sequence[MessageLine]) -> UsageSnapshot:
    """Return the totals a stored branch adds up to: what every recorded reply used, oldest first.

    Needs no message decoded, which is why reading a long session for its totals is cheap. A line records the provider's
    counters and when each segment arrived, not how much the opening chunk carried, so a replayed branch leaves that at
    zero and its rate reads a little high, by one chunk out of however much the branch generated.
    """
    usage = UsageSnapshot()
    for line in lines:
        if line.usage is not None:
            usage = usage.with_usage(line.usage, _stored_generation_seconds(line.timing))
    return usage


class UsageExtension(AgentExtension):
    """Accumulate per-session token usage and publish it after every model call."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        count_chunk: Callable[[str], int] | None = None,
        count_context: Callable[[Sequence[AnyMessage]], int] | None = None,
    ) -> None:
        """Start with no totals and a monotonic clock the tests can replace.

        Args:
            clock: Time source used to measure generation; it must be monotonic
                so a wall-clock correction cannot skew the rate.
            count_chunk: Token counter for the first streamed chunk, which the
                rate takes out of the numerator. The default estimates from
                length; the shell passes the counter whose encoding it warmed.
            count_context: Token counter for a conversation, used only when a
                provider omits its usage counters. Without one the previous
                reading stands, which is what a provider that never answered
                leaves behind.
        """
        self.clock = clock
        self.count_chunk = count_chunk or _estimated_tokens
        self.count_context = count_context
        #: Generation time and opening chunk tokens by request context: first
        #: streamed data to terminal response, filled by the model middleware
        #: and consumed by after_model.
        self._spans: WeakKeyDictionary[AgentRunContext, tuple[float, int]] = WeakKeyDictionary()
        #: Per session, the last input a provider reported and how many messages
        #: there were then, so a silent provider can be answered by counting only
        #: what arrived since.
        self._baselines: dict[str, tuple[int, int]] = {}
        #: Per session, how many messages the previous call saw, so a conversation
        #: that did not grow can be recognised as one that was replaced.
        self._lengths: dict[str, int] = {}
        self._totals: dict[str, UsageSnapshot] = {}

    def snapshot(self, session_id: str) -> UsageSnapshot:
        """Return one session's running totals, zeros when it never answered."""
        return self._totals.get(session_id, UsageSnapshot())

    def seed(self, session_id: str, snapshot: UsageSnapshot) -> None:
        """Replace one session's totals, as when a stored branch is replayed."""
        self._totals[session_id] = snapshot

    async def on_model_request(
        self, context: AgentRunContext, request: ModelRequest, call_next: ModelRequestNext
    ) -> AsyncIterator[ModelEvent]:
        """Measure one call from its first streamed data to its terminal response."""
        # The span belongs to this call: drop one a previous, failed call left.
        self._spans.pop(context, None)
        first: float | None = None
        opening = 0
        # ``call_next`` widens to AsyncIterator, which aclosing cannot close; the
        # provider stream behind it is an async generator.
        stream = cast("AsyncGenerator[ModelEvent]", call_next(request))
        async with aclosing(stream) as events:
            async for event in events:
                if event.type is ModelEventType.RESPONSE:
                    if first is not None:
                        self._spans[context] = (max(0.0, self.clock() - first), opening)
                else:
                    generated = _generated_text(event)
                    if first is None:
                        # A chunk that generated nothing — a server tool starting, say — does not open the clock:
                        # the wait it covers produced no token, and timing it would understate the rate.
                        if generated:
                            first = self.clock()
                            opening = self.count_chunk(generated)
                yield event

    def _context_tokens(self, session_id: str, context: AgentRunContext, usage: ModelUsage) -> int | None:
        """Return how full the context is, measuring it when the provider did not say.

        A provider that omits usage answers zero, and zero is not a measurement: keeping an earlier reading would leave
        the figure standing still while the conversation grows, so the share would silently stop moving. The last input
        a provider did report is the baseline, and only what was appended since is counted, which is how zett-agent's
        own compaction keeps its threshold honest under a provider that reports nothing. Before any provider has
        answered there is no baseline and the whole conversation is counted.

        The reply is already in the conversation when this runs, and the prompt it answered does not contain it, so the
        baseline pairs that prompt with that answer. Counting a baseline of the prompt alone would drop one whole reply
        from the figure every time the provider stayed quiet.
        """
        messages = context.state.messages
        length = len(messages)
        seen_before = self._lengths.get(session_id)
        self._lengths[session_id] = length
        if seen_before is not None and length <= seen_before:
            # A running session only grows, so a length that did not means a compaction or a branch switch replaced
            # the conversation: a baseline counted against the old messages no longer describes anything.
            self._baselines.pop(session_id, None)
        if usage.input_tokens > 0:
            self._baselines[session_id] = (usage.input_tokens + usage.output_tokens, length)
            return usage.input_tokens
        if self.count_context is None:
            return None
        baseline = self._baselines.get(session_id)
        if baseline is None:
            return self.count_context(messages)
        reported, seen = baseline
        return reported + self.count_context(messages[seen:])

    async def after_model(self, context: AgentRunContext, response: ModelResponse) -> None:
        """Add this call's counters and publish the new totals as a custom event."""
        session_id = cast(str, context.config.session_id)
        seconds, opening = self._spans.pop(context, (0.0, 0))
        totals = self.snapshot(session_id).with_usage(
            response.usage,
            seconds,
            first_chunk_tokens=opening,
            context_tokens=self._context_tokens(session_id, context, response.usage),
        )
        self.seed(session_id, totals)
        await context.emit(
            AgentEvent(
                type=AgentEventType.CUSTOM,
                session_id=session_id,
                name=USAGE_EVENT_NAME,
                payload=totals.to_payload(),
            )
        )
