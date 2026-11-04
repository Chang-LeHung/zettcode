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

from typing import Any, TypeVar

from zettcode.plugin_api.entries import (
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
from zettcode.plugin_api.presenters import CONTENT_INDENT, Indented, LeadingGap, Presenter, Presenters
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
)
from zettcode.tui.widgets.markdown import MarkdownSource

from .brand import LOGO_LINES
from .pulse import RUNNING_GLYPHS, WAIT_RAMP, moving, sweep_column
from .text import (
    COMPACTING_LABEL,
    STOP_HINT,
    TOOL_EXPANDED_ROWS,
    TOOL_PREVIEW_ROWS,
    bounded_rows,
    duration_text,
    elapsed_text,
    pack_segments,
    quiet_text,
    terminal_safe,
    tip_text,
)

#: Columns a tip's text is inset by: the same two the tools' results use for their hook.
TIP_INDENT = 2

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
    "web_search": "web-search",
    "ask_user": "ask-user",
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
    """Return the colour one tool paints its rows with.

    A role spelled with a hyphen (``web-search``) names the theme field it stands for (``web_search``).
    """
    role = TOOL_ROLES.get(tool, "").replace("-", "_")
    return getattr(theme.tools, role, theme.accent)


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
            if entry.group:
                # A group message is read by every member: say so in the header, where a one-to-one message has nothing.
                label += f" in #{terminal_safe(entry.group)}"
                detail = f" {SEPARATOR} to the whole group"

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
            ink = Style(foreground=theme.muted)
            room = max(1, width - CONTENT_INDENT)
            packed = pack_segments(list(entry.parts) or settled.split(f" {SEPARATOR} "), room)
            return [
                TextLine(),
                *(
                    layout_rich_lines((TextLine((Span(" " * CONTENT_INDENT + row, ink),)),), width, wrap=False)[0]
                    for row in packed
                ),
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
        # A failure is the error colour, and a row that did not happen at all — a skipped tool, a cancelled
        # question — is a caution rather than a result, so it is amber and not the tool's own hue.
        colour = {
            EntryStatus.FAILED: theme.error,
            EntryStatus.SKIPPED: theme.warning,
        }.get(entry.status, hue)
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
    """A file that was read: the body is highlighted as the language the file is in, and the row says how much."""

    entry_type = ReadEntry

    def after_title(self, entry: ReadEntry, theme: Theme) -> list[Span]:
        """Say how many lines came back, beside the title rather than inside it.

        A field of the row survives what a title does not: `restate_tool` rewrites the title from the arguments, and
        the count is drawn from the entry, the way an edit's ``+N -N`` is. A row too narrow for the title and the
        count together cuts the count, as it cuts any tail — an edit's counts go the same way.
        """
        if entry.lines is None:
            return []
        return [Span(f" \u00b7 {entry.lines} line" + ("" if entry.lines == 1 else "s"), Style(foreground=theme.subtle))]

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
