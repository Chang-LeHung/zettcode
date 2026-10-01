"""The transcript model and the virtualized view that renders it."""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import monotonic

from ..tui_framework import (
    Canvas,
    Host,
    Markdown,
    MouseAction,
    MouseEvent,
    ScrollView,
    Span,
    StaticLines,
    Style,
    TextLine,
    Theme,
)
from ..tui_framework.render import truncate, wrap_columns
from ..tui_framework.widgets.markdown import MarkdownSource

MAX_TOOL_OUTPUT = 64_000
TOOL_PREVIEW_ROWS = 5
TOOL_EXPANDED_ROWS = 40

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def terminal_safe(value: str) -> str:
    """Strip escape sequences and replace characters the canvas cannot paint.

    Args:
        value: Raw tool output; newlines survive, tabs become four spaces, and
            anything non-printable becomes the replacement character so a tool
            cannot smuggle control codes into the canvas.
    """
    cleaned = _ANSI.sub("", value).expandtabs(4)
    return "".join(
        character if character in "\n" else character if character.isprintable() else "\ufffd" for character in cleaned
    )


def bounded_rows(value: str, width: int, limit: int) -> tuple[list[str], int]:
    """Wrap tool output and return a bounded viewport plus omitted rows.

    Args:
        value: Raw tool output.
        width: Wrap width in cells.
        limit: Most rows to return; the remainder is reported as omitted.
    """
    rows: list[str] = []
    for source in terminal_safe(value).splitlines() or [""]:
        rows.extend(wrap_columns(source, width))
    omitted = max(0, len(rows) - limit)
    return rows[:limit], omitted


def limit_output(value: str) -> str:
    """Bound stored tool output while keeping both ends useful.

    Args:
        value: Raw tool output; anything past ``MAX_TOOL_OUTPUT`` keeps its head
            and tail with a marker in between, so a huge result cannot dominate
            memory while still showing how it started and ended.
    """
    if len(value) <= MAX_TOOL_OUTPUT:
        return value
    half = MAX_TOOL_OUTPUT // 2
    omitted = len(value) - half * 2
    return f"{value[:half]}\n\u2026 {omitted:,} characters omitted \u2026\n{value[-half:]}"


def arguments_preview(arguments: Mapping[str, object], *, limit: int = 90) -> str:
    """Render tool arguments as a single inline preview, truncated to ``limit``.

    Args:
        arguments: Tool arguments; JSON-encoded on one line.
        limit: Most characters to show, ellipsis included. The result is prefixed
            with a space so it can be concatenated onto a tool name directly.
    """
    if not arguments:
        return ""
    value = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    return f" {value if len(value) <= limit else value[: limit - 1] + '\u2026'}"


def duration_text(seconds: float | None) -> str:
    """Format an elapsed time for a row header, switching units at one second.

    Args:
        seconds: Elapsed time, or ``None`` for a row that has already finished
            without a recorded duration.
    """
    if seconds is None:
        return "done"
    return f"{round(seconds * 1000)} ms" if seconds < 1 else f"{seconds:.1f} s"


