"""The transcript view: a virtualized window over the conversation model.

The model itself lives in ``app.agent.transcript``, because that is what the
agent projector writes into; this module only turns it into lines and mouse
handling, so the dependency arrow points one way (ui reads agent).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable

from ...tui import Canvas, Host, LineSource, MouseAction, MouseEvent, ScrollView, TextLine, Theme
from ..agent.transcript import Entry, Transcript


class TranscriptSource(LineSource):
    """LineSource over the transcript, rendering each entry at most once."""

    def __init__(self, transcript: Transcript, *, theme: Theme, frame: Callable[[], int] = lambda: 0) -> None:
        """Serve ``transcript`` as lines, caching blocks per width and version.

        Args:
            transcript: Model to read; its ``version`` invalidates this cache.
            theme: Palette handed to each entry's renderer.
            frame: Pulled lazily so the animation frame is only read for the
                rows that are actually rendered.
        """
        self.transcript = transcript
        self.theme = theme
        self.frame = frame
        self._width = 0
        self._version = -1
        self._starts: list[int] = []
        self._blocks: list[object] = []
        self._count = 0

    def count(self, width: int) -> int:
        """Return how many terminal lines the transcript occupies at ``width``."""
        self._sync(width)
        return self._count

    def line(self, index: int, width: int) -> TextLine:
        """Return one rendered line, resolving its owning entry block first."""
        self._sync(width)
        if not self._blocks:
            return TextLine()
        # ``_starts`` holds the first line of every block, so the last start at or
        # before ``index`` names the block that owns it.
        position = min(max(0, bisect_right(self._starts, index) - 1), len(self._blocks) - 1)
        return self._blocks[position].line(index - self._starts[position], width)

    def entry_at(self, index: int, width: int) -> Entry | None:
        """Return the entry that owns a rendered line, for hit testing."""
        self._sync(width)
        if not self._blocks:
            return None
        position = min(max(0, bisect_right(self._starts, index) - 1), len(self._blocks) - 1)
        return self.transcript.entries[position]

    def _sync(self, width: int) -> None:
        """Rebuild the block boundaries when the width or the transcript changed."""
        if width == self._width and self.transcript.version == self._version:
            return
        self._width = width
        self._version = self.transcript.version
        frame = self.frame()
        starts: list[int] = []
        blocks: list[object] = []
        total = 0
        for entry in self.transcript.entries:
            starts.append(total)
            block = entry.block_for(width, self.theme, frame)
            blocks.append(block)
            total += block.count(width)
        self._starts = starts
        self._blocks = blocks
        self._count = total


class TranscriptView(ScrollView):
    """Scrollable transcript that toggles entries when they are clicked.

    Shape, one blank row between entries::

        > inspect the project                <- user prompt, bold, U+276F prefix
        v Thinking  0 ms                     <- reasoning row; v collapsed,
          checking the renderer                 U+25BE expanded, animated while
                                                running, stamped when finished
        x read_file {"path":"app.py"}  0 ms v <- tool row: glyph, name, argument
            | line one                          preview, duration, and U+25B8
              line two                          when its bounded output can open
        Fixed parse.                         <- answer: parsed as Markdown

    The last two rows are the same entry: a tool row collapses its output to
    `TOOL_PREVIEW_ROWS` unless it is expanded. A click toggles the entry under
    the pointer; everything else, the wheel included, is ScrollView's.
    """

    def __init__(self, transcript: Transcript, *, theme: Theme) -> None:
        """Scroll the transcript and keep its line source in sync with the theme.

        Args:
            transcript: Model rendered by this view.
            theme: Initial palette; ``render`` refreshes it from the live theme.
        """
        self.transcript = transcript
        self.transcript_source = TranscriptSource(transcript, theme=theme, frame=lambda: transcript.frame)
        super().__init__(self.transcript_source, follow_tail=True, selectable=True)

    def render(self, canvas: Canvas) -> None:
        """Refresh the source theme so a theme switch repaints the entries."""
        self.transcript_source.theme = self.theme
        super().render(canvas)

    def handle(self, event, host: Host) -> bool:
        """Toggle the clicked entry; every other event stays with ScrollView."""
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN and self.rect.contains(event.x, event.y):
            index = self.top + event.y - self.rect.y
            entry = self.transcript_source.entry_at(index, self.line_width)
            if entry is not None and self.transcript.toggle(entry.id):
                host.invalidate()
                return True
        # Everything else, the wheel included, belongs to ScrollView.
        return super().handle(event, host)
