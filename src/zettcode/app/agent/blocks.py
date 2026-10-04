"""Process agent entries into styled lines without mounting a widget per entry.

Processors are ordered from specific to general. Each claims entries it can
render; the first matching processor produces their TextLines. The transcript
retains only typed entries and a cached line source, and remains virtualized.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...tui import Span, Style, TextLine, Theme
from ...tui.render import SweepSpan, display_width, highlight, inset_line, layout_rich_lines, sweep_spans, truncate
from . import transcript as model
from .entries import Entry, EntryStatus, PlainEntry, ProcessingEntry, TextEntry, ThinkingEntry, ToolEntry


class EntryProcessor(ABC):
    """One link that claims entries and presents them as already-laid-out lines."""

    @abstractmethod
    def supports(self, entry: Entry) -> bool:
        """Return whether this processor can render the entry."""

    @abstractmethod
    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows this entry paints at the available width."""

    @staticmethod
    def text_lines(text: str, width: int, style: Style, *, indent: int = 0) -> list[TextLine]:
        """Wrap text with the same layout used by RichText and Markdown."""
        source = tuple(TextLine((Span(line, style),)) for line in text.split("\n"))
        margin = min(indent, max(0, width - 1))
        return [inset_line(row, margin) for row in layout_rich_lines(source, max(1, width - margin))]


class WelcomeProcessor(EntryProcessor):
    """Draw the welcome mark and its title with separate palette roles."""

    def supports(self, entry: Entry) -> bool:
        """Claim welcome banners."""
        return isinstance(entry, TextEntry) and entry.kind == "welcome"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Colour the logo, title, and subtitle without altering their text."""
        lines: list[TextLine] = []
        for index, line in enumerate(entry.text.split("\n")):
            if index in (1, 2) and "   " in line and any(glyph in line for glyph in "│╰"):
                logo, spacing, label = line.rpartition("   ")
                label_style = Style(foreground=theme.text, bold=True) if index == 1 else Style(foreground=theme.subtle)
                lines.append(TextLine((Span(logo + spacing, Style(foreground=theme.accent)), Span(label, label_style))))
            else:
                color = theme.accent if index == 0 and "╭" in line else theme.subtle
                lines.append(TextLine((Span(line, Style(foreground=color)),)))
        return lines


class NoticeProcessor(EntryProcessor):
    """Draw muted notices aligned with the answer above them."""

    def supports(self, entry: Entry) -> bool:
        """Claim notices."""
        return isinstance(entry, TextEntry) and entry.kind == "notice"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Leave a blank separator and let the transcript gutter add the inset."""
        return [TextLine(), *self.text_lines(entry.text, width, Style(foreground=theme.muted))]


class ModelChangeProcessor(EntryProcessor):
    """Center a model-change announcement between horizontal rules."""

    def supports(self, entry: Entry) -> bool:
        """Claim model-change announcements."""
        return isinstance(entry, TextEntry) and entry.kind == "model_change"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Center the label inside the padded content box.

        The transcript gutter already insets the row on the left, so the rule
        keeps the same two cells free on the right; the header, the status bar,
        and the composer all pad both edges by that amount.
        """
        margin = min(model.CONTENT_INDENT, max(0, width - 1))
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


class UserProcessor(EntryProcessor):
    """Paint a full-width message surface with its arrow flush left."""

    def supports(self, entry: Entry) -> bool:
        """Claim user messages."""
        return isinstance(entry, TextEntry) and entry.kind == "user"

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Wrap the message and fill each row to the edge of the surface."""
        style = Style(foreground=theme.text, background=theme.surface_alt)
        margin = min(model.CONTENT_INDENT, max(0, width - 1))
        prompt = self.text_lines(entry.text, max(1, width - margin), style)
        background = TextLine((Span(" " * width, style),))
        lines = [TextLine(), background]
        for index, row in enumerate(prompt):
            prefix = "\u203a "[:margin] if index == 0 else " " * margin
            body = truncate(f"{prefix}{row.text}", width)
            padding = " " * max(0, width - display_width(body))
            lines.append(TextLine((Span(body + padding, style),)))
        lines.append(background)
        return lines


