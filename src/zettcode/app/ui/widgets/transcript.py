"""The transcript view: a virtualized window over the conversation model.

The model itself lives in ``app.agent.transcript``, because that is what the
agent projector writes into; this module only turns it into lines and mouse
handling, so the dependency arrow points one way (ui reads agent).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable

from ....tui import Canvas, Host, LineSource, MouseAction, MouseEvent, Rect, ScrollView, Span, Style, TextLine, Theme
from ....tui.render import display_width
from ...agent.transcript import Entry, Transcript

#: Badge shown once the reader scrolls away from the newest line. It names the
#: shortcut so the mouse and the keyboard offer the same way back.
BADGE_ARROW = "\u2193"
BADGE_LABEL = " back to bottom \u00b7 Esc"
BACK_TO_BOTTOM = BADGE_ARROW + BADGE_LABEL


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
        self._theme: Theme | None = None
        self._processors = None
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
        if (
            width == self._width
            and self.transcript.version == self._version
            and self._theme == self.theme
            and self._processors is self.transcript.processors
        ):
            return
        self._width = width
        self._version = self.transcript.version
        self._theme = self.theme
        self._processors = self.transcript.processors
        frame = self.frame()
        starts: list[int] = []
        blocks: list[object] = []
        total = 0
        for entry in self.transcript.entries:
            starts.append(total)
            block = entry.block_for(width, self.theme, frame, processors=self.transcript.processors)
            blocks.append(block)
            total += block.count(width)
        self._starts = starts
        self._blocks = blocks
        self._count = total


class TranscriptView(ScrollView):
    """Scrollable transcript that toggles entries when they are clicked.

    Shape, one blank row between entries::

        > inspect the project                   <- user prompt: U+276F flush left,
                                                   text under the composer caret
          v Thinking  1.2 s                     <- reasoning row; v collapsed,
            checking the renderer                  U+25BE expanded, animated
                                                   while running, stamped at end
          x Read app.py  1.2 s v                <- tool row: glyph, what the call
              | import os                         did, duration, and U+25B8 when
                ...                               its bounded output can open
          Fixed parse.                          <- answer: parsed as Markdown

    Every row starts at the composer's caret column — the width of its ``\u203a ``
    prompt — so text never sits left of where the user types. A user prompt is
    the one exception: its own ``\u203a `` draws at column zero, flush with the
    edge like the composer's, and its text lands on that same shared margin.

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
        """Refresh the source theme, then float the return badge over the rows."""
        self.transcript_source.theme = self.theme
        super().render(canvas)
        self._render_badge(canvas)

    @property
    def scrolled_up(self) -> bool:
        """Return whether the newest lines are out of view."""
        return not self.follow_tail

    def badge_rect(self) -> Rect | None:
        """Return the cell rectangle of the return badge, or None while at the tail.

        The badge is anchored to the bottom-right corner with the same two-cell
        margin the header, the status bar, and the composer keep, so it lines up
        with the rest of the chrome instead of touching the frame.
        """
        if not self.scrolled_up or self.rect.empty:
            return None
        width = display_width(BACK_TO_BOTTOM) + 2
        if width > self.rect.width:
            return None
        x = max(self.rect.x, self.rect.x + self.rect.width - width - 2)
        return Rect(x, self.rect.bottom - 1, width, 1)

    def _render_badge(self, canvas: Canvas) -> None:
        """Paint the return badge in the composer's raised-surface colours."""
        rect = self.badge_rect()
        if rect is None:
            return
        style = Style(foreground=self.theme.text, background=self.theme.surface_alt)
        arrow = Style(foreground=self.theme.accent_bright, background=self.theme.surface_alt, bold=True)
        canvas.draw_spans(
            rect.x,
            rect.y,
            (
                Span(" ", style),
                Span(BADGE_ARROW, arrow),
                Span(BADGE_LABEL, style),
                Span(" ", style),
            ),
            max_width=rect.width,
        )

    def handle(self, event, host: Host) -> bool:
        """Run the badge, else toggle the clicked entry, else leave it to ScrollView."""
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN:
            badge = self.badge_rect()
            if badge is not None and badge.contains(event.x, event.y):
                self.scroll_end()
                host.invalidate()
                return True
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN and self.rect.contains(event.x, event.y):
            index = self.top + event.y - self.rect.y
            entry = self.transcript_source.entry_at(index, self.line_width)
            if entry is not None and self.transcript.toggle(entry.id):
                host.invalidate()
                return True
        # Everything else, the wheel included, belongs to ScrollView.
        return super().handle(event, host)
