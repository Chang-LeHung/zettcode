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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from time import monotonic
from typing import cast

from zett_agent.agent import AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.base import AgentExtension
from zett_agent.model import ModelRequest, ModelResponse, ModelUsage

from ...tui import ARROW_DOWN, ARROW_UP, SEPARATOR

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
        seconds: Wall time spent inside model calls, the rate denominator.
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
        """Return generated tokens per second of model time, if time was measured."""
        return self.output_tokens / self.seconds if self.seconds > 0 else None

    def with_usage(self, usage: ModelUsage, seconds: float) -> UsageSnapshot:
        """Return these totals plus one model call and its measured wall time.

        Args:
            usage: Provider-reported counters for one model call.
            seconds: Time that call spent generating, clamped at zero.
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
            context_tokens=usage.input_tokens,
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


def compact_tokens(count: int) -> str:
    """Shorten a token count for the status line: ``912``, ``12.3k``, ``1.2M``."""
    if count < 1_000:
        return str(count)
    if count < 999_950:
        return f"{count / 1_000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def usage_text(snapshot: UsageSnapshot) -> str:
    """Render the status-line summary, or an empty string before the first call."""
    if not snapshot.requests:
        return ""
    parts = [f"{ARROW_UP}{compact_tokens(snapshot.input_tokens)} {ARROW_DOWN}{compact_tokens(snapshot.output_tokens)}"]
    rate = snapshot.cache_hit_rate
    if rate is not None:
        parts.append(f"{rate * 100:.1f}% cached")
    speed = snapshot.output_rate
    if speed is not None:
        parts.append(f"{speed:.0f} tok/s" if speed >= 10 else f"{speed:.1f} tok/s")
    return "  " + f" {SEPARATOR} ".join(parts)


def context_text(snapshot: UsageSnapshot, window: int) -> str:
    """Render how much of the model's window the newest request filled.

    Args:
        snapshot: Session counters; only the newest call's input matters here.
        window: Tokens the model can carry, from its configuration.

    Returns:
        A short ``"· ctx 34.0%"`` fragment, or ``""`` before any request has been
        measured or when the model does not declare a window. The leading
        separator is part of the fragment, so it joins the usage counters the
        same way they join each other.
    """
    if not snapshot.requests or window < 1 or snapshot.context_tokens < 1:
        return ""
    share = min(100.0, snapshot.context_tokens * 100 / window)
    return f" {SEPARATOR} ctx {share:.1f}%"


class UsageExtension(AgentExtension):
    """Accumulate per-session token usage and publish it after every model call."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        """Start with no totals and a monotonic clock the tests can replace.

        Args:
            clock: Time source used to measure a model call's wall time; it must
                be monotonic so a wall-clock correction cannot skew the rate.
        """
        self.clock = clock
        self._started: dict[str, float] = {}
        self._totals: dict[str, UsageSnapshot] = {}

    def snapshot(self, session_id: str) -> UsageSnapshot:
        """Return one session's running totals, zeros when it never answered."""
        return self._totals.get(session_id, UsageSnapshot())

    def seed(self, session_id: str, snapshot: UsageSnapshot) -> None:
        """Replace one session's totals, as when a stored branch is replayed."""
        self._totals[session_id] = snapshot

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Stamp the clock that turns the next answer into a token rate."""
        # The runtime replaces an empty session_id before hooks run.
        self._started[cast(str, context.config.session_id)] = self.clock()

    async def after_model(self, context: AgentRunContext, response: ModelResponse) -> None:
        """Add this call's counters and publish the new totals as a custom event."""
        session_id = cast(str, context.config.session_id)
        started = self._started.pop(session_id, None)
        seconds = self.clock() - started if started is not None else 0.0
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
