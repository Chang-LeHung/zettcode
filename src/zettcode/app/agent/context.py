"""What the next request carries, broken down by who contributed it.

The runtime assembles one request per model call. ``before_model`` sees that
request just before it leaves, so an extension can remember it; ``/context``
then measures the remembered messages and tool schemas and shows how much of
the budget each source takes: the instructions, the tools, the user's turns,
the model's turns, and the tool output.

Token counts come from ``tiktoken`` when its encoding can be opened. That
encoding is fetched over the network the first time, which a CLI cannot rely
on, so the count falls back to a characters-per-token estimate and the report
says which one it used.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage
from zett_agent.model import ModelRequest, ToolDefinition

from ...paths import DEFAULT_TOKENIZER_CACHE
from ..pipeline import DaemonCall

#: Tokens per character when no tokenizer is available. The rule of thumb is
#: close for English prose and low for CJK, which is why the report names the
#: estimate it used instead of presenting it as exact.
CHARS_PER_TOKEN = 4

#: Seconds to wait for tiktoken's vocabulary before falling back.
ENCODING_DEADLINE = 2.0


@dataclass(frozen=True, slots=True)
class Counted:
    """What one message or tool cost the last time it was counted.

    Attributes:
        item: The message or tool the count belongs to. Holding it is what makes
            the key sound: a cache keyed by ``id`` can only name a different
            object once the one it named is gone, and this keeps that one alive.
        tokens: What the counter said it was worth.
    """

    item: object
    tokens: int


#: Counts from an earlier measurement, keyed by ``id`` of the item they describe.
Counts: TypeAlias = MutableMapping[int, Counted]


@dataclass(slots=True)
class SessionCounts:
    """One session's counts, and the counter that produced them.

    Attributes:
        measured_by: The counter's label. Numbers from one counter are never
            reused for another: the estimate and the encoder disagree by design.
        counts: One entry per message or tool the last report measured.
    """

    measured_by: str
    counts: Counts = field(default_factory=dict)


#: One row per source, in the order the request is assembled.
SOURCES = (
    "System prompt",
    "Environment notes",
    "Tool schemas",
    "User messages",
    "Assistant messages",
    "Tool output",
    "Compaction summary",
)


@dataclass(frozen=True, slots=True)
class ContextShare:
    """One source's share of the budget.

    Attributes:
        name: Row label, one of :data:`SOURCES`.
        tokens: Tokens this source contributes.
        items: Messages, tools, or summaries counted into ``tokens``.
    """

    name: str
    tokens: int
    items: int = 0


@dataclass(frozen=True, slots=True)
class ContextReport:
    """The budget as a whole: every source, the total, and what is left.

    A request has two numbers, and they come from different places: how many
    tokens it is, which only the provider knows because it counts what it bills,
    and how that total divides between the sources, which only the tokenizer can
    say because no provider reports a breakdown. The shares are always the
    tokenizer's; the total is the provider's whenever it reported one for this
    very request, and the tokenizer's sum when it did not — a session restored
    from the store, where the stored figure belongs to a call that may predate a
    compaction.

    Attributes:
        window: Tokens the budget is measured against.
        measured_by: Which counter produced the shares.
        shares: One entry per non-empty source, in :data:`SOURCES` order.
        partial: Whether a part the runtime would send is missing from the
            measurement, which is the case for a restored session measured
            before any reply in this process: its tool schemas are not knowable
            yet, and the page says so instead of reading low silently.
        reported: Tokens the provider counted for this request, if it did.
    """

    window: int
    measured_by: str
    shares: tuple[ContextShare, ...]
    partial: bool = False
    reported: int | None = None

    @property
    def measured(self) -> int:
        """Return the tokens the tokenizer counted, which the shares add up to."""
        return sum(share.tokens for share in self.shares)

    @property
    def used(self) -> int:
        """Return the tokens this request carries: the provider's count if there is one."""
        return self.reported if self.reported is not None else self.measured

    @property
    def from_provider(self) -> bool:
        """Return whether the total is the provider's rather than the tokenizer's."""
        return self.reported is not None

    @property
    def free(self) -> int:
        """Return the tokens left before the budget is full, never negative."""
        return max(0, self.window - self.used)

    def percent(self, tokens: int) -> float:
        """Return ``tokens`` as a share of the budget, in percent."""
        return tokens / self.window * 100 if self.window else 0.0

    def share(self, tokens: int) -> float:
        """Return ``tokens`` as a share of what the request is using, in percent.

        :meth:`percent` answers "how full is the model's window"; this answers
        "where does the context go", which is the question a breakdown is for —
        so it divides by what the tokenizer counted, never by a provider's total
        for the same request, which would leave the rows short of a hundred.
        """
        measured = self.measured
        return tokens / measured * 100 if measured else 0.0


