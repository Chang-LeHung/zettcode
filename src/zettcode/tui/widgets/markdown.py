"""Streaming-safe Markdown rendering.

Completed blocks are parsed once and cached; only the still-open trailing block
is re-parsed as text streams in. That keeps a long streamed answer linear in
the number of blocks instead of re-parsing the whole document every frame.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..core.theme import DARK, Theme
from ..layout.scroll import LineSource, ScrollView
from ..render import Canvas, Span, Style, TextLine, highlight, wrap_spans
from ..render.text import display_width

FENCE = "```"
TABLE_GAP = 3
TABLE_MIN_COLUMN = 4
TABLE_MAX_COLUMN = 60
_BLANK = re.compile(r"\n[ \t]*\n")
_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`|\[[^]]+\]\([^)]+\)|(?<!\*)\*[^*]+\*(?!\*)|(?<!_)_[^_]+_(?!_))")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET = re.compile(r"^(\s*)[-+*]\s+(.+)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RULE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")


def stable_cut(text: str) -> int:
    """Return how much of the tail is closed and safe to cache.

    A blank line ends a block, unless it sits inside an unterminated code
    fence, so only boundaries with balanced fences count.
    """
    cut = 0
    for match in _BLANK.finditer(text):
        boundary = match.end()
        if text.count(FENCE, 0, boundary) % 2 == 0:
            cut = boundary
    return cut


def render_markdown(text: str, width: int, theme: Theme = DARK) -> list[TextLine]:
    """Render Markdown source into wrapped, styled lines."""
    if not text:
        return []
    width = max(1, width)
    source = text.split("\n")
    logical: list[TextLine] = []
    index = 0
    in_code = False
    language = ""
    while index < len(source):
        line = source[index]
        stripped = line.strip()
        if stripped.startswith(FENCE):
            if in_code:
                in_code = False
                language = ""
            else:
                in_code = True
                language = stripped[3:].strip()
                if language:
                    logical.append(TextLine((Span(f"  {language}", Style(foreground=theme.muted)),)))
            index += 1
            continue
        if in_code:
            logical.append(TextLine(tuple(code_spans(line, language, theme))))
            index += 1
            continue
        if index + 1 < len(source):
            header = split_table_row(line)
            alignments = table_alignments(source[index + 1])
            if header is not None and alignments is not None and len(header) == len(alignments):
                rows: list[list[str]] = []
                cursor = index + 2
                while cursor < len(source):
                    row = split_table_row(source[cursor])
                    if row is None:
                        break
                    rows.append((row + [""] * len(header))[: len(header)])
                    cursor += 1
                logical.extend(render_table(header, alignments, rows, width, theme))
                index = cursor
                continue
        if _RULE.match(line):
            logical.append(TextLine(rule_spans(width, theme)))
            index += 1
            continue
        rendered = markdown_line(line, theme=theme)
        if rendered is not None:
            logical.append(TextLine(tuple(rendered)))
        index += 1
    result: list[TextLine] = []
    for line in logical:
        result.extend(TextLine(row) for row in wrap_spans(line.spans, width))
    return result


def code_spans(line: str, language: str, theme: Theme) -> list[Span]:
    """Highlight one line of a fenced code block, with no background fill."""
    indent = Span("  ", Style(foreground=theme.code.text))
    return [indent, *highlight(line, language, theme.code)]


def rule_spans(width: int, theme: Theme) -> tuple[Span, ...]:
    """Return one horizontal rule across ``width`` cells.

    A rule is chrome, but it has to stay readable: ``muted`` draws it clearly
    while still holding it below the body text, which is what a rule is for.
    """
    return (Span("\u2500" * max(1, width), Style(foreground=theme.muted)),)


def markdown_line(line: str, *, theme: Theme) -> list[Span] | None:
    """Render one non-code logical line."""
    heading = _HEADING.match(line)
    if heading:
        # Every level keeps the body colour: a dimmed heading read as washed-out
        # text in the answer, and the blank line around it already separates it.
        return inline_markdown(heading.group(2), base=Style(foreground=theme.text, bold=True), theme=theme)

    bullet = _BULLET.match(line)
    if bullet:
        prefix = [Span(f"{bullet.group(1)}\u00b7 ", Style(foreground=theme.text))]
        return prefix + inline_markdown(bullet.group(2), theme=theme)

    quote = _QUOTE.match(line)
    if quote:
        prefix = [Span("\u2502 ", Style(foreground=theme.accent))]
        return prefix + inline_markdown(quote.group(1), base=Style(foreground=theme.subtle), theme=theme)

    return inline_markdown(line, theme=theme)


def inline_markdown(value: str, *, base: Style | None = None, theme: Theme = DARK) -> list[Span]:
    """Render inline emphasis, code, and links.

    Args:
        value: One logical line of inline Markdown.
        base: Style for unmarked text; defaults to the theme's body colour.
        theme: Palette used for the synthesized spans.
    """
    base_style = base if base is not None else Style(foreground=theme.text)
    fragments: list[Span] = []
    position = 0
    for match in _INLINE.finditer(value):
        if match.start() > position:
            fragments.append(Span(value[position : match.start()], base_style))
        token = match.group(0)
        if token.startswith(("**", "__")):
            fragments.append(Span(token[2:-2], replace(base_style, bold=True)))
        elif token.startswith("`"):
            # Colour only: a background block reads as a filled box in a terminal.
            fragments.append(Span(token[1:-1], Style(foreground=theme.code.inline)))
        elif token.startswith("["):
            label, _, target = token[1:].partition("](")
            fragments.append(Span(label, Style(foreground=theme.accent_bright)))
            fragments.append(Span(f" <{target[:-1]}>", Style(foreground=theme.muted)))
        else:
            fragments.append(Span(token[1:-1], replace(base_style, italic=True)))
        position = match.end()
    if position < len(value) or not fragments:
        fragments.append(Span(value[position:], base_style))
    return fragments


def split_table_row(value: str) -> list[str] | None:
    """Split table cells while preserving escaped and inline-code pipes."""
    stripped = value.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False
    for character in stripped:
        if escaped:
            current.append(character if character in ("|", "\\") else f"\\{character}")
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "`":
            in_code = not in_code
            current.append(character)
        elif character == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells if len(cells) >= 2 else None


def table_alignments(value: str) -> list[str] | None:
    """Return the alignment of every column, or None when this is not a rule."""
    cells = split_table_row(value)
    if cells is None:
        return None
    alignments: list[str] = []
    for cell in cells:
        marker = cell.replace(" ", "")
        if re.fullmatch(r":-{3,}:", marker):
            alignments.append("center")
        elif re.fullmatch(r"-{3,}:", marker):
            alignments.append("right")
        elif re.fullmatch(r":?-{3,}", marker):
            alignments.append("left")
        else:
            return None
    return alignments


def render_table(
    header: list[str],
    alignments: list[str],
    rows: list[list[str]],
    width: int,
    theme: Theme,
    *,
    fixed: list[int | None] | None = None,
) -> list[TextLine]:
    """Render a borderless GFM table, wrapping cells rather than cutting them.

    Args:
        header: Header cells, one per column.
        alignments: One ``"left"``, ``"center"``, or ``"right"`` per column.
        rows: Body cells; short rows are padded and long ones truncated.
        width: Total width the table may occupy, in cells.
        theme: Palette used for the cells and the rule.
        fixed: Per-column pinned widths; ``None`` leaves a column at its natural
            width. Columns are dropped from the right when they cannot fit.
    """
    columns = len(header)
    while columns > 1 and columns * (TABLE_MIN_COLUMN + TABLE_GAP) - TABLE_GAP > width:
        columns -= 1
    dropped = len(header) - columns
    header = header[:columns]
    alignments = alignments[:columns]
    rows = [row[:columns] for row in rows]
    if dropped:
        header[-1] = "\u2026"
        rows = [row[:-1] + ["\u2026"] for row in rows]

    widths = table_widths(header, rows)
    for index, value in enumerate((fixed or [])[:columns]):
        if value is not None:
            widths[index] = max(TABLE_MIN_COLUMN, value)
    budget = max(columns * TABLE_MIN_COLUMN, width - TABLE_GAP * (columns - 1))
    while sum(widths) > budget:
        largest = max(range(columns), key=widths.__getitem__)
        if widths[largest] <= TABLE_MIN_COLUMN:
            break
        widths[largest] -= 1

    lines = table_row(
        [wrap_spans(inline_markdown(cell, theme=theme), widths[index]) for index, cell in enumerate(header)],
        widths,
        alignments,
        theme,
        header=True,
    )
    # A table rule is structure, not a page divider: it is drawn per column and
    # one step brighter than the thematic break, which only separates sections.
    rule = (" " * TABLE_GAP).join("\u2500" * width for width in widths)
    lines.append(TextLine((Span(rule, Style(foreground=theme.subtle)),)))
    for row in rows:
        cells = [wrap_spans(inline_markdown(row[index], theme=theme), widths[index]) for index in range(columns)]
        lines.extend(table_row(cells, widths, alignments, theme))
    return lines


def table_widths(header: list[str], rows: list[list[str]]) -> list[int]:
    """Return a natural width per column, capped but far more generous than before."""
    widths: list[int] = []
    for index, cell in enumerate(header):
        values = [cell, *(row[index] for row in rows if index < len(row))]
        natural = max(display_width(plain_inline(value)) for value in values)
        widths.append(max(TABLE_MIN_COLUMN, min(TABLE_MAX_COLUMN, natural)))
    return widths


def table_row(
    cells: list[list[tuple[Span, ...]]],
    widths: list[int],
    alignments: list[str],
    theme: Theme,
    *,
    header: bool = False,
) -> list[TextLine]:
    """Lay wrapped cells into one or more lines, padding each column to its width.

    Args:
        cells: Already-wrapped spans per column.
        widths: Target width per column, in cells.
        alignments: One alignment name per column.
        theme: Palette used for the padding spans.
        header: Draw the row bold.
    """
    base = Style(foreground=theme.text, bold=header)
    height = max((len(cell) for cell in cells), default=1)
    lines: list[TextLine] = []
    for index in range(height):
        spans: list[Span] = []
        for column, width in enumerate(widths):
            if column:
                spans.append(Span(" " * TABLE_GAP, base))
            part = cells[column][index] if index < len(cells[column]) else ()
            used = sum(display_width(span.text) for span in part)
            remaining = max(0, width - used)
            alignment = alignments[column]
            left = remaining if alignment == "right" else remaining // 2 if alignment == "center" else 0
            right = remaining - left
            if left:
                spans.append(Span(" " * left, base))
            spans.extend(part)
            if right and column < len(widths) - 1:
                spans.append(Span(" " * right, base))
        lines.append(TextLine(tuple(spans)))
    return lines


def plain_inline(value: str) -> str:
    """Return the visible text of one inline fragment, with no styling."""
    return "".join(span.text for span in inline_markdown(value))


class Markdown:
    """Incrementally parsed Markdown with per-width line caching."""

    def __init__(self, text: str = "", *, theme: Theme = DARK) -> None:
        """Start from empty caches, optionally parsing ``text`` up front.

        Args:
            text: Initial document; it is appended as if streamed in, so the
                trailing block stays re-parseable.
            theme: Palette used when rendering; the owner refreshes this before
                painting if the theme can change.
        """
        self.theme = theme
        self._text = ""
        self._stable_source = 0
        self._stable: list[TextLine] = []
        self._tail: list[TextLine] = []
        self._width = 0
        self._tail_key: tuple[int, int, int] | None = None
        if text:
            self.append(text)

    @property
    def text(self) -> str:
        """Return the full source appended so far."""
        return self._text

    def set_text(self, text: str) -> None:
        """Replace the document and drop every cached block."""
        self._text = ""
        self._stable_source = 0
        self._stable = []
        self._tail = []
        self._tail_key = None
        self.append(text)

    def append(self, delta: str) -> None:
        """Append streamed text, invalidating only the still-open tail."""
        if not delta:
            return
        self._text += delta
        self._tail_key = None

    def lines(self, width: int) -> list[TextLine]:
        """Return every rendered line for ``width``."""
        self._sync(max(1, width))
        return [*self._stable, *self._tail]

    def line_count(self, width: int) -> int:
        """Return how many lines the document occupies at ``width``."""
        self._sync(max(1, width))
        return len(self._stable) + len(self._tail)

    def line_at(self, index: int, width: int) -> TextLine:
        """Return one line, reading from the stable blocks or from the open tail."""
        self._sync(max(1, width))
        if 0 <= index < len(self._stable):
            return self._stable[index]
        return self._tail[index - len(self._stable)]

    @property
    def stable_line_count(self) -> int:
        """Return how many lines are already closed and safely cached."""
        return len(self._stable)

    def _sync(self, width: int) -> None:
        """Re-render only what changed since the last call at this width."""
        if width != self._width:
            self._width = width
            self._stable = []
            self._stable_source = 0
            self._tail_key = None
        cut = stable_cut(self._text[self._stable_source :])
        if cut > 0:
            tail = self._text[self._stable_source : self._stable_source + cut]
            self._stable.extend(render_markdown(tail, self._width, self.theme))
            self._stable_source += cut
            self._tail_key = None
        key = (len(self._text), self._stable_source, self._width)
        if key != self._tail_key:
            self._tail = render_markdown(self._text[self._stable_source :], self._width, self.theme)
            self._tail_key = key


class MarkdownSource(LineSource):
    """LineSource adapter so Markdown composes with ScrollView."""

    def __init__(self, markdown: Markdown) -> None:
        """Wrap one Markdown document."""
        self.markdown = markdown

    def count(self, width: int) -> int:
        """Return the document's line count at this width."""
        return self.markdown.line_count(width)

    def line(self, index: int, width: int) -> TextLine:
        """Return one rendered line of the document."""
        return self.markdown.line_at(index, width)


