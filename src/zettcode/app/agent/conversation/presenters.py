"""Present entries as styled lines, without mounting a widget per entry.

An entry is data; a *presenter* is what turns one kind of entry into rows. There is
one presenter per :class:`~.entries.EntryKind`, held in a :class:`Presenters`
registry that looks the right one up by the entry's kind, so adding a kind of row
is three things: a member of the enum, an entry class, and a presenter that names
the kind it presents.

A presenter also says what its rows depend on (:meth:`Presenter.look`) and whether
it draws its own marker in the gutter, because both are facts about the same code
that reads the entry. The registry caches what a presenter produced on the entry,
keyed by that look, so a row that has not changed is not rendered again; the
transcript view then stacks the cached rows into one virtualized line source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import fields as dataclass_fields
from typing import Any, ClassVar, Generic, TypeVar

from ....tui import (
    DONE,
    ELLIPSIS,
    EXPANDED,
    FAILED,
    MARKER,
    PROMPT,
    SEPARATOR,
    SKIPPED,
    STATUS,
    LineSource,
    Span,
    StaticLines,
    Style,
    TextLine,
    Theme,
)
from ....tui.render import SweepSpan, display_width, highlight, inset_line, layout_rich_lines, sweep_spans, truncate
from ....tui.widgets.markdown import MarkdownSource
from ...brand import LOGO_LINES
from .entries import (
    Entry,
    EntryKind,
    EntryStatus,
    MarkdownEntry,
    NoticeLevel,
    TextEntry,
    ThinkingEntry,
    ToolEntry,
    WaitEntry,
)
from .rows import (
    COMPACTING_LABEL,
    CONTENT_INDENT,
    RUNNING_GLYPHS,
    STOP_HINT,
    TOOL_EXPANDED_ROWS,
    TOOL_PREVIEW_ROWS,
    WAIT_RAMP,
    bounded_rows,
    duration_text,
    elapsed_text,
    moving,
    sweep_column,
)

#: The entry a presenter accepts; each subclass pins it to one entry type.
E = TypeVar("E", bound=Entry)

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
    "bash": "shell",
    "todo_write": "plan",
    "read_skill": "read",
    "task": "subagent",
}


def tool_color(tool: str, theme: Theme) -> str:
    """Return the colour one tool paints its rows with."""
    return getattr(theme.tools, TOOL_ROLES.get(tool, ""), theme.accent)


#: The entry fields that are not part of how a row looks: its identity, and the
#: slots the cache itself lives in.
_NOT_LOOK = frozenset({"id", "block", "block_key"})


_LOOK_FIELDS: dict[type, tuple[str, ...]] = {}


def _look_fields(entry_type: type) -> tuple[str, ...]:
    """Return the names of the fields a row of this type may look different for.

    Worked out once per entry class and kept, because it is asked for every entry
    every time the transcript view measures it.
    """
    names = _LOOK_FIELDS.get(entry_type)
    if names is None:
        names = tuple(field.name for field in dataclass_fields(entry_type) if field.name not in _NOT_LOOK)
        _LOOK_FIELDS[entry_type] = names
    return names


class Presenter(Generic[E], ABC):
    """Turns one kind of entry into rows.

    The type parameter is the entry the presenter handles, and :attr:`kind` is the
    kind that routes it there, so :meth:`lines` receives exactly that entry.

    Attributes:
        kind: The kind of entry this presenter presents; one presenter per kind.
        gutter: Whether the rows open with a marker the presenter draws in the
            gutter's own column — the user's arrow, the wait row's sparkle, a
            tool's outcome. Every other row is inset past the gutter, so every
            leading glyph sits in one column and every line of content in the next.
    """

    kind: ClassVar[EntryKind]
    gutter: ClassVar[bool] = False

    @abstractmethod
    def lines(self, entry: E, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows this entry paints at the available width."""

    def look(self, entry: E, frame: int) -> object:
        """Return what the entry's rows depend on, so unchanged ones are not drawn again.

        The default is every field of the entry. That is the safe direction to be
        wrong in: a field nobody told the cache about changes the key and costs one
        more render, where a hand-written list that forgot it would keep showing
        the row as it was. A presenter narrows it only to leave out something that
        changes without changing the rows, and adds to it only what is not a field.
        """
        return tuple(getattr(entry, name) for name in _look_fields(type(entry)))

    def block(self, entry: E, width: int, theme: Theme, frame: int, owner: Presenters) -> LineSource:
        """Return the entry's cached rows, rendering them again only when the look changed.

        Args:
            entry: The entry to present; its cache slots hold the last result.
            width: Columns available.
            theme: Palette the rows are drawn in.
            frame: Animation step, which only a presenter that animates reads.
            owner: The registry this call came through, part of the key so a
                transcript given other presenters never reuses these rows.
        """
        key: tuple[object, ...] = (width, theme, owner, self.look(entry, frame))
        if entry.block is None or entry.block_key != key:
            margin = min(CONTENT_INDENT, max(0, width - 1))
            content_width = width if self.gutter else max(1, width - margin)
            rendered = StaticLines(self.lines(entry, content_width, theme, frame))
            entry.block = rendered if self.gutter else Indented(rendered)
            entry.block_key = key
        return entry.block

    @staticmethod
    def text_lines(text: str, width: int, style: Style, *, indent: int = 0) -> list[TextLine]:
        """Wrap text with the same layout used by RichText and Markdown."""
        source = tuple(TextLine((Span(line, style),)) for line in text.split("\n"))
        margin = min(indent, max(0, width - 1))
        return [inset_line(row, margin) for row in layout_rich_lines(source, max(1, width - margin))]


