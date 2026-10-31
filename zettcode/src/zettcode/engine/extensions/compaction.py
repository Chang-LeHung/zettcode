"""Compaction a reader can ask for, not only a threshold that fires.

``CompactionExtension`` compacts a request that grew past ``max_tokens``; a
manual pass runs whenever a caller asks, whatever the size. zett-agent routes
that caller through ``on_compact`` (``Agent.compact`` / ``AgentClient.compact``),
which is the seam this subclass fills.

The other half of this module is how the threshold is *measured*. zett-agent counts the
context with tiktoken's ``o200k_base`` encoding, and loads that encoding the first time it
counts — on whatever thread asked, which is the event loop, at the start of the first turn.
Loading it reads a two-megabyte vocabulary and builds the encoder: a tenth of a second when
everything is cached and warm, over half a second on a first run after an install, and a
download when the cache is gone, and for that long nothing is painted and no key is read.
:class:`CompactionCounter` loads it on a thread of its own, ahead of the first turn, and
gives the extension a counter that never loads anything itself.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.compaction import CompactionExtension
from zett_agent.messages import ImageContent
from zett_agent.model import ModelRequest
from zett_agent.tools.base import tool

from zettcode.engine.pipeline import DaemonCall

from ..dialogue.side import is_side_run
from . import context as context_module
from .context import CHARS_PER_TOKEN, message_text

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.messages import AnyMessage

#: The encoding zett-agent's own counter asks tiktoken for. It is named here because warming a
#: different one (the ``/context`` report uses ``cl100k_base``) leaves this one to be loaded on
#: the loop; a test pins that the two agree.
COMPACTION_ENCODING = "o200k_base"

#: Seconds the first turn waits, asynchronously, for the encoding to finish loading before it
#: goes on with an estimate. The wait costs nothing — the interface keeps painting and reading
#: keys — and it is bounded because a first run with no network would otherwise wait for a
#: download that is not coming.
COUNTER_WAIT = 2.0

#: What zett-agent charges for one image, so an estimate agrees with it about pictures.
_IMAGE_TOKENS = 1_100

#: At this many messages a count is kept per message. A context with no usage
#: baseline is counted whole at every step, and a compaction's ``older`` count
#: then re-reads that same history; keeping the counts makes the later read a
#: cache hit. A shorter context stays one zett-agent call, which is both faster
#: and what its tests and a provider-specific counter expect.
COUNT_CACHE_FROM = 64

#: Most message counts kept. A session can be longer than this; the oldest
#: counts are evicted one at a time, so a long context keeps a stable working
#: set instead of clearing the cache in the middle of a pass. The cap counts
#: messages, not bytes, which is the price of not tokenizing the history twice.
MAX_COUNTED_MESSAGES = 20_000


class CompactionCounter:
    """Count a context for compaction without ever loading a vocabulary on the caller's thread.

    Exact counting is zett-agent's own function, so once the encoding is loaded the threshold is
    decided exactly as it was before. Until then — the first moments of a process — a count is
    an estimate from the text's length, which is close enough to tell a context that is nowhere
    near the threshold from one that has crossed it, and is what makes it safe to call from the
    event loop.

    Args:
        encoding: The tiktoken encoding zett-agent counts with.
        loader: Loads and returns the raw encoder, injectable for tests; the default is the one
            the ``/context`` report uses, which points tiktoken's cache at this program's own
            directory so a purge of the system's temp folder is not a download.
    """

    def __init__(
        self,
        encoding: str = COMPACTION_ENCODING,
        *,
        loader: Callable[[str], Callable[[str], Sequence[int]]] | None = None,
    ) -> None:
        """Hold the encoding to load; nothing runs until :meth:`start`."""
        self.encoding = encoding
        # Looked up now, through the module, so that anything that replaces the default loader — a test
        # that must not reach the network — replaces it here as it does for the report's counter.
        load = loader or context_module._tiktoken_encoder
        self._call: DaemonCall[Callable[[str], Sequence[int]]] = DaemonCall(lambda: load(encoding))
        self._ready = False
        #: Exact counts by message identity, for a long context counted more than
        #: once by one compaction pass. The message is kept beside its count so a
        #: reused id cannot answer for a different message; the least recently
        #: used entry is evicted once the cap is reached.
        self._counts: OrderedDict[int, tuple[AnyMessage, int]] = OrderedDict()
        self._counts_lock = threading.RLock()

    def start(self) -> None:
        """Begin loading on a daemon thread and return at once. Needs a running event loop."""
        self._call.start()

    @property
    def ready(self) -> bool:
        """Return whether the encoding is loaded, adopting an answer that arrived since the last look."""
        if not self._ready and self._call.started and self._call.peek() is not None:
            self._ready = True
        return self._ready

    async def wait(self, timeout: float = COUNTER_WAIT) -> bool:
        """Wait up to ``timeout`` seconds for the encoding, without holding up the event loop.

        Returns:
            Whether it is loaded now. ``False`` is not an error: the counter estimates until it is.
        """
        if self._call.started:
            await self._call.wait(timeout)
        return self.ready

    def count(self, messages: Sequence[AnyMessage]) -> int:
        """Return the tokens in ``messages``: zett-agent's exact count once loaded, an estimate before.

        A long context is counted message by message and the exact figures are
        kept. The whole-history count repeats when there is no usage baseline:
        the first step after a restore, every step of a provider that reports
        no usage, and the first step after a compaction, which drops the
        baseline. A compaction's ``older`` count then re-reads that history.
        ``_select_compaction_window``'s slices repeat too. An on-demand
        ``/compact`` counts its ``older`` list once, so its own benefit is a
        later pass, and then only for what the summary did not replace. Short
        contexts still go through zett-agent's own batch call, which is what a
        provider-specific counter and the tests expect.
        """
        if not self.ready:
            return sum(self._estimate(message) for message in messages)
        if len(messages) < COUNT_CACHE_FROM:
            return CompactionExtension._count_tokens(messages)
        total = 0
        missing: list[AnyMessage] = []
        with self._counts_lock:
            for message in messages:
                key = id(message)
                cached = self._counts.get(key)
                if cached is not None and cached[0] is message:
                    total += cached[1]
                    self._counts.move_to_end(key)
                else:
                    missing.append(message)
        counted: list[tuple[AnyMessage, int]] = []
        for message in missing:
            tokens = CompactionExtension._count_tokens([message])
            total += tokens
            counted.append((message, tokens))
        with self._counts_lock:
            for message, tokens in counted:
                key = id(message)
                self._counts[key] = (message, tokens)
                self._counts.move_to_end(key)
                if len(self._counts) > MAX_COUNTED_MESSAGES:
                    self._counts.popitem(last=False)
        return total

    @staticmethod
    def _estimate(message: AnyMessage) -> int:
        """Estimate one message from the length of its text, and a fixed charge per picture."""
        content: Any = getattr(message, "content", None)
        pictures = sum(isinstance(part, ImageContent) for part in content) if isinstance(content, Sequence) else 0
        text = message_text(message)
        return max(1, round(len(text) / CHARS_PER_TOKEN)) + pictures * _IMAGE_TOKENS


class OnDemandCompaction(CompactionExtension):
    """A compaction whose manual pass keeps the last turn instead of a quarter window.

    Automatic compaction is untouched: ``before_model`` calls ``compact`` with
    the configured ``keep_recent_tokens``, so the working tail it leaves behind
    still follows the model's window. ``on_compact`` is only reached by
    ``Agent.compact`` — the call ``/compact`` makes — and a reader who asks wants
    the context small, not merely smaller, so that pass keeps one turn verbatim
    and summarizes everything before it.
    """

    def __init__(self, *args: Any, self_compact: Callable[[str], bool] | None = None, **kwargs: Any) -> None:
        """Use the released compaction policy, optionally offering a tool for enabled sessions."""
        super().__init__(*args, **kwargs)
        self.self_compact = self_compact or (lambda session_id: False)
        self._requested: WeakSet[AgentRunContext] = WeakSet()

    async def on_tool(self, context: AgentRunContext) -> None:
        """Offer the tool only to a session that opted in, never to a side question."""
        if is_side_run(context) or not self.self_compact(context.session_id or ""):
            return

        @tool(name="compact_context")
        async def compact_context() -> str:
            """Self-compaction: compact your own context by replacing your earlier conversation with a summary you keep
            working from. The user enabled it so that you, not only the size limit, decide when the context is worth
            shrinking. It runs before your next model call and always keeps the current user turn, with its tool calls
            and results, exactly as it is; nothing happens if there are no older turns or the summary would not be
            smaller.

            Guidelines:
                - Call it when earlier work is settled and its detail no longer needs to stay in context, for
                  example after a finished subtask, or before a long unrelated one.
                - Do not call it repeatedly: one request is enough, and the current turn cannot be compacted.
                - Do not call it to finish a turn. Continue the task after requesting it; this is not an answer.
            """
            if not self.self_compact(context.session_id or ""):
                return "Self-compaction is disabled for this session."
            self._requested.add(context)
            return "Compaction requested for the next model call; the current turn will be kept intact."

        context.register_tool(compact_context)

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Leave a side question's context alone.

        Compacting there would summarize a branch the question is not part of,
        and store a checkpoint whose boundary ignores that the exchange is a side
        one. Automatic compaction waits for the next ordinary turn instead.
        """
        requested = context in self._requested
        self._requested.discard(context)
        if is_side_run(context):
            return
        if requested and self.self_compact(context.session_id or ""):
            # Wait until every tool result has joined the turn. Mutating context inside a tool
            # would race parallel siblings and could separate a call from its result.
            await self.on_compact(context)
        else:
            await super().before_model(context, request)

    async def on_compact(self, context: AgentRunContext) -> None:
        """Compact now, keeping only the turn the reader is still in."""
        configured = self.keep_recent_tokens
        self.keep_recent_tokens = 1
        try:
            await super().on_compact(context)
        finally:
            self.keep_recent_tokens = configured
