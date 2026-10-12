"""The shortcuts the text measuring takes must give exactly what the slow way gives.

Measuring and wrapping text is what every row of the transcript pays for, and most
of what a terminal shows is printable ASCII, where every character is one column.
So the common case skips the per-character width lookup. A shortcut like that is
only worth having if it cannot be told from the code it replaces, which is what
these tests hold it to: the original implementations live here as the reference,
and the real ones are compared against them over a lot of generated text, most of
it chosen to sit on the edge of a shortcut — wide glyphs, combining marks, control
characters, escape sequences, tabs, carriage returns.
"""

from __future__ import annotations

import random
import re

import pytest

from zettcode.app.agent.rows import bounded_rows, terminal_safe
from zettcode.tui import Span, Style, TextLine
from zettcode.tui.render import character_width, count_wrapped_rows, display_width, wrap_columns, wrap_spans

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")

#: Pieces chosen to sit on the edge of a shortcut: plain text, a wide glyph, a
#: combining mark, a control character, an escape sequence, a tab, a lone surrogate-
#: free emoji, DEL, and a non-breaking space.
_PIECES = (
    "a",
    "word ",
    "x" * 40,
    " ",
    "\u4e2d",
    "\u6587\u5b57",
    "e\u0301",
    "\u00e9",
    "\U0001f600",
    "\x00",
    "\x1b[31mred\x1b[0m",
    "\t",
    "\x7f",
    "\u00a0",
    "\u200b",
    "\r",
    "\n",
)


def _reference_display_width(text: str) -> int:
    return sum(character_width(character) for character in text)


def _reference_wrap_columns(text: str, width: int) -> list[str]:
    width = max(1, width)
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


def _reference_terminal_safe(value: str) -> str:
    cleaned = _ANSI.sub("", value).replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return "".join(
        character if character in "\n" else character if character.isprintable() else "\ufffd" for character in cleaned
    )


def _reference_bounded_rows(value: str, width: int, limit: int) -> tuple[list[str], int]:
    rows: list[str] = []
    for source in _reference_terminal_safe(value).splitlines() or [""]:
        rows.extend(_reference_wrap_columns(source, width))
    omitted = max(0, len(rows) - limit)
    return rows[:limit], omitted


def _samples(count: int, *, seed: int) -> list[str]:
    """Return generated text: runs of the edge pieces, some pure ASCII, some empty."""
    rng = random.Random(seed)
    texts = ["", " ", "a", "a" * 200, "hello world", "\n", "\n\n", "line\n", "\u4e2d" * 30, "a\u4e2db"]
    for _ in range(count):
        texts.append("".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 40))))
    for _ in range(count):
        texts.append("".join(rng.choice("abcdefgh ij\n") for _ in range(rng.randint(0, 120))))
    return texts


TEXTS = _samples(600, seed=20261011)
WIDTHS = (1, 2, 3, 5, 8, 20, 79, 120)


def test_the_width_of_a_string_is_what_summing_its_characters_gives():
    for text in TEXTS:
        assert display_width(text) == _reference_display_width(text), repr(text)


def test_printable_ascii_is_the_case_the_shortcut_takes_and_nothing_else_is():
    """The shortcut applies to exactly the text where every character is one column."""
    for text in TEXTS:
        takes_the_shortcut = text.isascii() and text.isprintable()
        if takes_the_shortcut:
            assert all(character_width(character) == 1 for character in text), repr(text)


@pytest.mark.parametrize("width", WIDTHS)
def test_wrapping_gives_the_same_rows_as_placing_characters_one_by_one(width: int):
    for text in TEXTS:
        assert wrap_columns(text, width) == _reference_wrap_columns(text, width), (width, repr(text))


def test_a_width_below_one_is_floored_to_one_on_both_paths():
    for text in ("abc", "\u4e2d\u6587", ""):
        assert wrap_columns(text, 0) == _reference_wrap_columns(text, 0)
        assert wrap_columns(text, -5) == _reference_wrap_columns(text, -5)


@pytest.mark.parametrize("width", WIDTHS)
def test_counting_rows_gives_the_number_wrapping_makes(width: int):
    for text in TEXTS:
        assert count_wrapped_rows(text, width) == len(_reference_wrap_columns(text, width)), (width, repr(text))