class MarkdownView(ScrollView):
    """A scrollable Markdown document that follows the tail while streaming.

    Shape::

        Heading                            <- bold, dimmed by level
        prose with bold, code, and links   <- inline styles
        . bullet                           <- bullet prefix
        | quote                            <- accent bar
          python                           <- fence label, muted
          def add(a, b):                   <- highlighted code

    Parsing is incremental: closed blocks are parsed once and cached, and only
    the still-open tail is re-parsed as text streams in, so a long answer stays
    linear in the number of blocks rather than the number of frames.
    """

    def __init__(self, text: str = "", *, follow_tail: bool = True, focusable: bool = False) -> None:
        """Scroll a document that follows the tail while text streams in.

        Args:
            text: Initial document.
            follow_tail: Keep the newest line visible until the reader scrolls up.
            focusable: Allow Tab traversal to land on the view so its keys work.
        """
        self.markdown = Markdown(text)
        self.markdown_source = MarkdownSource(self.markdown)
        super().__init__(self.markdown_source, follow_tail=follow_tail, focusable=focusable, selectable=True)

    def set_text(self, text: str) -> None:
        """Replace the document and repaint."""
        self.markdown.set_text(text)
        self.invalidate()

    def append(self, delta: str) -> None:
        """Append streamed text and repaint."""
        self.markdown.append(delta)
        self.invalidate()

    def render(self, canvas: Canvas) -> None:
        """Adopt the active theme before painting the document."""
        self.markdown.theme = self.theme
        super().render(canvas)
