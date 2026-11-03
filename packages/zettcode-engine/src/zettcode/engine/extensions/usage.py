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
        seconds: Time from the first token of each call to that call's terminal
            response, summed: the window output was generated in, the rate's
            denominator.
        requests: Model calls counted, zero before the first answer.
        context_tokens: Input tokens the newest call carried, which is how full
            the context is right now; zero before the first answer.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
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

        The numerator is the provider's own count, and the denominator is the time from the first token to the end of
        the response, both taken from the runtime's stream measurements. Counting the tokens that arrived with the
        first chunk against a window that opens at that chunk reads a little high — those tokens were made before the
        window — and that is the error this trades for: a rate that is never understated by a clock the program runs
        itself, and one number for every provider instead of one per protocol.

        A session that mixed in a call the runtime could not time keeps that call's tokens in the numerator and adds no
        seconds for it, so the figure reads high; it is still the rate over the calls that were measured.
        """
        return self.output_tokens / self.seconds if self.seconds > 0 and self.output_tokens > 0 else None

    def with_usage(self, usage: ModelUsage, seconds: float, *, context_tokens: int | None = None) -> UsageSnapshot:
        """Return these totals plus one model call and its measured generation time.

        Args:
            usage: Provider-reported counters for one model call.
            seconds: Time from that call's first token to its terminal response,
                clamped at zero; zero when the call streamed nothing to measure.
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
            seconds=seconds("seconds"),
            requests=count("requests"),
            context_tokens=count("context_tokens"),
        )


def _stored_generation_seconds(timing: MessageTiming, usage: ModelUsage | None) -> float:
    """Return the span between the first and last segment a stored reply recorded.

    The line's own usage carries the first token's arrival when the runtime measured it, which is what a reply stored
    by this version does: the window is then the call's duration less that wait, the same subtraction the live counter
    makes. A line written before that measurement existed has only the segment marks — reasoning and content arrivals,
    not tool-call arguments and not the provider's first byte — so the span between them stands in; it is shorter than
    the live window when a tool call follows reasoning, and there is no measurement at all when neither segment was
    recorded.
    """
    if usage is not None and usage.ttft_any_ns is not None:
        return max(0.0, (timing.duration_ns - usage.ttft_any_ns) / 1e9)
    starts = [moment for moment in (timing.reasoning_started_at, timing.content_started_at) if moment is not None]
    ends = [moment for moment in (timing.reasoning_completed_at, timing.content_completed_at) if moment is not None]
    if starts and ends:
        return max(0.0, (max(ends) - min(starts)).total_seconds())
    return 0.0


def session_usage(lines: Sequence[MessageLine]) -> UsageSnapshot:
    """Return the totals a stored branch adds up to: what every recorded reply used, oldest first.

    Needs no message decoded, which is why reading a long session for its totals is cheap. Each line records the
    provider's counters, when the call started and ended, and when its first token arrived, so a replayed branch
    divides by the window the runtime recorded, where a live one measures its own — a gap the width of the entry into
    this program's middleware, not an error.
    """
    usage = UsageSnapshot()
    for line in lines:
        if line.usage is not None:
            usage = usage.with_usage(line.usage, _stored_generation_seconds(line.timing, line.usage))
    return usage


class UsageExtension(AgentExtension):
    """Accumulate per-session token usage and publish it after every model call."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        count_context: Callable[[Sequence[AnyMessage]], int] | None = None,
    ) -> None:
        """Start with no totals and a monotonic clock the tests can replace.

        Args:
            clock: Time source used to measure a call; it must be monotonic so a
                wall-clock correction cannot skew the rate.
            count_context: Token counter for a conversation, used only when a
                provider omits its usage counters. Without one the previous
                reading stands, which is what a provider that never answered
                leaves behind.
        """
        self.clock = clock
        self.count_context = count_context
        #: Whole-call time by request context, from the call's start to its
        #: terminal response, filled by the model middleware and consumed by
        #: after_model, which takes the first token's wait out of it.
        self._spans: WeakKeyDictionary[AgentRunContext, float] = WeakKeyDictionary()
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
        """Measure one call from its start to its terminal response.

        The whole call, and not just the streaming part: the first token's own wait has to be known to be taken out of
        it, and that measurement is the runtime's (``ModelUsage.ttft_any_ns``), not this clock's. What is kept here is
        the span the runtime cannot see — when this program asked and when the answer ended.
        """
        started = self.clock()
        # ``call_next`` widens to AsyncIterator, which aclosing cannot close; the
        # provider stream behind it is an async generator.
        stream = cast("AsyncGenerator[ModelEvent]", call_next(request))
        async with aclosing(stream) as events:
            async for event in events:
                if event.type is ModelEventType.RESPONSE:
                    self._spans[context] = max(0.0, self.clock() - started)
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
        # The window output was generated in: the whole call less the wait for its first token. A call that streamed
        # nothing has no first token to start from, so it adds no time. Its tokens still count, so a session that mixed
        # such a call in reads high rather than "not measured".
        waited = response.usage.ttft_any_ns
        span = self._spans.pop(context, 0.0)
        seconds = 0.0 if waited is None else span - waited / 1e9
        totals = self.snapshot(session_id).with_usage(
            response.usage,
            seconds,
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