@dataclass(slots=True)
class Entry:
    """One semantic block of the conversation, in agent event order.

    Attributes:
        id: Monotonic id, also the handle used to toggle the entry.
        kind: Which renderer applies: ``welcome``, ``notice``, ``user``,
            ``pending``, ``thinking``, ``answer``, or ``tool``.
        text: Body text; for a tool row it is the (bounded) output.
        title: Row label, such as the tool name.
        detail: Inline suffix after the title, usually the argument preview.
        status: ``running``, ``completed``, ``failed``, or ``skipped``; only a
            running row animates and only a finished row can be toggled.
        call_id: Links a tool row to the call it answers.
        expanded: Disclosure state of a thinking or tool row.
        started_at: Clock reading when the row opened, used for the elapsed time.
        duration: Seconds between ``started_at`` and completion, filled in as the
            row runs so a long step shows progress.
        markdown: Streaming source for an answer row; answers are parsed
            incrementally instead of re-rendering on every delta.
        block: Cached rendered block for non-markdown rows.
        block_key: Inputs the cached block was rendered from, so a cache hit
            never shows stale content.
    """

    id: int
    kind: str
    text: str = ""
    title: str = ""
    detail: str = ""
    status: str = ""
    call_id: str = ""
    expanded: bool = False
    started_at: float | None = None
    duration: float | None = None
    markdown: Markdown | None = None
    block: object | None = None
    block_key: tuple[object, ...] | None = None

    def block_for(self, width: int, theme: Theme, frame: int) -> object:
        """Return this entry as a line source, re-rendering only on a real change.

        Args:
            width: Wrap width in cells; part of the cache key.
            theme: Palette; the theme name is part of the cache key.
            frame: Animation frame; only a running row includes it in the cache
                key, so a finished row is never re-rendered as the clock moves.
        """
        if self.markdown is not None:
            self.markdown.theme = theme
            if self.block is None:
                self.block = LeadingGap(MarkdownSource(self.markdown))
            return self.block
        # Only a running row animates, so a completed row must not be re-rendered
        # just because the frame counter moved on.
        animated = frame if self.status == "running" else 0
        key: tuple[object, ...] = (
            width,
            theme.name,
            animated,
            self.expanded,
            self.status,
            len(self.text),
            self.detail,
        )
        if self.block is None or self.block_key != key:
            self.block = StaticLines(render_entry(self, width, theme, frame))
            self.block_key = key
        return self.block


