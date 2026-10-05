"""Compaction that can be asked for, not only triggered by size.

``CompactionExtension.compact`` is the unit of work as of zett-agent 0.1.7 —
``before_model`` only forwards to it — so this subclass overrides that method
and leaves the runtime's own call path untouched.
"""

from __future__ import annotations

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.compaction import CompactionExtension
from zett_agent.extensions.events import CompactionEvent


class OnDemandCompaction(CompactionExtension):
    """A compaction extension whose threshold can be forced once.

    ``zett-agent`` compacts a request that has grown past ``max_tokens``, which
    is the right policy for a conversation nobody is watching. ``/compact``
    wants that same work on demand, whatever the size, without waiting for the
    context to fill up.

    The pass itself is the parent's, untouched: its cutoff, its summary
    request, its events, and its replacement of the message list all run as
    they would have. This subclass only changes the two budgets the parent
    compares against — nothing can pass the threshold, and the tail it keeps is
    a single turn — so the decision "is this worth compacting" still belongs to
    the extension that owns it.

    Keeping one turn rather than the automatic share of the window is the point
    of asking: the size thresholds exist to leave a working tail behind, while a
    reader who asks for compaction wants the context small, not merely smaller.
    """

    #: Set by :meth:`request`, read by the next :meth:`before_model`. The class
    #: attribute keeps the flag defined without repeating the parent's
    #: keyword-only signature just to initialise it.
    requested: bool = False

    def request(self) -> None:
        """Ask the next request to compact, however small it is."""
        self.requested = True

    async def compact(self, context: AgentRunContext) -> CompactionEvent | None:
        """Compact when the context is over the threshold, or when asked to.

        Returns:
            The checkpoint the parent published, or ``None`` when there was
            nothing worth replacing.
        """
        if not self.requested:
            return await super().compact(context)
        self.requested = False
        budgets = (self.max_tokens, self.keep_recent_tokens)
        self.max_tokens, self.keep_recent_tokens = -1, 1
        try:
            return await super().compact(context)
        finally:
            self.max_tokens, self.keep_recent_tokens = budgets