class ProcessingProcessor(EntryProcessor):
    """Draw the live ``Processing`` row and its elapsed time."""

    def supports(self, entry: Entry) -> bool:
        """Claim pending model calls."""
        return isinstance(entry, ProcessingEntry)

    def lines(self, entry: ProcessingEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the sweeping label below a blank separator."""
        label = entry.title
        if entry.duration is not None:
            label += f"  {model.duration_text(entry.duration)}"
        return [TextLine(), layout_rich_lines((TextLine(_running_label(label, theme, frame)),), width, wrap=False)[0]]


class ThinkingProcessor(EntryProcessor):
    """Draw reasoning in the "model" hue, apart from the tool rows' green."""

    def supports(self, entry: Entry) -> bool:
        """Claim reasoning entries."""
        return isinstance(entry, ThinkingEntry)

    def lines(self, entry: ThinkingEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the heading, plus the indented body when expanded."""
        timing = model.duration_text(entry.duration) if entry.duration is not None else "working"
        header = Style(foreground=theme.accent_bright)
        if entry.status is EntryStatus.RUNNING:
            heading = _running_label(f"Thinking  {timing}", theme, frame)
        else:
            marker = "\u25be" if entry.expanded else "\u25b8"
            heading = (Span(f"{marker} ", header), Span(f"Thinking  {timing}", header))
        lines = [TextLine(), layout_rich_lines((TextLine(heading),), width, wrap=False)[0]]
        if entry.expanded:
            source = "\n".join(entry.text.splitlines()) if entry.text else "Waiting for reasoning\u2026"
            lines.extend(self.text_lines(source, width, Style(foreground=theme.subtle), indent=4))
        return lines


class ToolProcessor(EntryProcessor):
    """Draw a tool heading and a bounded preview of its result.

    The marker carries the outcome colour while the command itself stays in the
    body colour, so a long run of tool rows reads as neutral text with green
    ticks instead of a wall of green.
    """

    def supports(self, entry: Entry) -> bool:
        """Claim tool invocations."""
        return isinstance(entry, ToolEntry)

    def lines(self, entry: ToolEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the call, elapsed time, and optional syntax-highlighted output."""
        running = entry.status is EntryStatus.RUNNING
        symbol = (
            model.RUNNING_GLYPHS[0]
            if running
            else {
                EntryStatus.COMPLETED: "\u2713",
                EntryStatus.FAILED: "\u00d7",
                EntryStatus.SKIPPED: "\u2013",
            }.get(entry.status, "\u25cf")
        )
        marker = Style(foreground=theme.error if entry.status is EntryStatus.FAILED else theme.accent)
        label = Style(foreground=theme.text)
        muted = Style(foreground=theme.muted)
        timing = f"  {model.duration_text(entry.duration)}" if entry.duration is not None else ""
        disclosure = "" if running or not entry.text else (" \u25be" if entry.expanded else " \u25b8")
        room = max(1, width - display_width(f"{symbol} {timing}{disclosure}"))
        title = truncate(entry.title, room)
        heading: list[Span] = [Span(f"{symbol} ", marker)]
        if running:
            travel = SweepSpan(title, label, peak=Style(foreground=theme.accent_bright), ramp=3)
            heading.extend(sweep_spans(travel, model.sweep_step(frame)))
        else:
            heading.append(Span(title, label))
        if timing:
            heading.append(Span(timing, muted))
        if disclosure:
            heading.append(Span(disclosure, muted))
        lines = [TextLine(), TextLine(tuple(heading))]
        output = "Running\u2026" if running else entry.text
        if output:
            limit = model.TOOL_EXPANDED_ROWS if entry.expanded else model.TOOL_PREVIEW_ROWS
            rows, omitted = model.bounded_rows(output, max(1, width - 6), limit)
            detail = Style(foreground=theme.subtle)
            for index, row in enumerate(rows):
                lead = "    \u2514 " if index == 0 else "      "
                lines.append(self._body_line(lead, row, detail, entry.language, theme))
            if omitted:
                lines.append(TextLine((Span(f"      \u2026 {omitted} more rows", muted),)))
        return [layout_rich_lines((line,), width, wrap=False)[0] if line.spans else line for line in lines]

    @staticmethod
    def _body_line(lead: str, text: str, detail: Style, language: str | None, theme: Theme) -> TextLine:
        """Highlight file contents with their language while the gutter stays faint."""
        gutter = Style(foreground=theme.muted)
        if language is None:
            return TextLine((Span(lead, gutter), Span(text, detail)))
        return TextLine((Span(lead, gutter), *highlight(text, language, theme.code)))


class PlainProcessor(EntryProcessor):
    """Fallback presentation for an unfamiliar entry kind."""

    def supports(self, entry: Entry) -> bool:
        """Claim remaining non-Markdown entries."""
        return isinstance(entry, PlainEntry)

    def lines(self, entry: PlainEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Wrap its text in the secondary body colour."""
        return self.text_lines(entry.text, width, Style(foreground=theme.subtle))


class EntryProcessors:
    """Ordered processor chain; the first processor accepting an entry wins."""

    def __init__(self, processors: tuple[EntryProcessor, ...]) -> None:
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
        ModelChangeProcessor(),
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
    """Keep the marker still while the highlight travels through the wording."""
    resting = Style(foreground=theme.accent_bright)
    label = SweepSpan(text, resting, peak=Style(foreground=theme.text), ramp=3)
    return (Span(f"{model.RUNNING_GLYPHS[0]} ", resting), *sweep_spans(label, model.sweep_step(frame)))