class Transcript:
    """Own the conversation entries and their rendered block boundaries."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        """Start an empty transcript whose elapsed times come from ``clock``.

        Args:
            clock: Time source for row durations, injectable for tests.
        """
        self.entries: list[Entry] = []
        self.clock = clock
        self.version = 0
        self.frame = 0
        self._next_id = 1

    def _add(self, kind: str, **values: object) -> Entry:
        """Append one entry, assigning its id and invalidating rendered caches."""
        entry = Entry(self._next_id, kind, **values)
        self._next_id += 1
        self.entries.append(entry)
        self.version += 1
        return entry

    def _last(self, kind: str) -> Entry | None:
        """Return the newest entry of one kind, or None when there is none."""
        return next((entry for entry in reversed(self.entries) if entry.kind == kind), None)

    def entry(self, entry_id: int) -> Entry | None:
        """Return the entry with this id, or None when it has been cleared."""
        return next((item for item in self.entries if item.id == entry_id), None)

    def clear(self) -> None:
        """Drop every entry, for instance when starting a new session."""
        self.entries.clear()
        self.version += 1

    def advance_frame(self) -> None:
        """Move the activity animation on so running rows repaint."""
        self.frame += 1
        for entry in self.entries:
            if entry.status == "running" and entry.started_at is not None:
                entry.duration = self.clock() - entry.started_at
        self.version += 1

    def notice(self, text: str) -> None:
        """Append a muted one-off status line."""
        self._add("notice", text=text)

    def welcome(self, text: str) -> None:
        """Append the banner shown once at startup."""
        self._add("welcome", text=text)

    def begin_turn(self, prompt: str) -> None:
        """Record the user prompt and open a placeholder for the reply."""
        self._add("user", text=prompt)
        # Nothing is known about the response yet, and the first token can take
        # seconds, so a live placeholder goes up immediately.
        self._add("pending", title="Waiting for the model\u2026", status="running", started_at=self.clock())

    def start_thinking(self) -> Entry:
        """Return the open thinking block, promoting the placeholder when it fits."""
        current = self._last("thinking")
        if current is not None and current.status == "running":
            return current
        pending = self._last("pending")
        if pending is not None:
            # The placeholder turned out to be reasoning: keep the same row.
            pending.kind = "thinking"
            pending.title = "Thinking"
            pending.started_at = self.clock()
            self.version += 1
            return pending
        return self._add("thinking", title="Thinking", status="running", started_at=self.clock())

    def drop_pending(self) -> bool:
        """Remove the placeholder once real output has started."""
        if self.entries and self.entries[-1].kind == "pending":
            self.entries.pop()
            self.version += 1
            return True
        return False

    def append_thinking(self, delta: str) -> None:
        """Append a reasoning delta to the running thinking block."""
        entry = self.start_thinking()
        entry.text += delta
        self.version += 1

    def complete_thinking(self) -> None:
        """Close the running thinking block and stamp its elapsed time."""
        entry = self._last("thinking")
        if entry is None or entry.status != "running":
            self.drop_pending()
            return
        entry.status = "completed"
        if entry.started_at is not None:
            entry.duration = self.clock() - entry.started_at
        self.version += 1

    def append_answer(self, delta: str) -> None:
        """Stream a delta into the trailing answer block, opening one if needed."""
        self.drop_pending()
        current = self.entries[-1] if self.entries else None
        if current is None or current.kind != "answer":
            current = self._add("answer", markdown=Markdown())
        assert current.markdown is not None
        current.markdown.append(delta)
        current.text += delta
        self.version += 1

    def start_tool(self, call_id: str, name: str, arguments: Mapping[str, object]) -> None:
        """Open a tool row, closing any reasoning or placeholder row first.

        Args:
            call_id: Identifier the matching result will carry.
            name: Tool name shown in the row label.
            arguments: Arguments shown as a short inline preview.
        """
        self.complete_thinking()
        self.drop_pending()
        self._add(
            "tool",
            call_id=call_id,
            title=name,
            detail=arguments_preview(arguments),
            status="running",
            started_at=self.clock(),
        )

    def complete_tool(self, call_id: str, output: str, *, status: str = "completed") -> None:
        """Attach a tool result to its row, ignoring calls that are no longer on screen.

        Args:
            call_id: Identifier from the matching ``start_tool`` call.
            output: Raw output; bounded before it is stored.
            status: Final status, normally ``completed``, ``failed``, or
                ``skipped``.
        """
        entry = next((item for item in reversed(self.entries) if item.kind == "tool" and item.call_id == call_id), None)
        if entry is None:
            return
        entry.text = limit_output(output)
        entry.status = status
        if entry.started_at is not None:
            entry.duration = self.clock() - entry.started_at
        self.version += 1

    def toggle(self, entry_id: int) -> bool:
        """Expand or collapse one collapsible entry and report whether it changed.

        Args:
            entry_id: Id from the click or key that triggered the toggle; a
                running or empty tool row refuses to expand.
        """
        entry = self.entry(entry_id)
        if entry is None or entry.kind not in ("thinking", "tool"):
            return False
        if entry.kind == "tool" and (entry.status == "running" or not entry.text):
            return False
        entry.expanded = not entry.expanded
        self.version += 1
        return True

    def toggle_latest_thinking(self) -> bool:
        """Expand or collapse the newest thinking block."""
        entry = self._last("thinking")
        if entry is None:
            return False
        entry.expanded = not entry.expanded
        self.version += 1
        return True

    def collapse_thinking_except(self, entry_id: int | None) -> bool:
        """Collapse every expanded thinking block except the one to keep open.

        Args:
            entry_id: Block to leave expanded, or ``None`` to collapse them all.
        """
        changed = False
        for entry in self.entries:
            if entry.kind == "thinking" and entry.expanded and entry.id != entry_id:
                entry.expanded = False
                changed = True
        if changed:
            self.version += 1
        return changed


class TranscriptSource:
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


class LeadingGap:
    """LineSource that renders one blank row before a nested source.

    Streamed answers are served by ``Markdown`` so their parsing stays
    incremental, which means the separating blank line cannot come from the
    generic entry renderer.
    """

    def __init__(self, source: object) -> None:
        """Wrap the nested line source.

        Args:
            source: Line source whose rows shift down by one.
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


class TranscriptView(ScrollView):
    """Scrollable transcript that toggles entries when they are clicked."""

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