class WelcomePresenter(Presenter[TextEntry]):
    """Draw the shared brand pixels unchanged, with themed title and hint text."""

    kind = EntryKind.WELCOME

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


class NoticePresenter(Presenter[TextEntry]):
    """Draw notices aligned with the answer above them.

    A notice is a remark; one a caller marked as an error is a failure, and
    failure is what the palette's error colour is for.
    """

    kind = EntryKind.NOTICE

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Leave a blank separator and let the transcript gutter add the inset."""
        colour = theme.error if entry.level == NoticeLevel.ERROR else theme.muted
        return [TextLine(), *self.text_lines(entry.text, width, Style(foreground=colour))]


class AnnouncementPresenter(Presenter[TextEntry]):
    """Center an announcement — a model or effort change — between rules."""

    kind = EntryKind.ANNOUNCEMENT

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


class UserPresenter(Presenter[TextEntry]):
    """Paint a full-width message surface with its arrow flush left."""

    kind = EntryKind.USER
    gutter = True

    def lines(self, entry: TextEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Wrap the message and fill each row to the edge of the surface.

        The arrow sits flush left, in the column the composer's prompt is drawn in,
        so the message the reader sent lines up under the draft they are typing —
        arrow over arrow, text over text.
        """
        style = Style(foreground=theme.text, background=theme.surface_alt)
        marker = PROMPT
        if entry.side:
            # A side question is answered on screen and nowhere else: it keeps a
            # surface of its own, so the row reads as a note beside the
            # conversation rather than as one of its turns.
            style = Style(foreground=theme.subtle, background=theme.surface_side)
            marker = f"btw {PROMPT}"
        # Room kept free on the right, so no row runs into the edge of the surface.
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


