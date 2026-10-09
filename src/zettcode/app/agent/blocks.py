"""Process agent entries into styled lines without mounting a widget per entry.

Processors are ordered from specific to general. Each claims entries it can
render; the first matching processor produces their TextLines. The transcript
retains only typed entries and a cached line source, and remains virtualized.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from ...tui import (
    DONE,
    ELLIPSIS,
    EXPANDED,
    FAILED,
    MARKER,
    PROMPT,
    SKIPPED,
    STATUS,
    Span,
    Style,
    TextLine,
    Theme,
)
from ...tui.render import SweepSpan, display_width, highlight, inset_line, layout_rich_lines, sweep_spans, truncate
from ..brand import LOGO_LINES
from .entries import Entry, EntryStatus, PlainEntry, ProcessingEntry, TextEntry, ThinkingEntry, ToolEntry
from .rows import (
    COMPACTING_LABEL,
    CONTENT_INDENT,
    RUNNING_GLYPHS,
    TOOL_EXPANDED_ROWS,
    TOOL_PREVIEW_ROWS,
    activity_glyph,
    bounded_rows,
    duration_text,
    sweep_column,
)

#: The entry a processor accepts; each subclass pins it to one entry type.
E = TypeVar("E")

#: Palette role that paints a tool, by the action it performs. The built-in
#: palettes give every role the same violet; a theme file can separate them. A
#: tool this table has never seen falls back to the generic accent.
TOOL_ROLES = {
    "read_file": "read",
    "view_image": "image",
    "glob": "search",
    "grep": "search",
    "write_file": "write",
    "replace_in_file": "write",
    "delete_file": "delete",
    "run_shell": "shell",
    "todo_write": "plan",
    "read_skill": "read",
    "task": "subagent",
}


def tool_color(tool: str, theme: Theme) -> str:
    """Return the colour one tool paints its rows with."""
    return getattr(theme.tools, TOOL_ROLES.get(tool, ""), theme.accent)


class EntryProcessor(Generic[E], ABC):
    """One link that claims entries and presents them as already-laid-out lines.

    The type parameter is the entry the processor handles; the chain dispatches
    on :meth:`supports`, so ``lines`` receives exactly that entry.
    """

    @abstractmethod
    def supports(self, entry: Entry) -> bool:
        """Return whether this processor can render the entry."""

    @abstractmethod
    def lines(self, entry: E, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows this entry paints at the available width."""

    @staticmethod
    def text_lines(text: str, width: int, style: Style, *, indent: int = 0) -> list[TextLine]:
        """Wrap text with the same layout used by RichText and Markdown."""
        source = tuple(TextLine((Span(line, style),)) for line in text.split("\n"))
        margin = min(indent, max(0, width - 1))
        return [inset_line(row, margin) for row in layout_rich_lines(source, max(1, width - margin))]


class WelcomeProcessor(EntryProcessor[TextEntry]):
    """Draw the shared brand pixels unchanged, with themed title and hint text."""

    def supports(self, entry: Entry) -> bool:
        """Claim welcome banners."""
        return isinstance(entry, TextEntry) and entry.kind == "welcome"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Keep labels beside the mark, stacking them when the window is narrow."""
        if width <= 0:
            return []
        lines: list[TextLine] = []
        marks: list[TextLine] = []
        labels: list[TextLine] = []
        titled = False
        for index, line in enumerate(entry.text.split("\n")):
            mark = LOGO_LINES[index] if index < len(LOGO_LINES) else None
            if mark is not None and line.startswith(f"  {mark.text}"):
                spans = [Span("  "), *mark.spans]
                marks.append(TextLine(tuple(spans)))
                label = line[2 + len(mark.text) :]
                if label:
                    style = Style(foreground=theme.subtle) if titled else Style(foreground=theme.text, bold=True)
                    spans.append(Span(label, style))
                    labels.append(TextLine((Span(label.lstrip(), style),)))
                    titled = True
                lines.append(TextLine(tuple(spans)))
            else:
                lines.append(TextLine((Span(line, Style(foreground=theme.subtle)),)))
        if marks and any(line.width > width for line in lines):
            stacked = [*marks, TextLine(), *(inset_line(label, 2) for label in labels)]
            return list(layout_rich_lines(stacked, width, wrap=False))
        return lines


class NoticeProcessor(EntryProcessor[TextEntry]):
    """Draw notices aligned with the answer above them.

    A notice is a remark; one a caller marked as an error is a failure, and
    failure is what the palette's error colour is for.
    """

    def supports(self, entry: Entry) -> bool:
        """Claim notices."""
        return isinstance(entry, TextEntry) and entry.kind == "notice"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Leave a blank separator and let the transcript gutter add the inset."""
        colour = theme.error if entry.level == "error" else theme.muted
        return [TextLine(), *self.text_lines(entry.text, width, Style(foreground=colour))]


