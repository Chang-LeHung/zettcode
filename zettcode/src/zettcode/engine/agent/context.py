"""What the next request carries: its size, its breakdown, and shrinking it.

Counting a request and summarizing one are the same subject seen from two ends — one says
how full the window is, the other makes room in it — and both are answered from what the
runtime assembled or, before it has assembled one, from what the store holds.
"""

from __future__ import annotations

from zett_agent.agent import AgentRunConfig
from zett_agent.extensions.events import CompactionEvent
from zett_agent.messages import AnyMessage, SystemMessage
from zett_agent.model import ToolDefinition

from zettcode.engine.core import build_system_prompt
from zettcode.engine.extensions.context import ContextReport
from zettcode.engine.extensions.usage import UsageSnapshot
from zettcode.engine.storage import Session

from .base import AgentBase


class ContextMixin(AgentBase):
    """Report the request the next turn would send, and compact the conversation behind it."""

    @property
    def usage(self) -> UsageSnapshot:
        """Return the active session's cumulative token counters.

        The numbers come from the usage extension's in-memory totals, so the
        status line can read them every frame; a session replayed from the store
        is seeded before this is asked.
        """
        return self.runtime.usage.snapshot(self.session_id)

    async def context_report(self) -> ContextReport | None:
        """Return what the next request carries by source, or None before the first call.

        The shares come from the tokenizer, which is prepared first: it prefers
        tiktoken and falls back to a character estimate when that vocabulary
        cannot be opened, which the report names so the numbers are not mistaken
        for exact ones. The total comes from the provider when it counted this
        very request — it counts what it bills — and from the tokenizer when the
        request was primed from the store, whose stored figure belongs to a call
        the dialogue may have outgrown.
        """
        tokenizer = self.runtime.tokenizer
        await tokenizer.prepare()
        model = self.runtime.active_model
        # No model configured means no window to measure against. Nothing is reported either way: a request is
        # refused before one is assembled, so the report is None and no share is ever computed from this 0.
        window = 0 if model is None else model.context_window
        counted = self.runtime.usage.snapshot(self.session_id).context_tokens
        # The provider's own count of this conversation is the total: what it
        # billed for the request this process assembled, or — for a session
        # rebuilt from the store, which has no call of its own yet — what it
        # billed for the last call that session made. Locally counting a rebuilt
        # request is not a substitute: on this machine's own session the rebuilt
        # list measured 1.65 M tokens against a provider's 326 k, because a
        # rebuilt list holds messages the live request no longer carries.
        #
        # A count that reaches the window is refused instead: a request cannot
        # carry more than the window it is measured against, so a figure that does
        # is about something else, and a share pinned at a hundred is worse than
        # the measurement.
        reported = counted if 0 < counted < window else None
        return self.runtime.context.report(
            self.session_id,
            window=window,
            tokenizer=tokenizer,
            reported=reported,
        )

    async def compact(self) -> CompactionEvent | None:
        """Summarize the conversation now, without adding a turn to it.

        zett-agent runs one pass over the restored session and dispatches every
        event it emits, so the transcript animates the same ``Compacting`` row an
        automatic compaction shows. Nothing is appended to the conversation and
        no primary model call is made: the only work is the summary itself.

        Returns:
            The checkpoint that was stored, or ``None`` when there was nothing
            worth replacing.

        Raises:
            SessionLocked: Another process has this session open, and a checkpoint is a write.
            ValueError: When the newest checkpoint already covers the branch —
                a second pass would summarize nothing but the checkpoint.
        """
        self.require_session()
        if self._compacted_at_the_head():
            raise ValueError("Already compacted; send a message before compacting again")
        await self.runtime.start()
        return await self.runtime.started.compact(
            config=AgentRunConfig(session_id=self.session_id),
            model=self.runtime.provider,
        )

    def _compacted_at_the_head(self) -> bool:
        """Return whether nothing has been appended since the newest checkpoint.

        Messages and checkpoints both carry ``created_at``, so the last message
        being older than the last checkpoint is what says the branch has not
        moved since it was summarized — no matter which session is active or
        whether the transcript in this process ever showed that compaction.
        """
        try:
            session = self.runtime.persistence.read(self.session_id)
        except ValueError:
            # A runtime without a store to read: no checkpoint can cover it.
            return False
        latest = session.latest_compaction
        if latest is None or session.head_id is None:
            return False
        head = session.message(session.head_id)
        return head is not None and head.created_at <= latest.created_at

    def _context_request(self, session: Session) -> tuple[tuple[AnyMessage, ...], tuple[ToolDefinition, ...]]:
        """Return the messages and tools the next turn would send.

        The request this process assembled is the honest answer; before one has
        run — a session restored into a fresh process — the instructions and the
        active branch stand in for it, which is all that can be known there.
        """
        assembled = self.runtime.context.assembled(self.session_id)
        if assembled is not None:
            messages, tools = assembled
            return tuple(messages), tuple(tools)
        return self._stored_request(session), self.runtime.context.tools

    def _stored_request(self, session: Session) -> tuple[AnyMessage, ...]:
        """Return the messages a request for ``session`` would carry, from what is stored.

        This depends on the session it is given and on nothing that changes with the
        active one, so it can be run later — a restore hands it over unrun, and the
        reader may have moved to another session by the time it is wanted.
        """
        instructions = self.runtime.context.instructions or (
            SystemMessage(content=build_system_prompt(self.runtime.config)),
        )
        checkpoint, tail = session.active()
        stored: list[AnyMessage] = [checkpoint.message[0]] if checkpoint is not None else []
        stored.extend(line.message[0] for line in tail if line.message[0].include_in_messages)
        return (*instructions, *stored)