class WaitPresenter(Presenter[WaitEntry]):
    """Draw the pinned wait row: a sweep while it runs, a line once it has ended.

    It is the one row that animates, and it is settled rather than removed: a
    request that was stopped still says how long it ran and when it stopped.
    """

    kind = EntryKind.WAIT
    gutter = True

    def look(self, entry: WaitEntry, frame: int) -> object:
        """Add the animation step while the row runs; a settled row is a line.

        This is the one presenter that reads the frame, which is the whole of what
        makes the wait row the one row that moves: every other row's look is its
        fields, and an animation step leaves it as it was.
        """
        return (super().look(entry, frame), frame if entry.running else 0)

    def lines(self, entry: WaitEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Pulse the word below a blank separator, or show the line it settled into.

        The clock and the key that stops the request stand beside the word in
        parentheses, in the same quiet ink a notice uses, so they read as one
        aside rather than as part of the row's business — and the highlight crosses
        the word alone, never the aside. The clock counts whole seconds: tenths of
        a second are more detail than a reader waiting on a request wants.
        """
        if not entry.running:
            settled = entry.text or f"Processed for {elapsed_text(entry.duration or 0.0)}"
            return [
                TextLine(),
                layout_rich_lines(
                    (TextLine((Span(" " * CONTENT_INDENT + settled, Style(foreground=theme.muted)),)),),
                    width,
                    wrap=False,
                )[0],
            ]
        spans = list(_running_label(entry.title, theme, frame))
        if entry.duration is not None:
            aside = f" ({elapsed_text(entry.duration)} {SEPARATOR} {STOP_HINT})"
            spans.append(Span(aside, Style(foreground=theme.muted)))
        return [TextLine(), layout_rich_lines((TextLine(tuple(spans)),), width, wrap=False)[0]]


class ThinkingPresenter(Presenter[ThinkingEntry]):
    """Draw reasoning in the "model" hue, apart from the tool rows' green."""

    kind = EntryKind.THINKING
    gutter = True

    def lines(self, entry: ThinkingEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the heading, plus the indented body when expanded."""
        header = Style(foreground=theme.accent_bright)
        if entry.running:
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
            lines.extend(self.text_lines(source, width, Style(foreground=theme.subtle), indent=CONTENT_INDENT))
        return lines


class ToolPresenter(Presenter[ToolEntry]):
    """Draw a tool heading and a bounded preview of its result.

    A row is painted in the hue of the tool that ran, so a transcript reads by
    what was done: reading, searching, editing, running. Tools that do the same
    thing share a hue, and a failed row is red whatever the tool was.
    """

    kind = EntryKind.TOOL
    gutter = True

    def lines(self, entry: ToolEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the call, elapsed time, and optional syntax-highlighted output."""
        running = entry.running
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
        if entry.added:
            heading.append(Span(f" +{entry.added}", Style(foreground=theme.accent)))
        if entry.removed:
            heading.append(Span(f" -{entry.removed}", Style(foreground=theme.error)))
        if timing:
            heading.append(Span(timing, muted))
        if disclosure:
            heading.append(Span(disclosure, muted))
        lines = [TextLine(), TextLine(tuple(heading))]
        output = f"Running{ELLIPSIS}" if running else entry.text
        if output:
            limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
            rows, omitted = bounded_rows(output, max(1, width - CONTENT_INDENT * 2), limit)
            detail = Style(foreground=theme.subtle)
            for index, row in enumerate(rows):
                lead = f"{' ' * CONTENT_INDENT}\u2514 " if index == 0 else " " * (CONTENT_INDENT * 2)
                lines.append(self._body_line(lead, row, detail, entry.language, theme))
            if omitted:
                lines.append(TextLine((Span(f"{' ' * (CONTENT_INDENT * 2)}{ELLIPSIS} {omitted} more rows", muted),)))
        return [layout_rich_lines((line,), width, wrap=False)[0] if line.spans else line for line in lines]

    @staticmethod
    def _body_line(lead: str, text: str, detail: Style, language: str | None, theme: Theme) -> TextLine:
        """Highlight file contents with their language while the gutter stays faint."""
        gutter = Style(foreground=theme.muted)
        if language is None:
            return TextLine((Span(lead, gutter), Span(text, detail)))
        return TextLine((Span(lead, gutter), *highlight(text, language, theme.code)))


class MarkdownPresenter(Presenter[MarkdownEntry]):
    """Present a Markdown row by serving its parsed document rather than rendering rows.

    The reply streams in, so rendering it again per token would make a long answer
    cost more with every word. The entry's ``Markdown`` parses incrementally and
    serves its lines on demand; this presenter wraps that once, behind the blank
    row that separates it from the row above, and afterwards only keeps the
    palette current. That is why it overrides :meth:`block` and does not use the
    look-keyed cache: the source is the cache.
    """

    def lines(self, entry: MarkdownEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return every row of the document at one width, for a caller that wants them all."""
        entry.markdown.theme = theme
        source = LeadingGap(MarkdownSource(entry.markdown))
        return [source.line(index, width) for index in range(source.count(width))]

    def block(self, entry: MarkdownEntry, width: int, theme: Theme, frame: int, owner: Presenters) -> LineSource:
        """Keep streamed Markdown virtualized instead of re-rendering it per frame."""
        entry.markdown.theme = theme
        if entry.block is None:
            entry.block = Indented(LeadingGap(MarkdownSource(entry.markdown)))
        return entry.block


class AnswerPresenter(MarkdownPresenter):
    """Present the model's reply as it streams in."""

    kind = EntryKind.ANSWER


class MessagePresenter(MarkdownPresenter):
    """Present Markdown that is not a reply, such as a command's output."""

    kind = EntryKind.MESSAGE


class Presenters:
    """The presenters of one transcript, looked up by the kind of entry each presents.

    There is exactly one presenter per kind, and a later one for a kind replaces an
    earlier one, which is how a transcript is given a different way to draw a kind
    without a chain whose order has to be right: :meth:`replacing`.
    """

    def __init__(self, presenters: Iterable[Presenter[Any]]) -> None:
        """Register presenters by kind; the last one given for a kind wins."""
        self._by_kind: dict[EntryKind, Presenter[Any]] = {}
        for presenter in presenters:
            self._by_kind[presenter.kind] = presenter

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the registered presenters, one per kind."""
        return tuple(self._by_kind.values())

    def replacing(self, *presenters: Presenter[Any]) -> Presenters:
        """Return a registry that draws the given kinds with the given presenters."""
        return Presenters((*self.presenters, *presenters))

    def for_entry(self, entry: Entry) -> Presenter[Any]:
        """Return the presenter for an entry's kind, or say which kind has none."""
        try:
            return self._by_kind[entry.kind]
        except KeyError:
            raise ValueError(f"No presenter for a {entry.kind.value} row") from None

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows an entry paints, rendered now and not cached."""
        return self.for_entry(entry).lines(entry, width, theme, frame)

    def block(self, entry: Entry, width: int, theme: Theme, frame: int) -> LineSource:
        """Return an entry's rows as a cached line source, in the gutter's layout."""
        return self.for_entry(entry).block(entry, width, theme, frame, self)


DEFAULT_PRESENTERS = Presenters(
    (
        WelcomePresenter(),
        UserPresenter(),
        NoticePresenter(),
        AnnouncementPresenter(),
        AnswerPresenter(),
        MessagePresenter(),
        WaitPresenter(),
        ThinkingPresenter(),
        ToolPresenter(),
    )
)


def render_entry(
    entry: Entry, width: int, theme: Theme, frame: int, *, presenters: Presenters = DEFAULT_PRESENTERS
) -> list[TextLine]:
    """Render one entry's rows now, through the presenter for its kind."""
    return presenters.lines(entry, width, theme, frame)


def block_for(
    entry: Entry, width: int, theme: Theme, frame: int, *, presenters: Presenters = DEFAULT_PRESENTERS
) -> LineSource:
    """Return an entry's rows as a line source, rendering again only when its look changed."""
    return presenters.block(entry, width, theme, frame)


class LeadingGap(LineSource):
    """LineSource that renders one blank row before a nested source.

    Streamed answers are served by ``Markdown`` so their parsing stays
    incremental, which means the separating blank line cannot come from the
    generic presenter.
    """

    def __init__(self, source: LineSource) -> None:
        """Wrap the nested line source.

        Args:
            source: Line source whose rows shift down by one; it is a
                ``LineSource`` itself, so the wrapper stays composable.
        """
        self.source = source

    def count(self, width: int) -> int:
        """Return the nested line count plus the leading blank row."""
        return self.source.count(width) + 1

    def line(self, index: int, width: int) -> TextLine:
        """Shift the index past the blank row and delegate to the nested source."""
        if index == 0:
            return TextLine()
        return self.source.line(index - 1, width)


class Indented(LineSource):
    """LineSource that shifts every row right by a fixed margin.

    The margin is drawn with the row's own leading style, so a line that carries
    a background keeps it across the gutter. The nested source wraps at the
    remaining width, which keeps long lines inside the window instead of
    wrapping past its right edge.
    """

    def __init__(self, source: LineSource, columns: int = CONTENT_INDENT) -> None:
        """Wrap ``source`` with ``columns`` cells of leading space.

        Args:
            source: Line source to shift right.
            columns: Margin in cells; the nested source wraps that much narrower.
        """
        self.source = source
        self.columns = max(0, columns)

    def count(self, width: int) -> int:
        """Return the nested row count, which the margin does not change."""
        return self.source.count(max(1, width - self._margin(width)))

    def line(self, index: int, width: int) -> TextLine:
        """Draw the margin, then the nested row at the reduced width."""
        margin = self._margin(width)
        row = self.source.line(index, max(1, width - margin))
        return inset_line(row, margin)

    def _margin(self, width: int) -> int:
        """Keep at least one column available for content on narrow screens."""
        return min(self.columns, max(0, width - 1))


def _running_label(text: str, theme: Theme, frame: int) -> tuple[Span, ...]:
    """Pulse the waiting row: one frame count drives the marker and the highlight.

    The row moves for a second — the marker lit, the highlight crossing
    the label — and then rests for a second, in which neither moves: the marker is
    the quiet ink's dot so the row keeps its shape without blinking, and the label
    is painted flat. Both halves read the same frame counter, so neither depends
    on how often the terminal repaints, and the marker is in step with the status
    bar's icon. Only the waiting row is drawn with this, which is what makes it
    the one thing that moves.
    """
    resting = Style(foreground=theme.accent_bright)
    if not moving(frame):
        return (Span(f"{RUNNING_GLYPHS[1]} ", Style(foreground=theme.muted)), Span(text, resting))
    label = SweepSpan(text, resting, peak=Style(foreground=theme.text), ramp=WAIT_RAMP)
    return (Span(f"{RUNNING_GLYPHS[0]} ", resting), *sweep_spans(label, sweep_column(frame, label.travel)))