class AnnouncementProcessor(EntryProcessor[TextEntry]):
    """Center an announcement — a model or effort change — between rules."""

    def supports(self, entry: Entry) -> bool:
        """Claim announcements."""
        return isinstance(entry, TextEntry) and entry.kind == "announcement"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Center the label inside the padded content box.

        The transcript gutter already insets the row on the left, so the rule
        keeps the same two cells free on the right; the header, the status bar,
        and the composer all pad both edges by that amount.
        """
        margin = min(CONTENT_INDENT, max(0, width - 1))
        available = max(1, width - margin)
        if available <= 2:
            return [TextLine(), TextLine((Span("─" * available, Style(foreground=theme.border)),)), TextLine()]
        heading = TextLine(
            (Span("◇ ", Style(foreground=theme.accent)), Span(entry.text, Style(foreground=theme.subtle)))
        )
        heading = heading.layout(available - 2, wrap=False)[0]
        remaining = max(0, available - heading.width - 2)
        left = remaining // 2
        right = remaining - left
        rule = Style(foreground=theme.border)
        line = TextLine(
            (
                Span("─" * left + " ", rule),
                *heading.spans,
                Span(" " + "─" * right, rule),
            )
        )
        return [TextLine(), line, TextLine()]


class UserProcessor(EntryProcessor[TextEntry]):
    """Paint a full-width message surface with its arrow flush left."""

    def supports(self, entry: Entry) -> bool:
        """Claim user messages."""
        return isinstance(entry, TextEntry) and entry.kind == "user"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Wrap the message and fill each row to the edge of the surface."""
        style = Style(foreground=theme.text, background=theme.surface_alt)
        marker = PROMPT
        if entry.side:
            # A side question is answered on screen and nowhere else: it keeps a
            # surface of its own, so the row reads as a note beside the
            # conversation rather than as one of its turns.
            style = Style(foreground=theme.subtle, background=theme.surface_side)
            marker = f"btw {PROMPT}"
        margin = min(CONTENT_INDENT, max(0, width - 1))
        prompt = self.text_lines(entry.text, max(1, width - margin), style)
        background = TextLine((Span(" " * width, style),))
        lines = [TextLine(), background]
        pad = " " * display_width(marker)
        for index, row in enumerate(prompt):
            prefix = f"{marker} " if index == 0 else f"{pad} "
            body = truncate(f"{prefix}{row.text}", width)
            padding = " " * max(0, width - display_width(body))
            lines.append(TextLine((Span(body + padding, style),)))
        lines.append(background)
        return lines


