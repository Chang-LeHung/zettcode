"""`AnsiBuffer`: what a program prints, as lines of styled characters."""

from __future__ import annotations

from zettcode.tui.render import ANSI_COLORS, AnsiBuffer
from zettcode.tui.render.ansi import xterm_color
from zettcode.tui.render.style import DEFAULT_STYLE, Style


def lines(buffer: AnsiBuffer) -> list[str]:
    return [line.text for line in buffer.lines]


def colours(buffer: AnsiBuffer, row: int = 0) -> list[tuple[str, str | None]]:
    return [(span.text, span.style.foreground) for span in buffer.lines[row].spans()]


def test_plain_text_is_lines_and_write_says_how_many_it_started():
    buffer = AnsiBuffer()

    assert buffer.write("one\ntwo\nthr") == 2
    assert buffer.write("ee\n") == 1
    assert lines(buffer) == ["one", "two", "three", ""]


def test_a_colour_applies_until_it_is_reset():
    buffer = AnsiBuffer()

    buffer.write("a \x1b[31mred\x1b[0m b")

    assert colours(buffer) == [("a ", None), ("red", ANSI_COLORS[1]), (" b", None)]


def test_bright_background_256_and_true_colour_codes():
    buffer = AnsiBuffer()

    buffer.write("\x1b[92mA\x1b[38;5;196mB\x1b[38;2;1;2;3mC\x1b[48;5;21mD\x1b[0m")

    assert [style for _, style in [(s.text, s.style) for s in buffer.lines[0].spans()]] == [
        Style(foreground=ANSI_COLORS[10]),
        Style(foreground="#ff0000"),
        Style(foreground="#010203"),
        Style(foreground="#010203", background="#0000ff"),
    ]


def test_the_colon_form_of_true_colour_is_read_like_the_semicolon_form():
    buffer = AnsiBuffer()

    buffer.write("\x1b[38:2::10:20:30mx\x1b[38:2:40:50:60my")

    assert colours(buffer) == [("x", "#0a141e"), ("y", "#28323c")]


def test_attributes_come_and_go():
    buffer = AnsiBuffer()

    buffer.write("\x1b[1;3mA\x1b[22mB\x1b[23mC\x1b[2;7;9mD\x1b[0mE")

    styles = [span.style for span in buffer.lines[0].spans()]
    assert styles[0] == Style(bold=True, italic=True)
    assert styles[1] == Style(italic=True)
    assert styles[2] == DEFAULT_STYLE
    assert styles[3] == Style(dim=True, reverse=True, strike=True)
    assert styles[4] == DEFAULT_STYLE


def test_a_carriage_return_writes_over_the_line_so_a_progress_bar_is_one_line():
    buffer = AnsiBuffer()

    buffer.write("10%\r50%\r100%\n")
    buffer.write("abcdef\rXY\n")

    assert lines(buffer) == ["100%", "XYcdef", ""]


def test_erase_to_end_of_line_after_a_return_leaves_only_the_new_text():
    buffer = AnsiBuffer()

    buffer.write("a long first message\r\x1b[Kshort")

    assert lines(buffer) == ["short"]


def test_erase_the_whole_line_and_move_in_it():
    buffer = AnsiBuffer()

    buffer.write("hello\x1b[2K!\x1b[3Gxy")

    # Erasing a line does not move the cursor: the "!" lands where the "o" ended, then "xy" at column 3.
    assert lines(buffer) == ["  xy !"]
    buffer.write("\nabc\x1b[2D-\x1b[1C+")
    assert lines(buffer)[1] == "a-c+"


def test_backspace_steps_back_and_a_tab_goes_to_the_next_stop():
    buffer = AnsiBuffer()

    buffer.write("ab\bX\n")
    buffer.write("a\tb\n")

    assert lines(buffer)[:2] == ["aX", "a       b"]


def test_a_sequence_cut_in_two_by_a_read_is_held_until_the_rest_arrives():
    buffer = AnsiBuffer()

    buffer.write("x\x1b")
    buffer.write("[3")
    buffer.write("1my\x1b[0m")

    assert colours(buffer) == [("x", None), ("y", ANSI_COLORS[1])]
    assert lines(buffer) == ["xy"]


def test_titles_unknown_sequences_and_cursor_moves_between_lines_are_dropped():
    buffer = AnsiBuffer()

    buffer.write("\x1b]0;a window title\x07ok\x1b[2A\x1b[?25l\x1b(B\x1b[1Gdone")

    assert lines(buffer) == ["done"]


def test_clearing_the_screen_forgets_what_was_printed():
    buffer = AnsiBuffer()

    buffer.write("old\nolder\n\x1b[2Jnew")

    assert lines(buffer) == ["new"]


def test_control_characters_are_not_printed():
    buffer = AnsiBuffer()

    buffer.write("a\x07b\x00c\x7fd")

    assert lines(buffer) == ["abcd"]


def test_only_the_newest_lines_are_kept_and_the_cut_is_counted():
    buffer = AnsiBuffer(max_lines=3)

    buffer.write("1\n2\n3\n4\n5")

    assert lines(buffer) == ["3", "4", "5"]
    assert buffer.dropped == 2


def test_a_style_given_to_one_write_does_not_leak_into_the_next():
    buffer = AnsiBuffer()

    buffer.write("$ cmd\n", Style(bold=True))
    buffer.write("output\n")

    assert buffer.lines[0].styles[0] == Style(bold=True)
    assert buffer.lines[1].styles[0] == DEFAULT_STYLE


def test_the_colour_a_program_set_survives_between_writes():
    buffer = AnsiBuffer()

    buffer.write("\x1b[32mgreen ")
    buffer.write("still green\x1b[0m")

    assert colours(buffer) == [("green still green", ANSI_COLORS[2])]


def test_a_line_wraps_by_columns_and_a_wide_glyph_is_not_cut_in_half():
    buffer = AnsiBuffer()

    buffer.write("abcdefghij\n" + "\u4f60\u597d\u4e16\u754c\n\n")

    assert buffer.lines[0].rows(4) == [(0, 4), (4, 8), (8, 10)]
    assert buffer.lines[1].rows(5) == [(0, 2), (2, 4)]
    assert buffer.lines[1].width == 8
    assert buffer.lines[2].rows(4) == [(0, 0)]


def test_the_palette_is_the_xterm_one():
    assert xterm_color(1) == ANSI_COLORS[1]
    assert xterm_color(16) == "#000000" and xterm_color(231) == "#ffffff"
    assert xterm_color(232) == "#080808" and xterm_color(255) == "#eeeeee"
