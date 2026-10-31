"""The plain values the SDK hands back.

Every one is a frozen dataclass owned by the SDK, not a view of an internal class, so the program does not break
when the application reorganizes its inside, and every one can be built by hand in a test. They carry no behaviour
beyond arithmetic on their own fields.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..modes import MODE_STEER

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .events import Event

__all__ = [
    "DIRECT_EMPTY",
    "DIRECT_FAILED",
    "DIRECT_UNFINISHED",
    "Compaction",
    "ContextReport",
    "ContextShare",
    "DaemonInfo",
    "DayTotals",
    "Delivered",
    "Image",
    "IncomingMessage",
    "MentionInfo",
    "Message",
    "ModelCheck",
    "ModelInfo",
    "ModelTotals",
    "Peer",
    "PluginEntry",
    "Receipt",
    "Relay",
    "ResumeInfo",
    "RunResult",
    "SendLimits",
    "SessionInfo",
    "SessionStatsInfo",
    "SessionTotals",
    "StoredSession",
    "StreamEvent",
    "TaskInfo",
    "ToolCallInfo",
    "ToolRecord",
    "Totals",
    "Usage",
    "WorkspaceUsage",
    "brief_of",
    "is_direct_notice",
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
        can_search: Whether the endpoint serves hosted web search at all (DeepSeek's chat endpoint does not).
        search_name: The tool type search is sent as: the entry's own, or the default for the API it speaks.
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
    can_search: bool = True
    search_name: str = ""

    @property
    def compaction_max_tokens(self) -> int:
        """Return the context size, in tokens, at which a request is summarized first."""
        return max(1, round(self.context_window * self.compact_percent / 100))


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
        relay: For a user message that another session sent, who sent it; ``None`` for what the reader typed.
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
    relay: Relay | None = None


@dataclass(frozen=True, slots=True)
class Relay:
    """Who sent a message that came from another session, as the conversation stored it.

    Attributes:
        sender_id: The sending session's id; the stable way to tell senders apart, because a handle can change.
        sender: The sender's handle when it sent the message.
        via: ``"user"`` when its reader typed it, ``"agent"`` when its agent sent it, ``"external"`` when the sender
            was a program that is not a ZettCode session.
        hops: How many sessions the message had passed through.
    """

    sender_id: str
    sender: str
    via: str = "agent"
    hops: int = 1


@dataclass(frozen=True, slots=True)
class Peer:
    """Another session that is registered with the broker right now.

    Attributes:
        session_id: The session's id; what a message is addressed to.
        handle: The word that follows an ``@`` to address it.
        title: What the session is about, or an empty string before it has a name.
        workspace: The directory it works in.
        status: ``"idle"`` or ``"working"``.
        kind: ``"zettcode"`` for a session, ``"external"`` for a program that stands in for one.
        direct: Whether it runs a message sent with ``direct=True`` as its reader's own prompt.
    """

    session_id: str
    handle: str
    title: str = ""
    workspace: str = ""
    status: str = "idle"
    kind: str = "zettcode"
    direct: bool = False


#: What a session sends back for a turn that did not end in an answer, so the sender is not left waiting.
#: They are shared by the sessions that send them and the gateway that shows them as notes rather than as replies.
DIRECT_FAILED = "The turn failed: "
DIRECT_UNFINISHED = "(the turn did not finish)"
DIRECT_EMPTY = "(the turn ended without a written answer)"


def is_direct_notice(text: str) -> bool:
    """Return whether a message is one of the lines a session sends when a turn ended without an answer."""
    return text.startswith(DIRECT_FAILED) or text in (DIRECT_UNFINISHED, DIRECT_EMPTY)


#: The arguments that say what a tool call is about, in the order they are looked for.
BRIEF_KEYS = ("command", "path", "file_path", "pattern", "query", "url", "to", "name", "description")


def brief_of(arguments: Mapping[str, object]) -> str:
    """Return one line saying what a tool call was about: its command, path, pattern or the like."""
    for key in BRIEF_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            line = " ".join(value.split())
            return line if len(line) <= 120 else line[:117] + "..."
    return ""


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One thing a watched session's running turn said, as it happened.

    Attributes:
        session_id: The session whose turn it is.
        kind: ``"begin"`` (a turn started), ``"text"`` (more of the answer), ``"thinking"`` (the model is reasoning),
            ``"tool"`` (a tool started), ``"tool_end"`` (it ended), ``"end"`` (the turn ended; what it produced is in
            the stored conversation).
        text: For ``"text"``, the new piece of the answer.
        call_id: For ``"tool"`` and ``"tool_end"``, which call.
        name: For ``"tool"``, the tool.
        brief: For ``"tool"``, one line saying what it was called on.
        ok: For ``"tool_end"``, whether it succeeded.
    """

    session_id: str
    kind: str
    text: str = ""
    call_id: str = ""
    name: str = ""
    brief: str = ""
    ok: bool | None = None


