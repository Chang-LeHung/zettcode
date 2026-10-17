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

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.compaction import CompactionExtension
from zett_agent.messages import ImageContent
from zett_agent.model import ModelRequest

from zettcode.app.pipeline import DaemonCall

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
        """Return the tokens in ``messages``: zett-agent's exact count once loaded, an estimate before."""
        if self.ready:
            return CompactionExtension._count_tokens(messages)
        return sum(self._estimate(message) for message in messages)

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

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Leave a side question's context alone.

        Compacting there would summarize a branch the question is not part of,
        and store a checkpoint whose boundary ignores that the exchange is a side
        one. Automatic compaction waits for the next ordinary turn instead.
        """
        if is_side_run(context):
            return
        await super().before_model(context, request)

    async def on_compact(self, context: AgentRunContext) -> None:
        """Compact now, keeping only the turn the reader is still in."""
        configured = self.keep_recent_tokens
        self.keep_recent_tokens = 1
        try:
            await super().on_compact(context)
        finally:
            self.keep_recent_tokens = configured
