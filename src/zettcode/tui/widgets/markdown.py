"""Streaming-safe Markdown rendering.

Completed blocks are parsed once and cached; only the still-open trailing block
is re-parsed as text streams in. That keeps a long streamed answer linear in
the number of blocks instead of re-parsing the whole document every frame.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from ...tui import ELLIPSIS, RULE, SEPARATOR
from ..core.theme import DARK, Theme
from ..layout.scroll import LineSource, ScrollView
from ..render import Canvas, Span, Style, TextLine, highlight, layout_rich_lines, wrap_spans
from ..render.text import display_width

FENCE = "```"
TABLE_GAP = 3
TABLE_MIN_COLUMN = 4
TABLE_MAX_COLUMN = 60
#: Columns a list item is inset by, relative to the prose above it, so a list
#: reads as content under its heading instead of another paragraph.
LIST_INDENT = 2
_BLANK = re.compile(r"\n[ \t]*\n")
# Underscore emphasis needs a word boundary on both sides, as CommonMark does:
# otherwise ``replace_in_file`` would lose the underscores that spell it.
# A code span is opened by a run of backticks and closed by the same run, so
# ````` `a`-`b` ````` can hold backticks of its own; the run must not touch a
# longer run on either side, which is what the lookarounds check.
_CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
#: Inline markup other than code; code spans are matched first and hidden from
#: this pattern, so ``**a `b` c**`` keeps its code span instead of letting the
#: emphasis delimiters swallow the backticks.
_INLINE = re.compile(
    r"(~~.+?~~|\*\*.+?\*\*|__.+?__|\[[^]]+\]\([^)]+\)|(?<!\*)\*[^*]+\*(?!\*)|(?<![\w_])_[^_\n]+_(?![\w_]))"
)
#: Stands in for one code span while the rest of the line is matched.
_CODE_MARK_TEXT = "\x00code{}\x00"
_CODE_MARK = re.compile(r"\x00code(\d+)\x00")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET = re.compile(r"^(\s*)[-+*]\s+(.+)$")
_ORDERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.+)$")
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
                # The fence label picks the scanner; it is not part of the code
                # and is never drawn, so a block starts straight at its text.
                language = stripped[3:].strip()
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
            logical.append(rendered)
        index += 1
    return list(layout_rich_lines(logical, width))


def code_spans(line: str, language: str, theme: Theme) -> list[Span]:
    """Highlight one line of a fenced code block, with no background fill."""
    indent = Span("  ", Style(foreground=theme.code.text))
    return [indent, *highlight(line, language, theme.code)]


def rule_spans(width: int, theme: Theme) -> tuple[Span, ...]:
    """Return one horizontal rule across ``width`` cells.

    A rule is chrome, but it has to stay readable: ``muted`` draws it clearly
    while still holding it below the body text, which is what a rule is for.
    """
    return (Span(RULE * max(1, width), Style(foreground=theme.muted)),)


def markdown_line(line: str, *, theme: Theme) -> TextLine | None:
    """Render one non-code logical line.

    The returned line's metadata carries the indent its wrapped rows should
    keep, which is how a list item stays aligned under its own text.
    """
    heading = _HEADING.match(line)
    if heading:
        # Every level keeps the body colour: a dimmed heading read as washed-out
        # text in the answer, and the blank line around it already separates it.
        return TextLine(
            tuple(inline_markdown(heading.group(2), base=Style(foreground=theme.text, bold=True), theme=theme))
        )

    bullet = _BULLET.match(line)
    if bullet:
        return list_item(f"{bullet.group(1)}{SEPARATOR} ", bullet.group(2), theme=theme)

    ordered = _ORDERED.match(line)
    if ordered:
        return list_item(f"{ordered.group(1)}{ordered.group(2)}. ", ordered.group(3), theme=theme)

    quote = _QUOTE.match(line)
    if quote:
        prefix = [Span("\u2502 ", Style(foreground=theme.accent))]
        return TextLine(
            tuple(prefix + inline_markdown(quote.group(1), base=Style(foreground=theme.subtle), theme=theme))
        )

    return TextLine(tuple(inline_markdown(line, theme=theme)))


def list_item(marker: str, body: str, *, theme: Theme) -> TextLine:
    """Return one list item, inset under the prose and wrapping under its text.

    Args:
        marker: The item's own marker, already carrying any source indent.
        body: Item text, rendered with the inline rules.
        theme: Palette used for the marker and the body.
    """
    prefix = " " * LIST_INDENT + marker
    spans = (Span(prefix, Style(foreground=theme.text)), *inline_markdown(body, theme=theme))
    return TextLine(spans, metadata=display_width(prefix))


def inline_markdown(value: str, *, base: Style | None = None, theme: Theme = DARK) -> list[Span]:
    """Render inline emphasis, code, and links.

    Code spans are recognised before anything else and stand in for themselves
    while emphasis and links are matched, which is the order CommonMark
    resolves them in: a code span is atomic, so the delimiters around it cannot
    reach inside.

    Args:
        value: One logical line of inline Markdown.
        base: Style for unmarked text; defaults to the theme's body colour.
        theme: Palette used for the synthesized spans.
    """
    base_style = base if base is not None else Style(foreground=theme.text)
    code: list[Span] = []

    def hide(match: re.Match[str]) -> str:
        # CommonMark strips one space on each side of the run, and only when the
        # span is not all spaces, so `` ` ` `` keeps its single space.
        content = match.group(2)
        if content.startswith(" ") and content.endswith(" ") and content.strip():
            content = content[1:-1]
        code.append(Span(content, Style(foreground=theme.code.inline)))
        return _CODE_MARK_TEXT.format(len(code) - 1)

    masked = _CODE.sub(hide, value)
    fragments: list[Span] = []
    position = 0
    for match in _INLINE.finditer(masked):
        if match.start() > position:
            fragments.append(Span(masked[position : match.start()], base_style))
        token = match.group(0)
        if token.startswith("~~"):
            fragments.extend(nested(token[2:-2], replace(base_style, strike=True), theme, code))
        elif token.startswith(("**", "__")):
            fragments.extend(nested(token[2:-2], replace(base_style, bold=True), theme, code))
        elif token.startswith("["):
            label, _, target = token[1:].partition("](")
            fragments.extend(nested(label, Style(foreground=theme.accent_bright), theme, code))
            fragments.append(Span(f" <{target[:-1]}>", Style(foreground=theme.muted)))
        else:
            fragments.extend(nested(token[1:-1], replace(base_style, italic=True), theme, code))
        position = match.end()
    if position < len(masked) or not fragments:
        fragments.append(Span(masked[position:], base_style))
    return reveal(fragments, code)


def nested(text: str, base: Style, theme: Theme, code: Sequence[Span]) -> list[Span]:
    """Render the inside of one inline token, so markup can nest.

    The content is always two characters shorter than the token it came from,
    which is what keeps this recursion finite. A code span inside the token
    already stands behind a placeholder, so it is put back here and never
    reaches the nested call, which knows nothing of this line's code spans.
    """
    pieces: list[Span] = []
    cursor = 0
    for match in _CODE_MARK.finditer(text):
        pieces.extend(inline_markdown(text[cursor : match.start()], base=base, theme=theme))
        pieces.append(code[int(match.group(1))])
        cursor = match.end()
    pieces.extend(inline_markdown(text[cursor:], base=base, theme=theme))
    return pieces


def reveal(fragments: Sequence[Span], code: Sequence[Span]) -> list[Span]:
    """Put the code spans back where their placeholders ended up.

    A placeholder can sit inside bold or italic text, so the host span is split
    around it and keeps its own style; the code span keeps the code colour.
    """
    revealed: list[Span] = []
    for fragment in fragments:
        cursor = 0
        for match in _CODE_MARK.finditer(fragment.text):
            if match.start() > cursor:
                revealed.append(Span(fragment.text[cursor : match.start()], fragment.style))
            revealed.append(code[int(match.group(1))])
            cursor = match.end()
        if cursor < len(fragment.text):
            revealed.append(Span(fragment.text[cursor:], fragment.style))
    return revealed


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
        header[-1] = ELLIPSIS
        rows = [row[:-1] + [ELLIPSIS] for row in rows]

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
    lines.append(table_rule(widths, theme))
    for row in rows:
        cells = [wrap_spans(inline_markdown(row[index], theme=theme), widths[index]) for index in range(columns)]
        lines.extend(table_row(cells, widths, alignments, theme))
        lines.append(table_rule(widths, theme))
    return lines


def table_rule(widths: Sequence[int], theme: Theme) -> TextLine:
    """Return the line under a table's header or one of its rows.

    A table rule is structure, not a page divider: it is drawn per column, one
    segment per column width, and one step brighter than the thematic break that
    only separates sections. Every row is closed by one, so wrapped cells never
    look like they belong to the row above.
    """
    segments = (" " * TABLE_GAP).join(RULE * width for width in widths)
    return TextLine((Span(segments, Style(foreground=theme.subtle)),))


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
        self._theme = theme
        self._tail_key: tuple[int, int, int, Theme] | None = None
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
        """Re-render only what changed since the last call at this width and theme.

        The palette is part of the cache key: switching themes keeps the same
        text and width, so a cache that ignored it would keep painting the old
        colours until the document changed.
        """
        if width != self._width or self.theme != self._theme:
            self._width = width
            self._theme = self.theme
            self._stable = []
            self._stable_source = 0
            self._tail_key = None
        cut = stable_cut(self._text[self._stable_source :])
        if cut > 0:
            tail = self._text[self._stable_source : self._stable_source + cut]
            self._stable.extend(render_markdown(tail, self._width, self.theme))
            self._stable_source += cut
            self._tail_key = None
        key = (len(self._text), self._stable_source, self._width, self.theme)
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