def test_cleaning_output_gives_the_same_text_with_or_without_the_shortcut():
    for text in TEXTS:
        assert terminal_safe(text) == _reference_terminal_safe(text), repr(text)


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("limit", [0, 1, 5, 40])
def test_the_rows_shown_and_the_rows_hidden_are_what_wrapping_everything_gives(width: int, limit: int):
    """A result is wrapped only as far as the rows that are shown; the count is exact all the same.

    The text is joined into one multi-line value as tool output is, so the limit
    falls in the middle of the value, at a line boundary, and inside a wrapped line.
    """
    rng = random.Random(width * 1000 + limit)
    for _ in range(60):
        value = "\n".join(rng.choice(TEXTS).replace("\n", " ") for _ in range(rng.randint(0, 25)))
        assert bounded_rows(value, width, limit) == _reference_bounded_rows(value, width, limit), (
            width,
            limit,
            repr(value[:80]),
        )


def test_a_huge_result_is_not_wrapped_beyond_the_rows_that_are_shown():
    """The saving is the point: a test log of ten thousand lines is wrapped for five of them."""
    lines = [f"tests/test_module.py::test_case_{index} PASSED" for index in range(10_000)]
    value = "\n".join(lines)

    rows, omitted = bounded_rows(value, 80, 5)

    assert rows == lines[:5]
    assert omitted == 9_995


# -- wrapping styled runs ----------------------------------------------------------


def _reference_wrap_spans(spans, width):
    """The character-by-character wrap the fragment shortcut stands in for."""
    width = max(1, width)
    rows = []
    row = []
    chunk = ""
    chunk_style = Style()
    used = 0
    for span in spans:
        for character in span.text:
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


_STYLES = (Style(), Style(bold=True), Style(foreground="#ff0000"), Style(italic=True, foreground="#00ff00"))


def _span_lists(count: int, *, seed: int) -> list[list[Span]]:
    """Return lists of styled runs: empty ones, same-style neighbours, wide glyphs, long runs."""
    rng = random.Random(seed)
    lists: list[list[Span]] = [[], [Span("")], [Span("", _STYLES[1]), Span("a", _STYLES[2])]]
    for _ in range(count):
        spans = []
        for _ in range(rng.randint(0, 8)):
            text = "".join(rng.choice(_PIECES + ("abc", "word ", "\u4e2d\u6587")) for _ in range(rng.randint(0, 6)))
            spans.append(Span(text.replace("\n", " "), rng.choice(_STYLES)))
        lists.append(spans)
    return lists


SPAN_LISTS = _span_lists(500, seed=7)


@pytest.mark.parametrize("width", WIDTHS)
def test_wrapping_styled_runs_gives_the_rows_character_by_character_placement_gives(width: int):
    """A fragment that fits is appended whole, and that is only a shortcut if nothing can tell.

    The same runs, the same rows, the same styles on each piece, and the same merging of
    neighbours that share a style — including where a fragment is exactly the room that is
    left, one column more than it, empty, or wider than a whole row.
    """
    for spans in SPAN_LISTS:
        assert wrap_spans(spans, width) == _reference_wrap_spans(spans, width), (width, spans)


def test_a_fragment_that_exactly_fills_the_row_does_not_wrap_and_one_more_column_does():
    style = Style(bold=True)

    assert wrap_spans([Span("abcd", style)], 4) == [(Span("abcd", style),)]
    assert wrap_spans([Span("abcde", style)], 4) == [(Span("abcd", style),), (Span("e", style),)]
    assert wrap_spans([Span("ab", style), Span("cd", style)], 4) == [(Span("abcd", style),)]
    assert wrap_spans([Span("ab", style), Span("cd", Style())], 4) == [(Span("ab", style), Span("cd", Style()))]


def test_the_width_of_a_line_is_the_sum_of_its_fragments_and_a_fragment_is_its_text():
    for spans in SPAN_LISTS:
        line = TextLine(tuple(spans))
        assert line.width == sum(_reference_display_width(span.text) for span in spans)
        assert all(span.width == _reference_display_width(span.text) for span in spans)
