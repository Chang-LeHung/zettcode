"""Compaction a reader can ask for, not only a threshold that fires.

``CompactionExtension`` compacts a request that grew past ``max_tokens``; a
manual pass runs whenever a caller asks, whatever the size. zett-agent routes
that caller through ``on_compact`` (``Agent.compact`` / ``AgentClient.compact``),
which is the seam this subclass fills.
"""

from __future__ import annotations

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.compaction import CompactionExtension


class OnDemandCompaction(CompactionExtension):
    """A compaction whose manual pass keeps the last turn instead of a quarter window.

    Automatic compaction is untouched: ``before_model`` calls ``compact`` with
    the configured ``keep_recent_tokens``, so the working tail it leaves behind
    still follows the model's window. ``on_compact`` is only reached by
    ``Agent.compact`` — the call ``/compact`` makes — and a reader who asks wants
    the context small, not merely smaller, so that pass keeps one turn verbatim
    and summarizes everything before it.
    """

    async def on_compact(self, context: AgentRunContext) -> None:
        """Compact now, keeping only the turn the reader is still in."""
        configured = self.keep_recent_tokens
        self.keep_recent_tokens = 1
        try:
            await super().on_compact(context)
        finally:
            self.keep_recent_tokens = configured
