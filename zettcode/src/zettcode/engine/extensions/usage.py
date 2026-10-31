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
        seconds: Time from the first streamed data to the terminal response,
            the rate denominator.
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
        """Return generated tokens per second of generation time, if it was measured."""
        return self.output_tokens / self.seconds if self.seconds > 0 else None

    def with_usage(self, usage: ModelUsage, seconds: float) -> UsageSnapshot:
        """Return these totals plus one model call and its measured generation time.

        Args:
            usage: Provider-reported counters for one model call.
            seconds: Time from that call's first streamed data to its terminal
                response, clamped at zero.
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
            context_tokens=usage.input_tokens or self.context_tokens,
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

    Needs no message decoded, which is why reading a long session for its totals is cheap.
    """
    usage = UsageSnapshot()
    for line in lines:
        if line.usage is not None:
            usage = usage.with_usage(line.usage, _stored_generation_seconds(line.timing))
    return usage


class UsageExtension(AgentExtension):
    """Accumulate per-session token usage and publish it after every model call."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        """Start with no totals and a monotonic clock the tests can replace.

        Args:
            clock: Time source used to measure generation; it must be monotonic
                so a wall-clock correction cannot skew the rate.
        """
        self.clock = clock
        #: Generation time by request context: first streamed data to terminal
        #: response, filled by the model middleware and consumed by after_model.
        self._spans: WeakKeyDictionary[AgentRunContext, float] = WeakKeyDictionary()
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
        # ``call_next`` widens to AsyncIterator, which aclosing cannot close; the
        # provider stream behind it is an async generator.
        stream = cast("AsyncGenerator[ModelEvent]", call_next(request))
        async with aclosing(stream) as events:
            async for event in events:
                if event.type is ModelEventType.RESPONSE:
                    if first is not None:
                        self._spans[context] = max(0.0, self.clock() - first)
                elif first is None:
                    # Reasoning, answer text, tool arguments and server-tool
                    # events are all generated output the provider streamed.
                    first = self.clock()
                yield event

    async def after_model(self, context: AgentRunContext, response: ModelResponse) -> None:
        """Add this call's counters and publish the new totals as a custom event."""
        session_id = cast(str, context.config.session_id)
        seconds = self._spans.pop(context, 0.0)
        totals = self.snapshot(session_id).with_usage(response.usage, seconds)
        self.seed(session_id, totals)
        await context.emit(
            AgentEvent(
                type=AgentEventType.CUSTOM,
                session_id=session_id,
                name=USAGE_EVENT_NAME,
                payload=totals.to_payload(),
            )
        )
