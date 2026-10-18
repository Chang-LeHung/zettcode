"""The plain values the SDK hands back.

Every one is a frozen dataclass owned by the SDK, not a view of an internal class, so the program does not break
when the application reorganizes its inside, and every one can be built by hand in a test. They carry no behaviour
beyond arithmetic on their own fields.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .events import Event

__all__ = [
    "Compaction",
    "ContextReport",
    "ContextShare",
    "Image",
    "Message",
    "ModelInfo",
    "ResumeInfo",
    "RunResult",
    "SessionInfo",
    "ToolCallInfo",
    "ToolRecord",
    "Usage",
]

#: Media types a model accepts as an image; anything else is rejected before it reaches the provider.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counters, for one run or for a whole session.

    ``input_tokens`` already contains the cache reads and writes, and ``output_tokens`` already contains the
    reasoning, so :attr:`total_tokens` is the plain sum and nothing is counted twice.

    Attributes:
        input_tokens: Everything sent to the model.
        output_tokens: Everything the model generated.
        cache_read_tokens: Input the provider served from its cache.
        cache_write_tokens: Input written into the provider's cache.
        reasoning_tokens: The reasoning part of ``output_tokens``.
        seconds: Wall time spent inside model calls.
        requests: How many model calls were made.
        context_tokens: How full the context was on the newest call; for a delta, the value after the run.
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
        """Return input plus output."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float | None:
        """Return the cached share of the input, or ``None`` before there is any input."""
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else None

    @property
    def output_rate(self) -> float | None:
        """Return generated tokens per second of model time, or ``None`` when no time was measured."""
        return self.output_tokens / self.seconds if self.seconds > 0 else None

    def since(self, earlier: Usage) -> Usage:
        """Return what was spent after ``earlier``: the counters subtracted, never below zero.

        ``context_tokens`` is a level, not a counter, so it is this usage's own. The subtraction is clamped because
        a session switched or replayed between the two readings can make a counter go backwards, and a negative
        spend is never a true statement.
        """
        values = {
            item.name: max(0, getattr(self, item.name) - getattr(earlier, item.name))
            for item in fields(self)
            if item.name not in ("context_tokens", "seconds")
        }
        return Usage(
            **values,
            seconds=max(0.0, self.seconds - earlier.seconds),
            context_tokens=self.context_tokens,
        )