class ProcessingProcessor(EntryProcessor[ProcessingEntry]):
    """Draw the pinned wait row: a sweep while it runs, a line once it has ended.

    It is the one row that animates, and it is settled rather than removed: a
    request that was stopped still says how long it ran and when it stopped.
    """

    def supports(self, entry: Entry) -> bool:
        """Claim pending model calls."""
        return isinstance(entry, ProcessingEntry)

    def lines(self, entry: ProcessingEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Sweep the label below a blank separator, or show the line it settled into."""
        if entry.status is not EntryStatus.RUNNING:
            settled = entry.text or f"Processed for {duration_text(entry.duration)}"
            return [
                TextLine(),
                layout_rich_lines((TextLine((Span(settled, Style(foreground=theme.muted)),)),), width, wrap=False)[0],
            ]
        label = entry.title
        if entry.duration is not None:
            label += f"  {duration_text(entry.duration)}"
        return [TextLine(), layout_rich_lines((TextLine(_running_label(label, theme, frame)),), width, wrap=False)[0]]


class ThinkingProcessor(EntryProcessor[ThinkingEntry]):
    """Draw reasoning in the "model" hue, apart from the tool rows' green."""

    def supports(self, entry: Entry) -> bool:
        """Claim reasoning entries."""
        return isinstance(entry, ThinkingEntry)

    def lines(self, entry: ThinkingEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the heading, plus the indented body when expanded."""
        header = Style(foreground=theme.accent_bright)
        if entry.status is EntryStatus.RUNNING:
            timing = duration_text(entry.duration) if entry.duration is not None else "working"
            # The marker is painted flat, like a settled row's: the waiting row
            # is the one thing that sweeps, so a run with reasoning and tools in
            # flight keeps one moving row instead of one per row on screen.
            heading = (Span(f"{RUNNING_GLYPHS[0]} ", header), Span(f"{entry.title}  {timing}", header))
        else:
            # A finished row whose duration was never recorded says nothing about
            # time; calling it "working" would claim a run that has already ended.
            timing = f"  {duration_text(entry.duration)}" if entry.duration is not None else ""
            marker = EXPANDED if entry.expanded else MARKER
            heading = (Span(f"{marker} ", header), Span(f"{entry.title}{timing}", header))
        lines = [TextLine(), layout_rich_lines((TextLine(heading),), width, wrap=False)[0]]
        if entry.expanded:
            waiting = "summary" if entry.title == COMPACTING_LABEL else "reasoning"
            source = "\n".join(entry.text.splitlines()) if entry.text else f"Waiting for {waiting}{ELLIPSIS}"
            lines.extend(self.text_lines(source, width, Style(foreground=theme.subtle), indent=4))
        return lines


class ToolProcessor(EntryProcessor[ToolEntry]):
    """Draw a tool heading and a bounded preview of its result.

    A row is painted in the hue of the tool that ran, so a transcript reads by
    what was done: reading, searching, editing, running. Tools that do the same
    thing share a hue, and a failed row is red whatever the tool was.
    """

    def supports(self, entry: Entry) -> bool:
        """Claim tool invocations."""
        return isinstance(entry, ToolEntry)

    def lines(self, entry: ToolEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the call, elapsed time, and optional syntax-highlighted output."""
        running = entry.status is EntryStatus.RUNNING
        symbol = (
            RUNNING_GLYPHS[0]
            if running
            else {
                EntryStatus.COMPLETED: DONE,
                EntryStatus.FAILED: FAILED,
                EntryStatus.SKIPPED: SKIPPED,
            }.get(entry.status, STATUS)
        )
        hue = tool_color(entry.tool, theme)
        colour = theme.error if entry.status is EntryStatus.FAILED else hue
        marker = Style(foreground=colour)
        label = Style(foreground=colour)
        muted = Style(foreground=theme.muted)
        timing = f"  {duration_text(entry.duration)}" if entry.duration is not None else ""
        disclosure = "" if running or not entry.text else (f" {EXPANDED}" if entry.expanded else f" {MARKER}")
        room = max(1, width - display_width(f"{symbol} {timing}{disclosure}"))
        title = truncate(entry.title, room)
        # A running title is painted flat, exactly as a settled one is: the
        # waiting row owns the motion, and a row that does not move is a row an
        # animation step never has to rebuild.
        heading: list[Span] = [Span(f"{symbol} ", marker), Span(title, label)]
        if timing:
            heading.append(Span(timing, muted))
        if disclosure:
            heading.append(Span(disclosure, muted))
        lines = [TextLine(), TextLine(tuple(heading))]
        output = f"Running{ELLIPSIS}" if running else entry.text
        if output:
            limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
            rows, omitted = bounded_rows(output, max(1, width - 6), limit)
            detail = Style(foreground=theme.subtle)
            for index, row in enumerate(rows):
                lead = "    \u2514 " if index == 0 else "      "
                lines.append(self._body_line(lead, row, detail, entry.language, theme))
            if omitted:
                lines.append(TextLine((Span(f"      {ELLIPSIS} {omitted} more rows", muted),)))
        return [layout_rich_lines((line,), width, wrap=False)[0] if line.spans else line for line in lines]

    @staticmethod
    def _body_line(lead: str, text: str, detail: Style, language: str | None, theme: Theme) -> TextLine:
        """Highlight file contents with their language while the gutter stays faint."""
        gutter = Style(foreground=theme.muted)
        if language is None:
            return TextLine((Span(lead, gutter), Span(text, detail)))
        return TextLine((Span(lead, gutter), *highlight(text, language, theme.code)))


class PlainProcessor(EntryProcessor[PlainEntry]):
    """Fallback presentation for an unfamiliar entry kind."""

    def supports(self, entry: Entry) -> bool:
        """Claim remaining non-Markdown entries."""
        return isinstance(entry, PlainEntry)

    def lines(self, entry: PlainEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Wrap its text in the secondary body colour."""
        return self.text_lines(entry.text, width, Style(foreground=theme.subtle))


class EntryProcessors:
    """Ordered processor chain; the first processor accepting an entry wins."""

    def __init__(self, processors: tuple[EntryProcessor[Any], ...]) -> None:
        self.processors = processors

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Dispatch to a matching processor or reject unsupported entries."""
        for processor in self.processors:
            if processor.supports(entry):
                return processor.lines(entry, width, theme, frame)
        raise ValueError(f"No processor for {type(entry).__name__}")


DEFAULT_PROCESSORS = EntryProcessors(
    (
        WelcomeProcessor(),
        NoticeProcessor(),
        AnnouncementProcessor(),
        UserProcessor(),
        ProcessingProcessor(),
        ThinkingProcessor(),
        ToolProcessor(),
        PlainProcessor(),
    )
)


def render_entry(
    entry: Entry, width: int, theme: Theme, frame: int, *, processors: EntryProcessors = DEFAULT_PROCESSORS
) -> list[TextLine]:
    """Render one entry through the ordered processor chain."""
    return processors.lines(entry, width, theme, frame)


def _running_label(text: str, theme: Theme, frame: int) -> tuple[Span, ...]:
    """Blink the marker, and cross the wording once a second, on one frame count.

    Both halves of the blink are one column wide, so the label never shifts as
    the marker turns over, and the marker reads the same frame as the status
    bar's dot: the row and the icon blink in step. The highlight takes a whole
    pass per second whatever the label's length, which is the point of pacing it
    by time: a long row is not swept more slowly than a short one. Only the
    waiting row is drawn with this, which is what makes it the one thing that
    moves.
    """
    resting = Style(foreground=theme.accent_bright)
    label = SweepSpan(text, resting, peak=Style(foreground=theme.text), ramp=3)
    return (Span(f"{activity_glyph(frame)} ", resting), *sweep_spans(label, sweep_column(frame, label.travel)))