class Tokenizer:
    """Count tokens with tiktoken when it can be opened, else by character count."""

    def __init__(
        self,
        encoding: str = "cl100k_base",
        *,
        deadline: float = ENCODING_DEADLINE,
        loader: Callable[[str], Callable[[str], Sequence[int]]] | None = None,
    ) -> None:
        """Configure the encoding, the deadline, and how it is loaded.

        Args:
            encoding: tiktoken encoding name; ``cl100k_base`` covers the models
                this shell talks to and their gateways.
            deadline: Seconds to wait for the encoder before estimating.
            loader: Returns the raw encoder, injectable for tests; the default
                loads tiktoken, which may fetch its vocabulary over the network.
        """
        self.encoding = encoding
        self.deadline = deadline
        self._loader = loader or _tiktoken_encoder
        self._encode: Callable[[str], Sequence[int]] | None = None
        self._resolved = False
        self._call: DaemonCall[Callable[[str], Sequence[int]]] | None = None

    @property
    def label(self) -> str:
        """Return the counter's name, for the report to show its own accuracy."""
        return f"tiktoken {self.encoding}" if self._encode is not None else f"~{CHARS_PER_TOKEN} chars/token"

    @property
    def prepared(self) -> bool:
        """Return whether an encoder was loaded."""
        return self._encode is not None

    def count(self, text: str) -> int:
        """Return the tokens in ``text``, estimating when no encoder loaded."""
        if not text:
            return 0
        if self._encode is not None:
            return len(self._encode(text))
        return max(1, round(len(text) / CHARS_PER_TOKEN))

    async def prepare(self) -> None:
        """Load the encoder at most once, giving up after the deadline.

        The load runs on a daemon thread because opening an encoding may fetch
        its vocabulary — seconds on a first run, and an executor's thread would
        hold the process open for the rest of it if the shell left first. A
        failure or a timeout leaves the character estimate in place rather than
        delaying the page, and the load is left to finish on its own: a later
        report adopts its answer instead of estimating for the whole session.
        """
        if self._resolved:
            if self._encode is None and self._call is not None:
                self._encode = self._call.peek()
            return
        self._resolved = True
        self._call = DaemonCall(lambda: self._loader(self.encoding))
        self._call.start()
        self._encode = await self._call.wait(self.deadline)


def _tiktoken_encoder(encoding: str) -> Callable[[str], Sequence[int]]:
    """Return tiktoken's encoder, importing it lazily so startup stays cheap.

    tiktoken caches the vocabulary it downloads in the OS temp directory, which
    is cleaned whenever the system feels like it: a purge turns the next load
    into a 1.7 MB fetch — five seconds, measured — behind the deadline above, so
    the count would arrive as an estimate after a wait. This program's own cache
    directory survives that, so the fetch happens once. An explicit
    ``TIKTOKEN_CACHE_DIR`` wins, because that is the reader's own choice.
    """
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(DEFAULT_TOKENIZER_CACHE))
    import tiktoken

    return tiktoken.get_encoding(encoding).encode


def message_text(message: AnyMessage) -> str:
    """Return the text of one message as the model sees it, for counting.

    Args:
        message: Any context message. Tool calls are counted through their name
            and arguments, and a tool result through the text it rendered.
    """
    if isinstance(message, ToolMessage):
        return message.text
    if isinstance(message, AssistantMessage):
        parts = [message.reasoning or "", message.content]
        parts.extend(
            f"{call.name} {json.dumps(call.arguments, ensure_ascii=False, default=str)}" for call in message.tool_calls
        )
        return "\n".join(part for part in parts if part)
    return str(getattr(message, "content", ""))


def tool_text(tool: ToolDefinition) -> str:
    """Return the schema text of one tool, as the provider receives it."""
    parameters = json.dumps(tool.parameters, ensure_ascii=False, default=str, sort_keys=True)
    return f"{tool.name}\n{tool.description}\n{parameters}"


def count_one(item: object, text: str, tokenizer: Tokenizer, counts: Counts | None) -> int:
    """Return the tokens in one counted item, reusing an earlier count of it.

    Counting is the whole cost of a report — 25 ms for a session of 155 k tokens
    — and the overwhelming majority of what a report walks was counted the last
    time the panel was opened: a turn appends, it does not rewrite. The cache
    turns that into a lookup, and only what arrived since is encoded.

    Args:
        item: The message or tool the text belongs to. Its identity is the key,
            and the entry holds it, so a key can never name a different object.
        text: What the tokenizer would count.
        tokenizer: Counter to use when there is no entry.
        counts: Earlier counts, updated in place; ``None`` counts everything.
    """
    if counts is None:
        return tokenizer.count(text)
    key = id(item)
    entry = counts.get(key)
    if entry is not None and entry.item is item:
        return entry.tokens
    tokens = tokenizer.count(text)
    counts[key] = Counted(item, tokens)
    return tokens