@dataclass(frozen=True, slots=True)
class Image:
    """An image to send with a prompt.

    Attributes:
        data: The encoded file, not decoded pixels.
        media_type: ``image/png``, ``image/jpeg``, ``image/gif`` or ``image/webp``.
    """

    data: bytes
    media_type: str

    def __post_init__(self) -> None:
        """Reject what no model would accept, so the error is here and not a provider's 400."""
        if not isinstance(self.data, (bytes, bytearray)) or not self.data:
            raise ValueError("An image needs its encoded bytes")
        if self.media_type not in IMAGE_TYPES:
            raise ValueError(
                f"Unsupported image type {self.media_type!r}; use one of: {', '.join(sorted(IMAGE_TYPES))}"
            )

    @classmethod
    def from_path(cls, path: str | Path) -> Image:
        """Read an image file, taking the media type from its extension.

        Raises:
            ValueError: The extension is not an image type a model takes, or the file is empty.
            OSError: The file cannot be read.
        """
        file = Path(path)
        media_type = mimetypes.guess_type(file.name)[0] or ""
        return cls(file.read_bytes(), media_type)


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One configured model.

    Attributes:
        name: What to pass to ``use_model``: the display name when the entry has one, else the model id.
        model: The model id sent to the endpoint.
        context_window: Tokens it can carry.
        multimodal: Whether it accepts images.
        efforts: The reasoning levels it accepts, cheapest first.
        active: Whether it is the model the next run uses.
    """

    name: str
    model: str
    context_window: int
    multimodal: bool
    efforts: tuple[str, ...]
    active: bool = False


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """One stored session, as a list shows it.

    Attributes:
        id: The session's identity; pass it to ``sessions.open``.
        title: Its name, or ``None`` until one was written.
        created_at: When its first record was written.
        updated_at: When its conversation last changed.
    """

    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ToolCallInfo:
    """A tool call the model made.

    Attributes:
        id: Identity that ties the call to its result.
        name: The tool.
        arguments: What it was called with.
    """

    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolRecord:
    """A tool call and how it ended, as :class:`RunResult` lists them.

    Attributes:
        id: Identity of the call.
        name: The tool.
        arguments: What it was called with.
        output: What it returned, or the failure text.
        ok: Whether it ran to success; a skipped call is not.
        skipped: Whether it never ran because steering took over.
    """

    id: str
    name: str
    arguments: dict[str, object]
    output: str
    ok: bool
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class Message:
    """One message of a stored conversation.

    Attributes:
        role: ``user``, ``assistant`` or ``tool``.
        text: What was said. For a user message it is what the person typed, not the instructions an ``@``
            reference added behind it.
        tool_calls: For an assistant message, the tools it asked for.
        tool_call_id: For a tool message, the call it answers.
        tool_name: For a tool message, the tool.
        ok: For a tool message, whether the call succeeded.
        images: How many images the message carries; their bytes are not kept in the history.
    """

    role: str
    text: str
    tool_calls: tuple[ToolCallInfo, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    ok: bool = True
    images: int = 0


@dataclass(frozen=True, slots=True)
class ContextShare:
    """One source's share of the context.

    Attributes:
        name: The source, such as ``Tool output``.
        tokens: Tokens it contributes.
        items: Messages, tools or summaries counted into ``tokens``.
    """

    name: str
    tokens: int
    items: int = 0


@dataclass(frozen=True, slots=True)
class ContextReport:
    """What the next request would carry, and how full the context is.

    Attributes:
        window: Tokens the model can carry.
        used: Tokens the request carries: the provider's own count when it gave one, else the tokenizer's.
        measured_by: The counter behind ``shares``.
        shares: One entry per non-empty source.
        partial: Whether a part of the request could not be measured yet, so ``used`` reads low.
        from_provider: Whether ``used`` is the provider's count.
    """

    window: int
    used: int
    measured_by: str
    shares: tuple[ContextShare, ...] = ()
    partial: bool = False
    from_provider: bool = False

    @property
    def free(self) -> int:
        """Return the tokens left, never negative."""
        return max(0, self.window - self.used)

    @property
    def fraction(self) -> float:
        """Return how full the context is, from 0 up to 1 (more only if the count exceeds the window)."""
        return self.used / self.window if self.window > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Compaction:
    """A conversation summarized to make room.

    Attributes:
        summary: The text that now stands in for the older messages.
        compressed: How many messages were folded into it.
        kept: How many were kept as they were.
    """

    summary: str
    compressed: int
    kept: int


@dataclass(frozen=True, slots=True)
class ResumeInfo:
    """Where an interrupted request stopped and what continuing would do.

    Attributes:
        kind: How it was interrupted.
        description: One sentence for a person.
    """

    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a finished run came to.

    Attributes:
        text: The model's final answer.
        session_id: The session the run belongs to.
        usage: What the run spent, not the session's total.
        tools: Every tool call the run made, in order, with how each ended.
        stop: ``None`` when the model finished normally, else why it stopped (``refusal``, ``max_output``, ...).
        stop_message: The provider's sentence about a stop, when it gave one.
        questions: The questions the model asked, in order.
        events: Every event of the run, when it was asked to keep them.
    """

    text: str
    session_id: str
    usage: Usage = field(default_factory=Usage)
    tools: tuple[ToolRecord, ...] = ()
    stop: str | None = None
    stop_message: str | None = None
    questions: tuple[str, ...] = ()
    events: tuple[Event, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the model finished on its own: no refusal, cut-off or interruption."""
        return self.stop is None

    @property
    def failed_tools(self) -> tuple[ToolRecord, ...]:
        """Return the tool calls that did not succeed."""
        return tuple(tool for tool in self.tools if not tool.ok)
