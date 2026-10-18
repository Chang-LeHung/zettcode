"""Wrapping prose between words, and where it is used: a notice or an error, and nowhere that must keep its columns."""

from __future__ import annotations

import pytest

from zettcode.app import Transcript, TranscriptSource
from zettcode.tui import DARK
from zettcode.tui.render import display_width, wrap_columns, wrap_words

SENTENCE = "error: Provider stream request failed (HTTP 404: the model does not exist; check the address with /config)"


def test_a_line_that_fits_is_left_alone():
    assert wrap_words("a short line", 40) == ["a short line"]
    assert wrap_words("exactly ten", 11) == ["exactly ten"]
    assert wrap_words("", 5) == [""]


def test_a_word_that_fits_a_row_is_never_split_it_moves_down_whole():
    rows = wrap_words("one two three four five six", 11)

    assert rows == ["one two", "three four", "five six"]
    assert all(len(row) <= 11 for row in rows)


def test_the_command_a_reader_is_told_to_try_is_never_cut_in_two():
    for width in range(14, 70):
        rows = wrap_words(SENTENCE, width)

        assert any(row.endswith("/config)") and row.split()[-1] == "/config)" for row in rows), (width, rows)
        assert not any(row.endswith(("/con", "/c", "/co", "/conf")) for row in rows), (width, rows)


@pytest.mark.parametrize("width", [8, 12, 20, 33, 60, 100])
def test_no_row_is_wider_than_the_budget_and_nothing_is_lost_but_the_spaces_at_the_breaks(width):
    rows = wrap_words(SENTENCE, width)

    assert all(display_width(row) <= width for row in rows)
    assert "".join("".join(rows).split()) == "".join(SENTENCE.split())


def test_a_word_wider_than_a_row_is_broken_at_the_budget_and_the_rest_goes_on_after_it():
    rows = wrap_words("see /Users/someone/projects/api/src/main.py now", 12)

    assert rows == ["see", "/Users/someo", "ne/projects/", "api/src/main", ".py now"]


def test_text_with_no_spaces_in_it_wraps_exactly_as_it_did():
    text = "修复解析器里关于制表符和缩进混用的所有边界情况"

    assert wrap_words(text, 10) == wrap_columns(text, 10)


def test_a_wide_character_is_never_split_and_never_overhangs():
    rows = wrap_words("a \u4e2d\u6587 mixed \u65e5\u672c\u8a9e line of text", 9)

    assert rows == ["a \u4e2d\u6587", "mixed", "\u65e5\u672c\u8a9e", "line of", "text"]
    assert all(display_width(row) <= 9 for row in rows)


def test_leading_space_is_kept_on_the_first_row():
    assert wrap_words("   indented and long enough to wrap", 14)[0].startswith("   indented")


def test_a_line_of_only_spaces_is_one_empty_row():
    assert wrap_words("          ", 4) == [""]


def test_a_budget_of_one_still_makes_progress():
    assert wrap_words("ab cd", 1) == ["a", "b", "c", "d"]


def test_a_row_never_starts_with_the_space_it_broke_at():
    assert all(not row.startswith(" ") for row in wrap_words(SENTENCE, 17))


# -- where it is used ----------------------------------------------------------------------------------------------


def _rows(transcript: Transcript, width: int) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(index, width).text for index in range(source.count(width))]


def test_an_error_in_the_conversation_breaks_between_words():
    transcript = Transcript()
    transcript.error(SENTENCE)

    rows = [row.strip() for row in _rows(transcript, 50) if row.strip()]

    assert len(rows) >= 2
    assert all(not row.startswith(("fig", "onfig")) for row in rows)
    assert " ".join(rows).replace("  ", " ") == SENTENCE


def test_a_notice_breaks_between_words_too():
    transcript = Transcript()
    transcript.notice("The model sent back an empty reply. Try again, or check the model and address with /config.")

    rows = [row.strip() for row in _rows(transcript, 40) if row.strip()]

    assert "/config." in rows[-1] and not any(row.endswith("/con") for row in rows)


def test_the_readers_own_message_still_wraps_at_the_column_as_it_did():
    """Not changed here: whether a message the reader typed should wrap by word is their call."""
    transcript = Transcript()
    transcript.begin_turn("abcdefghij klmnopqrst")

    rows = [row.rstrip() for row in _rows(transcript, 8)]

    assert rows[2:6] == ["› abcdef", "  ghij k", "  lmnopq", "  rst"], "'klmnopqrst' is cut in the middle, as before"


def test_a_tools_output_still_wraps_at_the_column_because_a_space_in_it_is_a_character():
    transcript = Transcript()
    transcript.start_tool("t", "bash", {"command": "echo"})
    transcript.complete_tool("t", "ab" * 20, wait=False)

    rows = _rows(transcript, 20)

    assert any(row.strip().startswith("abababab") for row in rows)


@pytest.mark.parametrize("width", [1, 2, 3, 5])
def test_a_wide_glyph_in_a_row_too_narrow_for_it_is_cut_to_the_budget_not_left_overhanging(width):
    transcript = Transcript()
    transcript.notice("\u4e2d\u6587 \u540e\u9762 \u8fd8\u6709 text")

    assert all(display_width(row) <= width for row in _rows(transcript, width))
