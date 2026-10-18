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

from zettcode.app.brand import LOGO_LINES
from zettcode.tui import (
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
from zettcode.tui.render import (
    SweepSpan,
    blend,
    display_width,
    highlight,
    inset_line,
    layout_rich_lines,
    sweep_spans,
    truncate,
    wrap_words,
)
from zettcode.tui.widgets.markdown import MarkdownSource

from .entries import (
    ChangesEntry,
    EditEntry,
    Entry,
    EntryKind,
    EntryStatus,
    FileChangeEntry,
    FileSummary,
    MarkdownEntry,
    MessageEntry,
    NoticeLevel,
    ReadEntry,
    RelayEntry,
    TextEntry,
    ThinkingEntry,
    ToolEntry,
    WaitEntry,
    WriteEntry,
)
from .pulse import RUNNING_GLYPHS, WAIT_RAMP, moving, sweep_column
from .text import (
    COMPACTING_LABEL,
    CONTENT_INDENT,
    STOP_HINT,
    TOOL_EXPANDED_ROWS,
    TOOL_PREVIEW_ROWS,
    bounded_rows,
    duration_text,
    elapsed_text,
    quiet_text,
    terminal_safe,
    tip_text,
)

#: Columns a tip's text is inset by: the same two the tools' results use for their hook.
TIP_INDENT = 2

#: The entry a presenter accepts; each subclass pins it to one entry type.
E = TypeVar("E", bound=Entry)

#: The tool entry a tool presenter accepts.
T = TypeVar("T", bound=ToolEntry)

#: The file-changing tool entry a file-change presenter accepts.
F = TypeVar("F", bound=FileChangeEntry)

#: Palette role that paints a tool, by the action it performs. The built-in
#: palettes give every role the same violet; a theme file can separate them. A
#: tool this table has never seen falls back to the generic accent.
TOOL_ROLES = {
    "read_file": "read",
    "read": "read",
    "view_image": "image",
    "glob": "search",
    "grep": "search",
    "write_file": "write",
    "edit": "write",
    "replace_in_file": "write",  # what a session stored before the rename called it
    "delete_file": "delete",
    "bash": "shell",
    "todo_write": "plan",
    "read_skill": "read",
    "task": "subagent",
    "send_message": "message",
    "list_sessions": "message",
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
        entry_type: The entry class this presenter is for, when it is for one family of a kind
            rather than the kind as a whole: the presenter of an edit row is the one for
            ``EditEntry``, though an edit row is a ``tool`` row like any other. The registry looks
            for the entry's own class first (and its parents') and the kind second.
        gutter: Whether the rows open with a marker the presenter draws in the
            gutter's own column — the user's arrow, the wait row's sparkle, a
            tool's outcome. Every other row is inset past the gutter, so every
            leading glyph sits in one column and every line of content in the next.
        priority: How strongly this presenter claims the rows it draws, when more than one could draw
            them. The higher number wins, and an equal number goes to whichever was registered later,
            so the built-in presenters - priority 0, registered first - are what a transcript uses
            until a plugin registers its own. A plugin that wants to replace only some families of a
            kind, or to beat another plugin, raises this.
    """

    kind: ClassVar[EntryKind]
    entry_type: ClassVar[type[Entry] | None] = None
    gutter: ClassVar[bool] = False
    priority: ClassVar[int] = 0

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
    def text_lines(text: str, width: int, style: Style, *, indent: int = 0, words: bool = False) -> list[TextLine]:
        """Wrap text with the same layout used by RichText and Markdown.

        Args:
            text: What to wrap; each newline starts a new row.
            width: Columns available.
            style: The ink the text is drawn in.
            indent: Columns left empty at the start of every row.
            words: Break between words and not mid-word. For a sentence a reader is meant to read, such as an
                error naming a command to try; left off, a row breaks at the column, as code and output must.
        """
        margin = min(indent, max(0, width - 1))
        room = max(1, width - margin)
        if words:
            rows = [piece for line in text.split("\n") for piece in wrap_words(line, room)]
            # A character wider than the whole row (a wide glyph in a column or two) cannot be placed in it;
            # the layout that wraps by column cuts such a row to the budget, and so does this.
            fitted = layout_rich_lines(tuple(TextLine((Span(row, style),)) for row in rows), room, wrap=False)
            return [inset_line(row, margin) for row in fitted]
        source = tuple(TextLine((Span(line, style),)) for line in text.split("\n"))
        return [inset_line(row, margin) for row in layout_rich_lines(source, room)]


def _welcome_label(label: str, theme: Theme, *, titled: bool) -> list[Span]:
    """Style one label of the banner: the title in bold, everything after it in the quiet colour.

    The title line is the name and, two spaces after it, the version. The name is the one bold thing; the
    version is the same line's quiet part, so it reads as a fact about the name rather than as part of it.
    """
    quiet = Style(foreground=theme.subtle)
    if titled:
        return [Span(label, quiet)]
    name, gap, rest = _after_indent(label)
    spans = [Span(name, Style(foreground=theme.text, bold=True))]
    if rest:
        spans.append(Span(gap + rest, quiet))
    return spans


def _after_indent(label: str) -> tuple[str, str, str]:
    """Split an indented title into its name (indent included), the gap, and what follows the gap."""
    body = label.lstrip()
    indent = label[: len(label) - len(body)]
    name, gap, rest = body.partition("  ")
    return indent + name, gap, rest.strip()


def _unindented(spans: list[Span]) -> list[Span]:
    """Return the spans of a label without the indent it has beside the mark, for stacking under it."""
    first = spans[0]
    return [Span(first.text.lstrip(), first.style), *spans[1:]]


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
                    shown = _welcome_label(label, theme, titled=titled)
                    spans.extend(shown)
                    labels.append(TextLine(tuple(_unindented(shown))))
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
        return [TextLine(), *self.text_lines(entry.text, width, Style(foreground=colour), words=True)]


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


def relay_detail(theme: Theme) -> str:
    """Return the colour of the quiet words on a message between sessions (``delivered``, ``queued``).

    The surface is a little lighter than the reader's own, and the usual quiet text would be too close to
    it, so the words are taken halfway to the body colour: still quieter than the message, and readable.
    """
    return blend(theme.subtle, theme.text, 0.5)


class RelayPresenter(Presenter[RelayEntry]):
    """Draw a message between two sessions the way the reader's own message is drawn, on a surface of its own.

    Same arrow, same text column, same filled rows as what the reader types — it is part of the
    conversation — but on a different background, with a line above the text that says whose it is::

        ← agent of session fix-the-parser
        › The tokenizer change is merged; can you rerun the parser tests?

        → to session fix-the-parser · queued
        › yes, on it

    The header is the one place colour says who spoke: the message colour (mauve) for another session's
    *agent* (another agent, as a delegated child is), the warning yellow for another session's reader,
    and the accent for this reader's own message to it.
    """

    kind = EntryKind.RELAY
    gutter = True

    def lines(self, entry: RelayEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the header and the wrapped message on the surface, every row filled to the edge."""
        if entry.outgoing:
            tone = theme.accent
        elif entry.external:
            tone = theme.warning
        elif entry.by_agent:
            tone = theme.tools.message
        else:
            tone = theme.warning
        style = Style(foreground=theme.text, background=theme.surface_peer)
        margin = min(CONTENT_INDENT, max(0, width - 1))
        pad = " " * display_width(PROMPT)
        peer = terminal_safe(entry.peer).replace("\n", " ")
        if entry.outgoing:
            label = f"\u2192 to session {peer}"
            detail = f" {SEPARATOR} {entry.note}" if entry.note else ""
        else:
            label = (
                f"\u2190 external source {peer}"
                if entry.external
                else f"\u2190 {'agent' if entry.by_agent else 'user'} of session {peer}"
            )
            detail = ""

        def row(*spans: Span) -> TextLine:
            used = sum(display_width(span.text) for span in spans)
            return TextLine((*spans, Span(" " * max(0, width - used), style)))

        head = truncate(f"{pad} {label}", width)
        tail = truncate(detail, max(0, width - display_width(head)))
        header = row(
            Span(head, Style(foreground=tone, background=theme.surface_peer)),
            Span(tail, Style(foreground=relay_detail(theme), background=theme.surface_peer)),
        )
        blank = row()
        lines = [TextLine(), blank, header]
        for index, text in enumerate(self.text_lines(terminal_safe(entry.text), max(1, width - margin), style)):
            prefix = f"{PROMPT} " if index == 0 else f"{pad} "
            lines.append(row(Span(truncate(f"{prefix}{text.text}", width), style)))
        lines.append(blank)
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
            quiet = quiet_text(entry.quiet)
            said = f"{elapsed_text(entry.duration)} {SEPARATOR} "
            if quiet is not None:
                # In the warning ink, apart from the quiet aside around it: this is the one thing in the row
                # that says something may be wrong, and a reader who has been waiting is looking for it.
                spans.append(Span(f" ({said}", Style(foreground=theme.muted)))
                spans.append(Span(quiet, Style(foreground=theme.warning)))
                spans.append(Span(f" {SEPARATOR} {STOP_HINT})", Style(foreground=theme.muted)))
            else:
                spans.append(Span(f" ({said}{STOP_HINT})", Style(foreground=theme.muted)))
        rows = [TextLine(), layout_rich_lines((TextLine(tuple(spans)),), width, wrap=False)[0]]
        tip = tip_text(entry.tips, entry.duration)
        if tip is not None:
            # Under the word, in the quiet ink and hung from it the way a tool's result is: it is not about the
            # request, so it must not read as part of it.
            gutter, ink = Style(foreground=theme.muted), Style(foreground=theme.muted)
            text = self.text_lines(f"Tip: {tip}", max(1, width - TIP_INDENT * 2), ink, words=True)
            for index, row in enumerate(text):
                lead = f"{' ' * CONTENT_INDENT}\u2514 " if index == 0 else " " * (CONTENT_INDENT * 2)
                rows.append(TextLine((Span(lead, gutter), *row.spans)))
        return rows


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


class ToolPresenter(Presenter[T]):
    """Draw a tool heading and a bounded preview of its result.

    A row is painted in the hue of the tool that ran, so a transcript reads by
    what was done: reading, searching, editing, running. Tools that do the same
    thing share a hue, and a failed row is red whatever the tool was.

    This is the row every tool has. A tool whose entry carries more has a presenter that
    extends this one in the two places a row can differ — what is written after the title
    (:meth:`after_title`) and what is written under it (:meth:`body_lines`) — and nothing
    else, so the symbol, the timer, the fold and the preview limits are the same for all of
    them and cannot drift apart.
    """

    kind = EntryKind.TOOL
    gutter = True

    def lines(self, entry: T, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Show the call, elapsed time, and whatever body the tool's entry has."""
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
        disclosure = "" if not entry.foldable else (f" {EXPANDED}" if entry.expanded else f" {MARKER}")
        room = max(1, width - display_width(f"{symbol} {timing}{disclosure}"))
        title = truncate(entry.title, room)
        # A running title is painted flat, exactly as a settled one is: the
        # waiting row owns the motion, and a row that does not move is a row an
        # animation step never has to rebuild.
        heading: list[Span] = [Span(f"{symbol} ", marker), Span(title, label), *self.after_title(entry, theme)]
        if timing:
            heading.append(Span(timing, muted))
        if disclosure:
            heading.append(Span(disclosure, muted))
        lines = [TextLine(), TextLine(tuple(heading))]
        lines.extend(self.body_lines(entry, width, theme, muted))
        return [layout_rich_lines((line,), width, wrap=False)[0] if line.spans else line for line in lines]

    def after_title(self, entry: T, theme: Theme) -> list[Span]:
        """Return what follows the title on the heading row; a plain tool has nothing to add."""
        return []

    def body_lines(self, entry: T, width: int, theme: Theme, muted: Style) -> list[TextLine]:
        """Return the rows under the heading: the tool's output, bounded, or that it is running."""
        return self.output_lines(entry, width, theme, muted, language=None)

    @staticmethod
    def output_lines(
        entry: ToolEntry, width: int, theme: Theme, muted: Style, *, language: str | None
    ) -> list[TextLine]:
        """Return the bounded preview of a tool's output, highlighted as ``language`` when it has one."""
        output = f"Running{ELLIPSIS}" if entry.running else entry.text
        if not output:
            return []
        limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
        rows, omitted = bounded_rows(output, max(1, width - CONTENT_INDENT * 2), limit)
        detail = Style(foreground=theme.subtle)
        gutter = Style(foreground=theme.muted)
        lines: list[TextLine] = []
        for index, row in enumerate(rows):
            lead = f"{' ' * CONTENT_INDENT}\u2514 " if index == 0 else " " * (CONTENT_INDENT * 2)
            if language is None:
                lines.append(TextLine((Span(lead, gutter), Span(row, detail))))
            else:
                lines.append(TextLine((Span(lead, gutter), *highlight(row, language, theme.code))))
        if omitted:
            lines.append(TextLine((Span(f"{' ' * (CONTENT_INDENT * 2)}{ELLIPSIS} {omitted} more rows", muted),)))
        return lines


class SessionMessagePresenter(ToolPresenter[MessageEntry]):
    """A message the agent sent to another session: what it said, then how it ended.

    Folded, the row shows the first lines of the message and the one-line outcome; expanded, every
    line of the message. The message comes first because it is the substance of the call; the outcome
    (``Delivered to work …``, or why it was not) is a line of its own underneath, in the colour of the
    result — muted when it went, the error colour when it did not.
    """

    entry_type = MessageEntry

    def body_lines(self, entry: MessageEntry, width: int, theme: Theme, muted: Style) -> list[TextLine]:
        """Return the message, bounded as any tool output is, and the outcome under it."""
        if entry.running:
            return []
        inner = max(1, width - CONTENT_INDENT * 2)
        limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
        detail = Style(foreground=theme.subtle)
        gutter = Style(foreground=theme.muted)
        lines: list[TextLine] = []
        rows, omitted = bounded_rows(entry.message, inner, limit) if entry.message else ([], 0)
        for index, row in enumerate(rows):
            lead = f"{' ' * CONTENT_INDENT}\u2514 " if index == 0 else " " * (CONTENT_INDENT * 2)
            lines.append(TextLine((Span(lead, gutter), Span(row, detail))))
        if omitted:
            lines.append(TextLine((Span(f"{' ' * (CONTENT_INDENT * 2)}{ELLIPSIS} {omitted} more rows", muted),)))
        if entry.text:
            ended = Style(foreground=theme.error if entry.status is EntryStatus.FAILED else theme.muted)
            # An arrow, so the answer is not read as the last line of the message above it.
            outcome, more = bounded_rows(entry.text, max(1, inner - 2), 3 if entry.expanded else 1)
            for index, row in enumerate(outcome):
                lead = f"{' ' * CONTENT_INDENT}\u2192 " if index == 0 else " " * (CONTENT_INDENT * 2)
                lines.append(TextLine((Span(f"{lead}{row}", ended),)))
            if more and not entry.expanded:
                lines[-1] = TextLine((Span(f"{lines[-1].text} {ELLIPSIS}", ended),))
        return lines


class ReadPresenter(ToolPresenter[ReadEntry]):
    """A file that was read: the body is highlighted as the language the file is in."""

    entry_type = ReadEntry

    def body_lines(self, entry: ReadEntry, width: int, theme: Theme, muted: Style) -> list[TextLine]:
        """Show the output as source code when the file is."""
        return self.output_lines(entry, width, theme, muted, language=entry.language)


def _change_counts(added: int, removed: int, theme: Theme) -> list[Span]:
    """Return ``+N`` and ``-M`` in the colours an addition and a deletion get; a zero is left out."""
    spans: list[Span] = []
    if added:
        spans.append(Span(f" +{added}", Style(foreground=theme.addition)))
    if removed:
        spans.append(Span(f" -{removed}", Style(foreground=theme.deletion)))
    return spans


class FileChangePresenter(ToolPresenter[F]):
    """A tool that changed a file: the lines it changed beside the name, and the change under it.

    What a write and an edit share. They differ only in whether anything is taken away
    (:meth:`removed`), so the diff, the colours, the cut at the width and the preview limits are
    written once.
    """

    def removed(self, entry: F) -> int:
        """Return the lines the change removes; a change that cannot remove any says none."""
        return 0

    def after_title(self, entry: F, theme: Theme) -> list[Span]:
        """Show how many lines the change adds and removes."""
        return _change_counts(entry.added, self.removed(entry), theme)

    def body_lines(self, entry: F, width: int, theme: Theme, muted: Style) -> list[TextLine]:
        """Show the change once the call has succeeded; before that, and if it failed, the usual body."""
        if not entry.shows_diff:
            return super().body_lines(entry, width, theme, muted)
        return self._diff_lines(entry, width, theme, muted)

    @staticmethod
    def _diff_lines(entry: FileChangeEntry, width: int, theme: Theme, muted: Style) -> list[TextLine]:
        """Draw the change an edit made: additions and deletions in the colours the counts wear.

        A row is cut at the width rather than wrapped, so one long line cannot push the rest of
        the diff off the screen; the break between two edits is drawn quiet, and what is past the
        preview is counted the way a long output's is.
        """
        limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
        room = max(1, width - CONTENT_INDENT * 2 - 2)
        styles = {
            "+": Style(foreground=theme.addition, background=theme.addition_fill),
            "-": Style(foreground=theme.deletion, background=theme.deletion_fill),
            " ": Style(foreground=theme.subtle),
            "@": muted,
        }
        lines: list[TextLine] = []
        for index, (sign, text) in enumerate(entry.diff[:limit]):
            lead = f"{' ' * CONTENT_INDENT}\u2514 " if index == 0 else " " * (CONTENT_INDENT * 2)
            style = styles.get(sign, styles[" "])
            shown = text if sign == "@" else f"{sign} {terminal_safe(text)}"
            cut = truncate(shown, room)
            if style.background is not None:
                # A band runs the width of the row, so a short line is as much a line as a long one.
                cut += " " * max(0, room - display_width(cut))
            lines.append(TextLine((Span(lead, muted), Span(cut, style))))
        omitted = len(entry.diff) - limit
        if omitted > 0:
            lines.append(TextLine((Span(f"{' ' * (CONTENT_INDENT * 2)}{ELLIPSIS} {omitted} more rows", muted),)))
        return lines


class WritePresenter(FileChangePresenter[WriteEntry]):
    """A file that was written whole: every line of it an addition."""

    entry_type = WriteEntry


class EditPresenter(FileChangePresenter[EditEntry]):
    """A file that was edited: the lines added and removed, and the change."""

    entry_type = EditEntry

    def removed(self, entry: EditEntry) -> int:
        """Return the lines the edits remove."""
        return entry.removed


#: Files listed under "Changed N files" before the rest are counted. A request that rewrote forty
#: files has a summary that is a summary, not the list of them.
MAX_CHANGED_ROWS = 8


class ChangesPresenter(Presenter[ChangesEntry]):
    """Say which files a request changed: one line for one file, a short list for several.

    ::

        Changed src/app.py +4 -1

        Changed 3 files
          src/app.py +4 -1
          src/new.py +40
          old.py deleted

    The same colours as the tool rows above it, so a count means the same thing in both places.
    """

    kind = EntryKind.CHANGES

    def lines(self, entry: ChangesEntry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the summary under a blank separator, each row cut at the width."""
        muted = Style(foreground=theme.muted)
        room = max(1, width)
        files = entry.files
        if len(files) == 1:
            return [TextLine(), self._row("Changed ", files[0], theme, muted, room)]
        shown = files[:MAX_CHANGED_ROWS]
        rows = [TextLine(), TextLine((Span(f"Changed {len(files)} files", muted),))]
        rows.extend(self._row("  ", item, theme, muted, room) for item in shown)
        if len(files) > len(shown):
            rows.append(TextLine((Span(f"  {ELLIPSIS} and {len(files) - len(shown)} more", muted),)))
        return rows

    @staticmethod
    def _row(lead: str, item: FileSummary, theme: Theme, muted: Style, room: int) -> TextLine:
        """One file: its name, then what happened to it."""
        counts = (
            [Span(" deleted", Style(foreground=theme.deletion))]
            if item.deleted
            else _change_counts(item.added, item.removed, theme)
        )
        used = display_width(lead) + sum(display_width(span.text) for span in counts)
        name = truncate(item.path, max(1, room - used))
        return TextLine((Span(lead + name, muted), *counts))


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
    """The presenters of one transcript: one for each kind of entry, and for the families inside a kind.

    A presenter is found by the entry's class first, walking up its parents, and by its kind
    second. Most kinds have one presenter and no family (a notice is a notice), and ``tool`` has
    one for tools in general and one for each tool whose entry carries more than the rest.

    When more than one presenter could draw the same rows, the one with the higher
    :attr:`Presenter.priority` wins, and an equal priority goes to the later registration. That is
    what makes a transcript's own presenters the default: they are registered first, at priority 0,
    so anything a plugin registers for the same rows wins without having to outrank them.
    :meth:`replacing` appends, which is the same thing for a caller holding a registry rather than a
    plugin container.

    A presenter for a whole kind is a claim on every row of that kind, so it beats the families
    registered before it at its priority: a plugin that draws every tool row draws every tool row.
    A family registered after it, or at a higher priority, is a refinement and keeps its own.
    """

    def __init__(self, presenters: Iterable[Presenter[Any]]) -> None:
        """Register presenters in order; for one kind or class, the strongest claim wins."""
        self._by_kind: dict[EntryKind, tuple[int, int, Presenter[Any]]] = {}
        self._by_type: dict[type[Entry], tuple[int, int, Presenter[Any]]] = {}
        for order, presenter in enumerate(presenters):
            rank = (presenter.priority, order)
            if presenter.entry_type is not None:
                current = self._by_type.get(presenter.entry_type)
                if current is None or rank >= current[:2]:
                    self._by_type[presenter.entry_type] = (*rank, presenter)
            else:
                current = self._by_kind.get(presenter.kind)
                if current is None or rank >= current[:2]:
                    self._by_kind[presenter.kind] = (*rank, presenter)

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters that draw something: the kinds' first, then the families'.

        A family a kind's presenter has outranked is left out: it would never be asked for a row.
        """
        live = [presenter for _, _, presenter in self._by_kind.values()]
        live.extend(
            presenter
            for priority, order, presenter in self._by_type.values()
            if self._by_kind.get(presenter.kind) is None or (priority, order) > self._by_kind[presenter.kind][:2]
        )
        return tuple(live)

    def replacing(self, *presenters: Presenter[Any]) -> Presenters:
        """Return a registry that draws the given kinds, and families, with the given presenters."""
        return Presenters((*self.presenters, *presenters))

    def for_entry(self, entry: Entry) -> Presenter[Any]:
        """Return the presenter for an entry: the strongest claim on its class or kind, else say so."""
        family: tuple[int, int, Presenter[Any]] | None = None
        for cls in type(entry).__mro__:
            found = self._by_type.get(cls)
            if found is not None:
                family = found
                break
        kind = self._by_kind.get(entry.kind)
        if family is not None and (kind is None or family[:2] > kind[:2]):
            return family[2]
        if kind is None:
            raise ValueError(f"No presenter for a {entry.kind.value} row")
        return kind[2]

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows an entry paints, rendered now and not cached."""
        return self.for_entry(entry).lines(entry, width, theme, frame)

    def block(self, entry: Entry, width: int, theme: Theme, frame: int) -> LineSource:
        """Return an entry's rows as a cached line source, in the gutter's layout."""
        return self.for_entry(entry).block(entry, width, theme, frame, self)


BUILTIN_PRESENTERS: tuple[Presenter[Any], ...] = (
    WelcomePresenter(),
    UserPresenter(),
    NoticePresenter(),
    AnnouncementPresenter(),
    AnswerPresenter(),
    MessagePresenter(),
    WaitPresenter(),
    ThinkingPresenter(),
    ToolPresenter(),
    ChangesPresenter(),
    RelayPresenter(),
    ReadPresenter(),
    WritePresenter(),
    EditPresenter(),
    SessionMessagePresenter(),
)

#: How a transcript draws entries when nothing has registered a presenter: the built-in ones, at the
#: lowest priority, which is also what the built-in plugin registers them with for a real run.
DEFAULT_PRESENTERS = Presenters(BUILTIN_PRESENTERS)


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
