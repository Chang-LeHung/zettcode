"""Text that comes from another process: cleaned of escapes, reduced to a title, folded into a name."""

from __future__ import annotations

import pytest

from zettcode.broker.protocol import MAX_TITLE
from zettcode.broker.text import clean_text, clean_title, folder_name, short_id, slug, tail_id

# -- text ----------------------------------------------------------------------------------------------


def test_escape_sequences_are_removed_because_the_text_is_painted_in_another_terminal():
    assert clean_text("a\x1b[2Jb\x1b[31mred\x1b[0m\x1b]0;evil title\x07c\x1b]8;;http://x\x1b\\d") == "abredcd"


@pytest.mark.parametrize("text", ["\x1b", "\x1b[", "text \x1b[3", "\x1b]0;unterminated"])
def test_a_broken_escape_sequence_leaves_no_control_character_behind(text):
    assert "\x1b" not in clean_text(text)


def test_control_characters_go_but_newlines_and_tabs_stay():
    assert clean_text("a\x00b\x07c\x08d\x7fe\x85f\tg\nh") == "abcdef\tg\nh"


def test_line_endings_are_normalised():
    assert clean_text("one\r\ntwo\rthree\nfour") == "one\ntwo\nthree\nfour"


def test_a_lone_surrogate_becomes_a_replacement_character():
    assert clean_text("a\ud800b") == "a\ufffdb"


def test_ordinary_unicode_is_left_alone():
    assert clean_text("你好 — café ☕ \U0001f600") == "你好 — café ☕ \U0001f600"


def test_cleaning_is_idempotent():
    once = clean_text("x\x1b[1my\x00\r\nz\ud800")

    assert clean_text(once) == once


# -- titles --------------------------------------------------------------------------------------------


def test_a_title_is_one_trimmed_line():
    assert clean_title("  Fix   the\nparser\t now \x1b[1m ", MAX_TITLE) == "Fix the parser now"


def test_a_long_title_is_cut_and_not_left_with_a_trailing_space():
    cut = clean_title("word " * 100, MAX_TITLE)

    assert len(cut) <= MAX_TITLE and not cut.endswith(" ")


@pytest.mark.parametrize("value", [None, 5, [], {}, b"bytes"])
def test_what_is_not_a_title_is_empty(value):
    assert clean_title(value, MAX_TITLE) == ""


# -- the part of a title that follows an @ ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Fix the Parser!", "fix-the-parser"),
        ("  --  weird   //  spacing  --  ", "weird-spacing"),
        ("café ☕ crème", "cafe-creme"),
        ("snake_case and CamelCase", "snake-case-and-camelcase"),
        ("v1.2.3 release", "v1-2-3-release"),
        ("a" * 80, "a" * 32),
        ("", ""),
        ("!!!", ""),
        ("修复解析器", ""),
        ("日本語 and english", "and-english"),
    ],
)
def test_a_title_reduces_to_what_the_composer_can_type_after_an_at_sign(title, expected):
    assert slug(title) == expected


def test_a_slug_never_starts_or_ends_with_a_separator_even_when_cut():
    value = slug("abc " * 20)

    assert value and not value.startswith("-") and not value.endswith("-") and len(value) <= 32


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("01a138df-3a1c-7b02-9c11-5f2d3e4a77c1", "4a77c1"),
        ("ABCDEF-0123", "ef0123"),
        ("abc", "abc"),
        ("---", "session"),
        ("", "session"),
    ],
)
def test_the_end_of_an_id_is_the_part_that_tells_two_sessions_apart(session_id, expected):
    assert tail_id(session_id) == expected


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("01A10B75-1234-7abc-8def-0123456789ab", "01a10b75"),
        ("abc", "abc"),
        ("---", "session"),
        ("", "session"),
        ("a.b_c-d!e", "abcde"),
    ],
)
def test_the_short_form_of_an_id_is_what_a_person_can_type(session_id, expected):
    assert short_id(session_id) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/home/me/project", "project"),
        ("/home/me/project/", "project"),
        ("C:\\Users\\me\\proj", "proj"),
        ("C:\\", ""),
        ("/", ""),
        ("", ""),
        ("relative/dir", "dir"),
        ("//server//share//x", "x"),
    ],
)
def test_the_folder_a_path_names_is_its_last_part_whichever_way_it_is_written(path, expected):
    assert folder_name(path) == expected