@dataclass(frozen=True, slots=True)
class SendLimits:
    """What the broker accepts from a sender, so a front end can refuse before it sends.

    Attributes:
        max_text: The longest message, in characters.
        rate_limit: Messages one sender may send in ``rate_window`` seconds.
        rate_window: The length of that window, in seconds.
        max_hops: How many sessions a chain of agent messages may pass through.
    """

    max_text: int = 32_000
    rate_limit: int = 20
    rate_window: float = 60.0
    max_hops: int = 6


@dataclass(frozen=True, slots=True)
class DaemonInfo:
    """One background agent, as ``daemon list`` shows it.

    Attributes:
        session_id: The session it runs, which is also the id other sessions message it by.
        workspace: The directory it works in, or an empty string when it never recorded one.
        status: ``starting``, ``idle``, ``working``, ``stopping``, ``dead`` (its process is gone) or ``unknown``.
        name: The label its starter gave it, saying what it is for.
        title: The session's own name, once the model has written one.
        model: The model it runs on.
        effort: The reasoning level it runs at, or ``None`` for the model's own.
        permission: The shell level: ``deny``, ``safe`` or ``full``.
        pid: Its process id, or ``0`` when it never recorded one.
        started_at: Seconds since the epoch when it started, or ``0.0``.
        input_tokens: Everything its session has sent to the model, or ``None`` when it has recorded none.
        output_tokens: Everything the model has generated for it, or ``None``.
        context_tokens: How full its context was on the newest call, or ``None``.
        context_window: The window of the model it runs on, or ``None``.
        requested_model: A model a reader asked for, not yet in force, or ``None``.
        requested_effort: A reasoning level a reader asked for, not yet in force, or ``None``.
        requested_error: Why the last requested model or level could not be put in force, or ``None``.
        broker: Whether the session broker was reachable at the last check, or ``None`` before one.
    """

    session_id: str
    workspace: str = ""
    status: str = "unknown"
    name: str | None = None
    title: str | None = None
    model: str | None = None
    effort: str | None = None
    permission: str | None = None
    pid: int = 0
    started_at: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_tokens: int | None = None
    context_window: int | None = None
    requested_model: str | None = None
    requested_effort: str | None = None
    requested_error: str | None = None
    broker: bool | None = None


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
class PluginEntry:
    """One plugin as a list of them shows it, and as a switch is written for it.

    Attributes:
        name: What the plugin calls itself.
        origin: The distribution that carries it, which is the name a switch is written with; the same as ``name``
            for a plugin compiled into the program.
        builtin: Whether it is compiled into the program.
        enabled: Whether the next start does its work. A switch is a promise about that start, not about this process.
        failure: Why it could not load here, or ``""`` when it did.
        setting: The configuration key that decides a compiled-in plugin (``"skills.enabled"``), or ``""`` for an
            installed one, which `[plugins] disable` holds.
        switchable: Whether there is a switch to draw here; a list shows the rest without one and says ``why``.
        why: Why it cannot be switched, when it cannot; ``""`` otherwise.
    """

    name: str
    origin: str
    builtin: bool = False
    enabled: bool = True
    failure: str = ""
    setting: str = ""
    switchable: bool = True
    why: str = ""


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
        direct: ``True`` when the sender is a person's one-to-one chat: run ``text`` with :meth:`Session.prompt`, as
            the session's own reader's words, and give the final answer back with :meth:`Client.send_back`.
        mode: ``"steer"`` (the default) asks this session to hand the message to the request that is running, and
            ``"followup"`` asks it to wait until that request ends. An idle session starts a turn either way. A
            front end that cannot steer a running request — a polled inbox — holds it as a follow-up and answers
            ``queued``.
    """

    sender_id: str
    sender: str
    text: str
    via: str = "agent"
    hops: int = 1
    direct: bool = False
    mode: str = MODE_STEER


@dataclass(frozen=True, slots=True)
class Receipt:
    """What a program says about a message another session sent it: the answer to the sender.

    Attributes:
        accepted: Whether it took the message. A refusal carries its reason to the sender.
        reason: Why not, in words the sender's model can act on.
        disposition: What will happen to it: ``"started"`` (a turn began), ``"steered"`` (the request that was
            running took it into account), ``"queued"`` (it waits for the current request to end), or
            ``"delivered"`` (a chat window kept it without starting a turn).
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
        direct: Whether the broker handed it over as the session's own prompt (see ``Client.send``'s ``direct``).
    """

    to: str
    disposition: str
    direct: bool = False


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
