"""The plain-text layouts a command prints: measured in terminal cells, not in characters."""

from __future__ import annotations

import pytest

from zettcode.table import block, display_width, pad, table


def test_a_wide_character_takes_two_cells_and_a_combining_mark_none():
    assert display_width("审查") == 4
    assert display_width("abc") == 3
    assert display_width("e\u0301") == 1, "an e and its combining acute are one cell"


def test_padding_is_measured_in_cells_and_never_cuts():
    assert display_width(pad("审查", 6)) == 6
    assert display_width(pad("ab", 6)) == 6
    assert pad("abcdef", 2) == "abcdef", "a text wider than the column is left as it is"


def test_a_table_starts_each_column_at_the_same_cell_whatever_the_script():
    lines = table([("NAME", "TITLE"), ("审查", "修复"), ("ab", "fix")])

    assert lines == ["NAME  TITLE", "审查  修复", "ab    fix"], "a wide name takes two cells each, and pads with two"


def test_a_block_puts_one_field_on_a_line_and_lines_the_values_up():
    lines = block([("name", "审查"), ("workspace", "~/w")])

    assert lines == ["  name       审查", "  workspace  ~/w"]


def test_a_control_character_is_shown_as_a_space_and_never_breaks_the_layout():
    lines = block([("title", "a\nb"), ("name", "x")])

    assert len(lines) == 2 and lines[0] == "  title  a b", "a newline in a title cannot start a line of its own"


def test_a_bidi_override_is_shown_as_a_space_rather_than_reordering_the_line():
    lines = block([("title", "a\u202eb")])

    assert "\u202e" not in lines[0] and lines[0] == "  title  a b"


def test_pad_does_not_let_a_control_character_through_either():
    padded = pad("a\nb", 4)

    assert padded.startswith("a b") and "\n" not in padded


def test_a_joiner_or_a_skin_tone_takes_no_cells_of_its_own():
    assert display_width("👍🏽") == 2
    assert display_width("a\u200db") == 2
    assert display_width("e\ufe0f") == 1


def test_a_row_of_another_width_is_refused_rather_than_laid_out_wrongly():
    with pytest.raises(ValueError, match="cells"):
        table([("NAME", "TITLE"), ("only one",)])


def test_an_empty_table_or_block_is_no_lines():
    assert table([]) == []
    assert block([]) == []
