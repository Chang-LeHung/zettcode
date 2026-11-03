"""Unicode-aware text measurement, wrapping, and clamping."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from wcwidth import wcwidth

from .style import Span, Style

ELLIPSIS = "…"


def cell_glyph(character: str) -> tuple[str, int]:
    """Return the paintable glyph and the columns it occupies.

    Combining marks stay zero-width. Control characters cannot be painted
    safely, so they are replaced by a single-column placeholder rather than
    being allowed to reach the terminal as an escape.
    """
    width = wcwidth(character)
    if width < 0:
        return "�", 1
    return character, width


@lru_cache(maxsize=1 << 16)
def character_width(character: str) -> int:
    """Return the columns one character occupies on screen.

    Remembered, because the same few thousand characters make up almost all of the
    text a terminal shows, and a cache hit is answered without running any Python:
    measuring a screenful of Chinese is a hundred thousand of these.
    """
    return cell_glyph(character)[1]


def display_width(text: str) -> int:
    """Return the columns a string occupies, counting wide glyphs as two."""
    if text.isascii() and text.isprintable():
        # Printable ASCII is one column a character, and it is nearly all of what a
        # terminal shows; measuring it one character at a time is the cost this skips.
        return len(text)
    return sum(map(character_width, text))


def slice_columns(text: str, start: int, end: int) -> str:
    """Return the characters overlapping the half-open column range.

    Args:
        text: Source string measured in display columns, not code points.
        start: First column to include.
        end: Column to stop before; a wide glyph is kept when it overlaps the
            range at all, so the result can be one column wider than requested.
    """
    output: list[str] = []
    column = 0
    for character in text:
        width = character_width(character)
        if column >= end:
            break
        if column + width > start:
            output.append(character)
        column += width
    return "".join(output)


def truncate(text: str, width: int, *, ellipsis: str = ELLIPSIS) -> str:
    """Clamp text to a column budget, reserving room for the ellipsis.

    Args:
        text: Source string.
        width: Column budget; zero or less yields an empty string.
        ellipsis: Suffix appended when text is cut; dropped when it would not
            itself fit in ``width``.
    """
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    suffix = ellipsis if display_width(ellipsis) <= width else ""
    # A wide glyph that straddles the cut is left out rather than kept whole: the budget is the budget,
    # and a result one column over it shifts every column after it on that line (which is what made a
    # truncated CJK title push a table's columns out by one).
    remaining = width - display_width(suffix)
    kept: list[str] = []
    used = 0
    for character in text:
        size = character_width(character)
        if used + size > remaining:
            break
        kept.append(character)
        used += size
    return "".join(kept) + suffix


def truncate_spans(spans: Sequence[Span], width: int) -> tuple[Span, ...]:
    """Clamp styled fragments to a column budget, marking overflow with an ellipsis.

    The styles travel with the characters they were attached to, so a clipped
    line keeps every colour it had up to the cut and the ellipsis wears the last
    surviving style.

    Args:
        spans: Fragments in paint order.
        width: Column budget; the ellipsis is carved out of it.
    """
    if width <= 0:
        return ()
    if sum(span.width for span in spans) <= width:
        return tuple(spans)
    remaining = max(0, width - 1)
    clipped: list[Span] = []
    for span in spans:
        text = ""
        for character in span.text:
            size = character_width(character)
            if size > remaining:
                break
            text += character
            remaining -= size
        if text:
            clipped.append(Span(text, span.style))
        if remaining == 0 or len(text) < len(span.text):
            break
    style = clipped[-1].style if clipped else spans[0].style if spans else Style()
    clipped.append(Span(ELLIPSIS, style))
    return tuple(clipped)


def wrap_words(text: str, width: int) -> list[str]:
    """Wrap one logical line of prose at a column budget, breaking between words where it can.

    A word that fits a row is never split: it moves to the next row whole, and the space it was set
    off by is dropped at the break rather than starting a row with a gap. A word wider than a row of
    its own — a long path, an address, text with no spaces at all — is broken at the budget, never
    mid-character, because there is nowhere kinder to break it. Leading space is kept on the first row,
    and a run of spaces inside a line that has to wrap becomes one.

    This is for sentences; code and command output keep :func:`wrap_columns`, where a column is a
    column and a space is a character to preserve.

    Args:
        text: Source line; embedded newlines are not treated specially.
        width: Column budget per row, floored at 1.
    """
    width = max(1, width)
    if display_width(text) <= width:
        return [text]
    indent = text[: len(text) - len(text.lstrip(" "))]
    rows: list[str] = []
    current = indent if display_width(indent) < width else ""
    used = display_width(current)
    for word in text.lstrip(" ").split(" "):
        if not word:
            continue
        size = display_width(word)
        gap = 1 if current.strip() else 0
        if used + gap + size <= width:
            current += (" " if gap else "") + word
            used += gap + size
            continue
        if current.strip():
            rows.append(current)
            current, used = "", 0
        pieces = wrap_columns(word, width)  # a word that fits a row comes back whole, so only a longer one is cut
        rows.extend(pieces[:-1])
        current = pieces[-1]
        used = display_width(current)
    rows.append(current)
    return rows or [""]


def wrap_columns(text: str, width: int) -> list[str]:
    """Hard-wrap one logical line at a column budget, never mid-character.

    Args:
        text: Source line; embedded newlines are not treated specially.
        width: Column budget per row, floored at 1.
    """
    width = max(1, width)
    if text.isascii() and text.isprintable():
        # One column a character, so a row is exactly ``width`` characters and the
        # last is whatever is left. An empty line is still one (empty) row.
        return [text[start : start + width] for start in range(0, len(text), width)] or [""]
    lines: list[str] = []
    current = ""
    used = 0
    for character in text:
        char_width = character_width(character)
        if current and used + char_width > width:
            lines.append(current)
            current, used = "", 0
        current += character
        used += char_width
    lines.append(current)
    return lines


def count_wrapped_rows(text: str, width: int) -> int:
    """Return how many rows :func:`wrap_columns` would make of one line, without making them.

    A caller that only needs to say how many rows lie beyond the ones it shows — a
    tool result's "… 40 more rows" — should not build every one of them to count.

    Args:
        text: Source line; embedded newlines are not treated specially.
        width: Column budget per row, floored at 1.
    """
    width = max(1, width)
    if text.isascii() and text.isprintable():
        return max(1, -(-len(text) // width))
    return len(wrap_columns(text, width))


def expand_tabs(text: str, *, tab_size: int = 4, start_column: int = 0) -> str:
    """Replace tabs with spaces aligned to fixed tab stops.

    Args:
        text: Source string.
        tab_size: Cells between tab stops.
        start_column: Column the text begins at, so tab stops continue from the
            caller's indentation rather than restarting at zero.
    """
    expanded: list[str] = []
    column = start_column
    for character in text:
        if character != "\t":
            expanded.append(character)
            column += character_width(character)
            continue
        spaces = tab_size - (column % tab_size)
        expanded.append(" " * spaces)
        column += spaces
    return "".join(expanded)


def expand_span_tabs(spans: Sequence[Span], *, tab_size: int = 4, start_column: int = 0) -> tuple[Span, ...]:
    """Expand tabs across span boundaries while preserving their styles.

    Args:
        spans: Fragments that may contain tabs.
        tab_size: Cells between tab stops.
        start_column: Column the first span begins at.
    """
    expanded: list[Span] = []
    column = start_column
    for span in spans:
        if "\t" not in span.text:
            expanded.append(span)
            column += display_width(span.text)
            continue
        chunk = ""
        for character in span.text:
            if character == "\t":
                spaces = tab_size - (column % tab_size)
                chunk += " " * spaces
                column += spaces
            else:
                chunk += character
                column += character_width(character)
        if chunk:
            expanded.append(Span(chunk, span.style))
    return tuple(expanded)


def wrap_spans(spans: Sequence[Span], width: int) -> list[tuple[Span, ...]]:
    """Hard-wrap styled runs at a column budget, never mid-character.

    Args:
        spans: Styled fragments forming one logical line.
        width: Column budget per row, floored at 1.

    Returns:
        One span tuple per row; a fragment split across rows keeps its style.
    """
    width = max(1, width)
    rows: list[tuple[Span, ...]] = []
    row: list[Span] = []
    chunk = ""
    chunk_style: Style = Style()
    used = 0
    for span in spans:
        text = span.text
        if not text:
            continue
        span_width = display_width(text)
        if used + span_width <= width:
            # The whole fragment fits on this row, so no character of it can wrap:
            # it joins the run in progress when the style is the same and starts a
            # new one when it is not, exactly as placing it character by character
            # would, without visiting each character to say so.
            if chunk and chunk_style != span.style:
                row.append(Span(chunk, chunk_style))
                chunk = ""
            chunk_style = span.style
            chunk += text
            used += span_width
            continue
        for character in text:
            char_width = character_width(character)
            if used and used + char_width > width:
                if chunk:
                    row.append(Span(chunk, chunk_style))
                    chunk = ""
                rows.append(tuple(row))
                row = []
                used = 0
            if chunk and chunk_style != span.style:
                row.append(Span(chunk, chunk_style))
                chunk = ""
            chunk_style = span.style
            chunk += character
            used += char_width
    if chunk:
        row.append(Span(chunk, chunk_style))
    rows.append(tuple(row))
    return rows
