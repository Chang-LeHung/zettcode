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

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage
from zett_agent.model import ModelRequest, ToolDefinition

#: Tokens per character when no tokenizer is available. The rule of thumb is
#: close for English prose and low for CJK, which is why the report names the
#: estimate it used instead of presenting it as exact.
CHARS_PER_TOKEN = 4

#: Seconds to wait for tiktoken's vocabulary before falling back.
ENCODING_DEADLINE = 2.0

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

    Attributes:
        window: Tokens the budget is measured against.
        measured_by: Which counter produced the numbers.
        shares: One entry per non-empty source, in :data:`SOURCES` order.
        partial: Whether a part the runtime would send is missing from the
            measurement, which is the case for a restored session measured
            before any reply in this process: its tool schemas are not knowable
            yet, and the page says so instead of reading low silently.
    """

    window: int
    measured_by: str
    shares: tuple[ContextShare, ...]
    partial: bool = False

    @property
    def used(self) -> int:
        """Return the tokens every source adds up to."""
        return sum(share.tokens for share in self.shares)

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
        "where does the context go", which is the question a breakdown is for.
        """
        return tokens / self.used * 100 if self.used else 0.0


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

        The load runs off the event loop because opening an encoding can talk to
        the network; a failure or a timeout leaves the character estimate in
        place rather than delaying the page.
        """
        if self._resolved:
            return
        self._resolved = True
        try:
            self._encode = await asyncio.wait_for(asyncio.to_thread(self._loader, self.encoding), self.deadline)
        except Exception:
            self._encode = None


def _tiktoken_encoder(encoding: str) -> Callable[[str], Sequence[int]]:
    """Return tiktoken's encoder, importing it lazily so startup stays cheap."""
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


def measure(
    messages: Sequence[AnyMessage],
    tools: Sequence[ToolDefinition],
    *,
    window: int,
    tokenizer: Tokenizer,
) -> ContextReport:
    """Break one assembled request into the sources that fill the budget.

    Args:
        messages: Context in provider order; the first system message is this
            application's prompt and later ones are the environment and tool
            notes an extension added.
        tools: Tool schemas offered with the request.
        window: Token budget the shares are measured against.
        tokenizer: Counter to use; it may still be estimating.
    """
    totals = dict.fromkeys(SOURCES, 0)
    counts = dict.fromkeys(SOURCES, 0)
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
        totals[source] += tokenizer.count(message_text(message))
        counts[source] += 1
    if tools:
        totals["Tool schemas"] = sum(tokenizer.count(tool_text(tool)) for tool in tools)
        counts["Tool schemas"] = len(tools)
    shares = tuple(ContextShare(name, totals[name], counts[name]) for name in SOURCES if totals[name] or counts[name])
    return ContextReport(window=max(1, window), measured_by=tokenizer.label, shares=shares, partial=not tools)


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
        """Start with no captured request."""
        self._requests: dict[str, tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]]] = {}
        self._template: tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]] | None = None

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Keep the request that is about to leave, replacing the previous one."""
        # The runtime replaces an empty session_id before hooks run.
        session_id = cast(str, context.config.session_id)
        self._requests[session_id] = (tuple(request.messages), tuple(request.tools))
        self._template = (tuple(request.messages), tuple(request.tools))

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

    def assembled(self, session_id: str) -> tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]] | None:
        """Return the last assembled request, or None before the first call."""
        return self._requests.get(session_id)

    def report(self, session_id: str, *, window: int, tokenizer: Tokenizer) -> ContextReport | None:
        """Return the breakdown of the last assembled request, if there was one."""
        assembled = self.assembled(session_id)
        if assembled is None:
            return None
        messages, tools = assembled
        return measure(messages, tools, window=window, tokenizer=tokenizer)
