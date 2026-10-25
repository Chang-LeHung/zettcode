"""The plain values the SDK hands back.

Every one is a frozen dataclass owned by the SDK, not a view of an internal class, so the program does not break
when the application reorganizes its inside, and every one can be built by hand in a test. They carry no behaviour
beyond arithmetic on their own fields.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .events import Event

__all__ = [
    "Compaction",
    "ContextReport",
    "ContextShare",
    "DayTotals",
    "Delivered",
    "Image",
    "IncomingMessage",
    "MentionInfo",
    "Message",
    "ModelCheck",
    "ModelInfo",
    "ModelTotals",
    "Receipt",
    "ResumeInfo",
    "RunResult",
    "SessionInfo",
    "SessionStatsInfo",
    "SessionTotals",
    "StoredSession",
    "TaskInfo",
    "ToolCallInfo",
    "ToolRecord",
    "Totals",
    "Usage",
    "WorkspaceUsage",
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
        compact_percent: Share of the window, in percent, at which a request is summarized first (80 by default).
        web_search: Whether the provider searches the web for this model.
        web_search_name: The tool type that search is sent as, when the entry names one; ``None`` takes the default
            for the API it speaks.
        display_model: The name the picker shows, when the entry has one.
        base_url: The address requests go to, or ``None`` for the API's own.
        api: The protocol the entry speaks: ``chat``, ``responses`` or ``anthropic``.
        temperature: The sampling temperature the entry sends, or ``None`` for the provider's own.
    """

    name: str
    model: str
    context_window: int
    multimodal: bool
    efforts: tuple[str, ...]
    active: bool = False
    compact_percent: float = 80.0
    web_search: bool = False
    web_search_name: str | None = None
    display_model: str | None = None
    base_url: str | None = None
    api: str = "chat"
    temperature: float | None = None


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
class StoredSession:
    """A conversation read from the store and not yet current: what :meth:`Sessions.read` returns.

    Attributes:
        id: The session's identity.
        title: Its name, or ``None`` until one was written.
        model: The model it last used, by the name ``models`` lists, or ``None`` when none was recorded.
        usage: What it has spent in total, from the replies the file records.
        records: The parsed conversation file, for a front end that draws the conversation itself. Its type belongs to
            the engine and is not part of this API: read it with the helper of the front end that draws it, and do not
            depend on its shape.
    """

    id: str
    title: str | None
    model: str | None
    usage: Usage
    records: object = field(repr=False, compare=False)
    _engine: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """One step of the plan the model keeps for a session.

    Attributes:
        status: ``pending``, ``in_progress`` or ``completed``.
        content: What the step says.
    """

    status: str
    content: str


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
        role: ``user``, ``assistant`` or ``tool``; ``summary`` for the text a compaction left in place of the
            older messages, which nobody typed.
        text: What was said. For a user message it is what the person typed, not the instructions an ``@``
            reference added behind it.
        tool_calls: For an assistant message, the tools it asked for.
        tool_call_id: For a tool message, the call it answers.
        tool_name: For a tool message, the tool.
        ok: For a tool message, whether the call succeeded.
        images: How many images the message carries.
        pictures: For a user message, the images themselves, so a client that reopens the session can show them
            again. A tool message's images are counted but not returned.
        usage: For an assistant message, what its model call spent, when the store recorded it.
        seconds: How long the message took to produce: the model call for an assistant message, the run for a tool
            message, and nothing for a user message.
    """

    role: str
    text: str
    tool_calls: tuple[ToolCallInfo, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    ok: bool = True
    images: int = 0
    usage: Usage | None = None
    seconds: float = 0.0
    pictures: tuple[Image, ...] = ()


@dataclass(frozen=True, slots=True)
class MentionInfo:
    """One ``@`` resource a prompt can reference, as the completion menu lists it.

    Attributes:
        token: The text as typed, ``@name``.
        kind: What owns it: ``"file"``, ``"skill"``, or the name a plugin gives its own kind.
        name: The resource without the ``@``; a file's path is relative to the workspace.
        description: One line for a menu.
    """

    token: str
    kind: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """A message another ZettCode session sent, as the broker delivered it.

    Attributes:
        sender_id: The sending session's id; the stable way to answer it, because a handle can change.
        sender: The sender's handle when it sent the message.
        text: What it said.
        via: ``"user"`` when its reader typed it, ``"agent"`` when its agent sent it, ``"external"`` when the
            sender is a program that is not a ZettCode session.
        hops: How many sessions the message has passed through; an agent's answer carries it on, which ends two
            agents that keep answering each other.
    """

    sender_id: str
    sender: str
    text: str
    via: str = "agent"
    hops: int = 1


@dataclass(frozen=True, slots=True)
class Receipt:
    """What a program says about a message another session sent it: the answer to the sender.

    Attributes:
        accepted: Whether it took the message. A refusal carries its reason to the sender.
        reason: Why not, in words the sender's model can act on.
        disposition: What will happen to it: ``"started"`` (a turn began), or ``"queued"`` (it waits for the current
            request to end).
    """

    accepted: bool
    reason: str = ""
    disposition: str = ""


@dataclass(frozen=True, slots=True)
class Delivered:
    """The answer to a send: who took the message, and what they will do with it.

    Attributes:
        to: The handle of the session that took it.
        disposition: ``"started"`` (a turn began there) or ``"queued"`` (it waits for the request running there).
    """

    to: str
    disposition: str


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

    @property
    def measured(self) -> int:
        """Return the tokens the tokenizer counted, which ``shares`` add up to (``used`` may be the provider's own)."""
        return sum(share.tokens for share in self.shares)

    @property
    def estimated(self) -> bool:
        """Return whether ``shares`` are a characters-per-token estimate and not a tokenizer's count."""
        return "chars/token" in self.measured_by

    def percent(self, tokens: int) -> float:
        """Return ``tokens`` as a share of the window, in percent: how full the model's window is."""
        return tokens / self.window * 100 if self.window else 0.0

    def share(self, tokens: int) -> float:
        """Return ``tokens`` as a share of what the tokenizer counted, in percent: where the context goes.

        It divides by :attr:`measured` and never by a provider's total for the same request, which would leave the
        rows short of a hundred.
        """
        return tokens / self.measured * 100 if self.measured else 0.0


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


@dataclass(frozen=True, slots=True)
class Totals:
    """Token counters added up over some replies: what the usage ledger reports.

    A tally is read back from the stored conversations, so it has no wall-clock seconds and no context size — those
    belong to a call, not to a record. :attr:`Usage` is what one session or run spent now.

    Attributes:
        requests: Model replies counted.
        input_tokens: Everything sent, cache reads included.
        output_tokens: Everything generated, reasoning included.
        cache_read_tokens: The part of the input the provider served from its cache.
        reasoning_tokens: The reasoning part of the output.
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return everything sent plus everything generated."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_share(self) -> float | None:
        """Return the share of the input the provider served from its cache, or ``None`` before there is input."""
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else None


@dataclass(frozen=True, slots=True)
class SessionTotals:
    """One session in the workspace's ledger: what it spent, and how long it is.

    Attributes:
        id: The session's identity.
        title: Its name, or ``None`` until one was written.
        started: When its first record was written.
        updated: When its conversation last changed.
        tokens: What it spent.
        models: The models it was charged under, in the order they were used.
        entries: Message records the conversation file holds.
    """

    id: str
    title: str | None
    started: datetime
    updated: datetime
    tokens: Totals
    models: tuple[str, ...]
    entries: int = 0


@dataclass(frozen=True, slots=True)
class ModelTotals:
    """What one model was charged across the workspace."""

    model: str
    tokens: Totals


@dataclass(frozen=True, slots=True)
class DayTotals:
    """What one day spent across the workspace."""

    day: date
    tokens: Totals


@dataclass(frozen=True, slots=True)
class WorkspaceUsage:
    """What a workspace's stored sessions have spent, as the ``/usage`` page shows it.

    Attributes:
        sessions: One entry per session, most recently active first.
        models: One entry per model, busiest first.
        days: One entry per day that spent anything, oldest first.
        total: Everything together.
    """

    sessions: tuple[SessionTotals, ...]
    models: tuple[ModelTotals, ...]
    days: tuple[DayTotals, ...]
    total: Totals


@dataclass(frozen=True, slots=True)
class SessionStatsInfo:
    """The totals one row of the ``/resume`` panel shows, read from the store.

    Attributes:
        id: The session.
        entries: Message records its conversation holds.
        requests: Model replies it was charged for; a fork is not charged for the replies it copied.
        input_tokens: Everything sent, cache reads included.
        output_tokens: Everything generated, reasoning included.
        cache_read_tokens: The part of the input the provider served from its cache.
        reasoning_tokens: The reasoning part of the output.
    """

    id: str
    entries: int = 0
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return everything sent plus everything generated."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_share(self) -> float | None:
        """Return the cached share of the input, or ``None`` before there was any."""
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else None


@dataclass(frozen=True, slots=True)
class ModelCheck:
    """One configured model, asked one short question by :meth:`~zettcode.sdk.Client.check_models`.

    Attributes:
        model: The name the configuration shows it by.
        model_id: The id sent to the endpoint.
        ok: Whether it answered.
        seconds: How long the answer, or the failure, took.
        detail: The reply when it answered; the provider's reason when it did not.
        input_tokens: What the answer cost, when the provider said.
        output_tokens: What it generated, when the provider said.
    """

    model: str
    model_id: str
    ok: bool
    seconds: float
    detail: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