def render_entry(entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
    """Render one non-streaming entry into terminal lines.

    Args:
        entry: Entry to render; answer rows are excluded because they are served
            by ``Markdown`` instead.
        width: Wrap width in cells.
        theme: Palette to draw with.
        frame: Animation frame, used for running rows only.
    """
    match entry.kind:
        case "welcome":
            return [TextLine((Span(line, Style(foreground=theme.subtle)),)) for line in entry.text.split("\n")]
        case "notice":
            return [
                TextLine(),
                *[TextLine((Span(f"  {line}", Style(foreground=theme.muted)),)) for line in entry.text.split("\n")],
            ]
        case "user":
            prompt = entry.text.split("\n")
            lines = [TextLine(), TextLine((Span(f"\u276f {prompt[0]}", Style(foreground=theme.text, bold=True)),))]
            lines.extend(TextLine((Span(f"  {line}", Style(foreground=theme.text, bold=True)),)) for line in prompt[1:])
            return lines
        case "thinking":
            return _thinking_lines(entry, width, theme, frame)
        case "pending":
            label = f"{activity_glyph(frame)} {entry.title}"
            if entry.duration is not None and entry.duration >= 1:
                label += f"  {duration_text(entry.duration)}"
            return [TextLine(), TextLine((Span(label, Style(foreground=theme.accent, bold=True)),))]
        case "tool":
            return _tool_lines(entry, width, theme, frame)
        case _:
            return [TextLine((Span(line, Style(foreground=theme.subtle)),)) for line in entry.text.split("\n")]


def _thinking_lines(entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
    """Render a thinking row, wrapping its body only while it is expanded.

    Args:
        entry: Thinking entry; its body is wrapped at ``width - 4`` for the
            indent, or shown as a waiting message while it is still empty.
        width: Row width in cells.
        theme: Palette to draw with.
        frame: Animation frame used for the running marker.
    """
    running = entry.status == "running"
    marker = activity_glyph(frame) if running else ("\u25be" if entry.expanded else "\u25b8")
    timing = duration_text(entry.duration) if entry.duration is not None else "working"
    header = Style(foreground=theme.accent, bold=True)
    lines = [TextLine(), TextLine((Span(f"{marker} Thinking  {timing}", header),))]
    if entry.expanded:
        body = Style(foreground=theme.subtle)
        for row in entry.text.splitlines() or ["Waiting for reasoning\u2026"]:
            lines.extend(TextLine((Span(f"    {chunk}", body),)) for chunk in wrap_columns(row, max(8, width - 4)))
    return lines


def _tool_lines(entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
    """Render a tool row with a preview or expanded view of its output.

    Args:
        entry: Tool entry; its output is cut to ``TOOL_PREVIEW_ROWS`` unless the
            row is expanded, which raises the budget to ``TOOL_EXPANDED_ROWS``.
        width: Row width in cells.
        theme: Palette to draw with; a failed row switches to the error colour.
        frame: Animation frame used for the running marker.
    """
    running = entry.status == "running"
    symbol = (
        activity_glyph(frame)
        if running
        else {"completed": "\u2713", "failed": "\u00d7", "skipped": "\u2013"}.get(entry.status, "\u25cf")
    )
    timing = f"  {duration_text(entry.duration)}" if entry.duration is not None else ""
    style = (
        Style(foreground=theme.error, bold=True)
        if entry.status == "failed"
        else Style(foreground=theme.accent, bold=True)
    )
    disclosure = "" if running or not entry.text else (" \u25be" if entry.expanded else " \u25b8")
    label = truncate(f"{symbol} {entry.title}{entry.detail}{timing}{disclosure}", width)
    lines = [TextLine(), TextLine((Span(label, style),))]
    output = "Running\u2026" if running else entry.text
    if output:
        limit = TOOL_EXPANDED_ROWS if entry.expanded else TOOL_PREVIEW_ROWS
        rows, omitted = bounded_rows(output, max(8, width - 6), limit)
        detail = Style(foreground=theme.subtle)
        lines.append(TextLine((Span(f"    \u2514 {rows[0]}", detail),)))
        lines.extend(TextLine((Span(f"      {row}", detail),)) for row in rows[1:])
        if omitted:
            lines.append(TextLine((Span(f"      \u2026 {omitted} more rows", Style(foreground=theme.muted)),)))
    return lines


def activity_glyph(frame: int) -> str:
    """Return the animated glyph shared by every running row.

    Args:
        frame: Monotonic frame counter; the glyph changes every third frame so
            all running rows animate in step.
    """
    return ("\u2726", "\u2727", "\u00b7", "\u2727")[(frame // 3) % 4]