def measure(
    messages: Sequence[AnyMessage],
    tools: Sequence[ToolDefinition],
    *,
    window: int,
    tokenizer: Tokenizer,
    counts: Counts | None = None,
    reported: int | None = None,
) -> ContextReport:
    """Break one assembled request into the sources that fill the budget.

    Args:
        messages: Context in provider order; the first system message is this
            application's prompt and later ones are the environment and tool
            notes an extension added.
        tools: Tool schemas offered with the request.
        window: Token budget the shares are measured against.
        tokenizer: Counter to use; it may still be estimating.
        counts: Counts from an earlier measurement of the same items, updated in
            place as new ones are counted; ``None`` measures everything.
        reported: Tokens the provider counted for this request, if it did; the
            shares are still measured here, because it cannot break them down.
    """
    totals = dict.fromkeys(SOURCES, 0)
    items = dict.fromkeys(SOURCES, 0)
    system_seen = False
    for message in messages:
        match message:
            case SystemMessage():
                source = "Environment notes" if system_seen else "System prompt"
                system_seen = True
            case CompactedMessage():
                source = "Compaction summary"
            case AssistantMessage():
                source = "Assistant messages"
            case ToolMessage():
                source = "Tool output"
            case _:
                source = "User messages"
        totals[source] += count_one(message, message_text(message), tokenizer, counts)
        items[source] += 1
    if tools:
        totals["Tool schemas"] = sum(count_one(tool, tool_text(tool), tokenizer, counts) for tool in tools)
        items["Tool schemas"] = len(tools)
    shares = tuple(ContextShare(name, totals[name], items[name]) for name in SOURCES if totals[name] or items[name])
    return ContextReport(
        window=max(1, window),
        measured_by=tokenizer.label,
        shares=shares,
        partial=not tools,
        reported=reported,
    )


class ContextExtension(AgentExtension):
    """Remember the request the runtime assembled for the last model call.

    Nothing is measured here: tokenizing every request would cost a little on
    every turn, and the report is only wanted when ``/context`` asks for it. The
    extension keeps the assembled messages and tools per session instead.

    A session restored from the store has not been assembled in this process, so
    the shell primes it with the stored dialogue; the instructions and tool
    schemas come from the last request of any session, because one configuration
    sends the same ones every time.
    """

    def __init__(self) -> None:
        """Start with no captured request and nothing counted."""
        self._requests: dict[str, tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]]] = {}
        self._template: tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]] | None = None
        #: Sessions whose request was primed from the store rather than assembled
        #: for a call. The difference matters for the total: a provider reported a
        #: number for one of them and for the other only the store remembers a
        #: call, which may be older than the dialogue it is being compared with.
        self._primed: set[str] = set()
        #: Per session, what the last report counted and which counter did it.
        self._counts: dict[str, SessionCounts] = {}

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Keep the request that is about to leave, replacing the previous one."""
        # The runtime replaces an empty session_id before hooks run.
        session_id = cast(str, context.config.session_id)
        self._requests[session_id] = (tuple(request.messages), tuple(request.tools))
        self._template = (tuple(request.messages), tuple(request.tools))
        self._primed.discard(session_id)

    @property
    def instructions(self) -> tuple[AnyMessage, ...]:
        """Return the instruction messages every request starts with, once seen."""
        return self._template[0] if self._template is not None else ()

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        """Return the tool schemas every request offers, once one was seen."""
        return self._template[1] if self._template is not None else ()

    def remember(self, session_id: str, messages: Sequence[AnyMessage]) -> None:
        """Record a context assembled outside a model call, as restoring does.

        Args:
            session_id: Session the messages belong to.
            messages: Instructions followed by the restored dialogue, in the
                order a request would carry them.
        """
        self._requests[session_id] = (tuple(messages), self.tools)
        self._primed.add(session_id)

    def primed(self, session_id: str) -> bool:
        """Return whether this session's request was rebuilt from the store.

        A primed request has no provider figure of its own: the stored usage
        belongs to the call that was made before the shell was restarted, which
        for a session that was compacted since is a different, larger request.
        """
        return session_id in self._primed

    def assembled(self, session_id: str) -> tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]] | None:
        """Return the last assembled request, or None before the first call."""
        return self._requests.get(session_id)

    def report(
        self,
        session_id: str,
        *,
        window: int,
        tokenizer: Tokenizer,
        reported: int | None = None,
    ) -> ContextReport | None:
        """Return the breakdown of the last assembled request, if there was one.

        What was counted for an earlier report is counted again only if the
        counter changed: a turn appends to the context rather than rewriting it,
        so a report spends its time on what arrived since the last one.

        Args:
            session_id: Session to report on.
            window: Tokens the model can carry.
            tokenizer: Counter that measures the shares.
            reported: Tokens the provider counted for this request, if it counted
                it; it becomes the report's total while the shares stay measured.
        """
        assembled = self.assembled(session_id)
        if assembled is None:
            return None
        messages, tools = assembled
        label = tokenizer.label
        cached = self._counts.get(session_id)
        if cached is None or cached.measured_by != label:
            cached = SessionCounts(measured_by=label)
        counts = cached.counts
        live = {id(message) for message in messages} | {id(tool) for tool in tools}
        for key in [key for key in counts if key not in live]:
            # The request stopped carrying this item, so its count has no reader
            # and its key must not outlive the object it stands for.
            del counts[key]
        self._counts[session_id] = cached
        return measure(messages, tools, window=window, tokenizer=tokenizer, counts=counts, reported=reported)
