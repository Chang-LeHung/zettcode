"""The conversation model: an ordered list of entries, and what the agent does to it.

The projector writes into this model and the UI reads it, so it lives on the agent
side of the application and never imports the shell. The entries are plain data
(``entries.py``); how one is drawn is its presenter's business (``presenters.py``);
the scrollable view over the list is ``app.ui.widgets.transcript``.

What is left is the list and the verbs on it, which this package splits by what each
is responsible for, the way the shell splits its own: a shared state class, and a
mixin for each kind of thing done to it.

==============  ==========================================================
``log``         :class:`EntryLog` — the list: where an entry goes, how many
                are kept, what changed since the view last looked
``turn``        :class:`TurnMixin` — a request's life: the reader's message,
                the pinned wait row, the clock, closing what was left open
``stream``      :class:`StreamMixin` — what the model produces as it arrives:
                reasoning, a compaction, the answer, tool calls
``oneoff``      :class:`OneOffMixin` — rows written once and left alone:
                a banner, a notice, an error, an announcement, Markdown
``fold``        :class:`FoldMixin` — opening and closing reasoning and tools
==============  ==========================================================

A mixin inherits :class:`EntryLog` only to be type-checked against the surface it
shares with the rest. :class:`Transcript` is the composition, and the one place
that holds what no single part owns: the clock, the renderers that phrase tool rows,
and the presenters the view draws with.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from zettcode.config import DEFAULT_TRANSCRIPT_MAX_ENTRIES

from ..presenters import DEFAULT_PRESENTERS, Presenters
from ..rendering import DEFAULT_RENDERERS, Renderers
from ..tips import TipDeck
from .fold import FoldMixin
from .log import EntryLog
from .oneoff import OneOffMixin
from .stream import StreamMixin

__all__ = ["EntryLog", "Transcript"]


class Transcript(OneOffMixin, FoldMixin, StreamMixin, EntryLog):
    """The conversation: entries in order, and the verbs the agent's events map onto."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        renderers: Renderers = DEFAULT_RENDERERS,
        presenters: Presenters = DEFAULT_PRESENTERS,
        max_entries: int = DEFAULT_TRANSCRIPT_MAX_ENTRIES,
    ) -> None:
        """Start an empty transcript whose elapsed times come from ``clock``.

        Args:
            clock: Time source for row durations, injectable for tests.
            renderers: Chain that phrases tool rows; tests can pass their own to
                pin the wording a row would show.
            presenters: How each kind of entry is drawn; the view reads this so a
                transcript given other presenters is drawn with them.
            max_entries: Conversation entries kept for display; older ones are
                dropped, while the session file keeps the whole tree. Must be
                positive.
        """
        super().__init__(max_entries=max_entries)
        self.clock = clock
        self.renderers = renderers
        self.presenters = presenters
        self.frame = 0
        #: Where the tips under the waiting row come from; ``None`` shows none.
        self.tip_deck: TipDeck | None = None
        self._picture_drawn = None
