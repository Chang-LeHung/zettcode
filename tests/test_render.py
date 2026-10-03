"""Tests for the render layer: color depth, Unicode text, and canvases."""

from dataclasses import replace
from io import StringIO

from zettcode.tui import Canvas, ColorDepth, DifferentialRenderer, Span, Style
from zettcode.tui.capabilities import (
    detect_capabilities,
    detect_color_depth,
    detect_reduced_motion,
    detect_unicode,
)
from zettcode.tui.render import (
    SweepSpan,
    blend,
    cell_glyph,
    character_width,
    display_width,
    encode_style,
    expand_span_tabs,
    expand_tabs,
    parse_hex,
    rgb_to_ansi16,
    rgb_to_ansi256,
    slice_columns,
    sweep_spans,
    truncate,
    wrap_columns,
    wrap_spans,
)
from zettcode.tui.render.renderer import _changed_bounds


def test_color_depth_encodes_truecolor_256_16_and_mono():
    red = Style(foreground="#ff0000", bold=True)

    assert encode_style(red, ColorDepth.TRUECOLOR) == "\x1b[0;1;38;2;255;0;0m"
    assert encode_style(red, ColorDepth.ANSI256) == "\x1b[0;1;38;5;196m"
    assert encode_style(red, ColorDepth.ANSI16) == "\x1b[0;1;91m"
    assert encode_style(red, ColorDepth.MONO) == "\x1b[0;1m"
    assert encode_style(Style(background="#000000"), ColorDepth.ANSI16) == "\x1b[0;40m"
    assert encode_style(Style(foreground="#ffffff"), ColorDepth.ANSI16) == "\x1b[0;97m"


def test_palette_lookup_picks_the_nearest_index():
    assert parse_hex("#ff0000") == (255, 0, 0)
    assert parse_hex("bogus") is None
    assert parse_hex("#fff") is None
    assert rgb_to_ansi16(255, 0, 0) == 9
    # The first sixteen entries alias the terminal's theme, so 256-colour output
    # is always drawn from the fixed cube and grey ramp above them.
    assert rgb_to_ansi256(255, 255, 255) == 231
    assert rgb_to_ansi256(230, 233, 231) == 254
    assert rgb_to_ansi256(95, 95, 95) == 59
    assert rgb_to_ansi256(128, 128, 128) == 244


def test_blend_walks_between_two_colours_and_survives_a_bad_palette():
    assert blend("#000000", "#ffffff", 0) == "#000000"
    assert blend("#000000", "#ffffff", 1) == "#ffffff"
    assert blend("#000000", "#ffffff", 0.5) == "#808080"
    # Clamped, and unusable input falls back to the first colour rather than
    # failing a repaint.
    assert blend("#000000", "#ffffff", 2) == "#ffffff"
    assert blend("#123456", "#ffffff", -1) == "#123456"
    assert blend("not-a-colour", "#ffffff", 0.5) == "not-a-colour"


def test_sweep_spans_moves_the_bright_end_left_to_right():
    label = SweepSpan("abcdef", Style(foreground="#111111"), peak=Style(foreground="#999999"), ramp=2)

    def peak_column(step: int) -> int:
        column = 0
        for span in sweep_spans(label, step):
            if span.style.foreground == "#999999":
                return column
            column += display_width(span.text)
        return -1

    # Off the text at first, then one column per step, then off the right end.
    assert peak_column(0) == -1
    assert [peak_column(step) for step in (2, 3, 4)] == [0, 1, 2]
    assert peak_column(label.travel - 1) == -1
    assert peak_column(label.travel + 2) == 0


def test_sweep_spans_keeps_the_text_and_merges_equal_runs():
    label = SweepSpan("wide 字符", Style(foreground="#111111"), peak=Style(foreground="#999999"), ramp=3)
    ramp_colours = {blend("#111111", "#999999", amount) for amount in (0, 0.25, 0.5, 0.75, 1)}

    for step in range(label.travel):
        spans = sweep_spans(label, step)

        assert "".join(span.text for span in spans) == label.text
        assert all(spans[index].style != spans[index + 1].style for index in range(len(spans) - 1))
        # The ramp never darkens the text: every run sits between the resting
        # colour and the peak, never below the resting one.
        assert {span.style.foreground for span in spans} <= ramp_colours
    assert all(rgb_to_ansi256(*rgb) >= 16 for rgb in [(0, 0, 0), (255, 0, 0), (205, 205, 205)])


def test_capability_detection_reads_the_environment():
    assert detect_color_depth({}) is ColorDepth.ANSI16
    assert detect_color_depth({"TERM": "xterm-256color"}) is ColorDepth.ANSI256
    assert detect_color_depth({"COLORTERM": "truecolor"}) is ColorDepth.TRUECOLOR
    assert detect_color_depth({"TERM": "xterm-direct"}) is ColorDepth.TRUECOLOR
    assert detect_color_depth({"TERM": "dumb"}) is ColorDepth.MONO
    assert detect_color_depth({"NO_COLOR": "1", "COLORTERM": "truecolor"}) is ColorDepth.MONO
    assert detect_unicode({"LANG": "en_US.UTF-8"}) is True
    assert detect_unicode({"LANG": "C"}) is False
    assert detect_capabilities({"COLORTERM": "truecolor", "LANG": "en_US.UTF-8"}).truecolor is True
    assert detect_reduced_motion({}) is False
    assert detect_reduced_motion({"ZETTCODE_REDUCED_MOTION": "1"}) is True
    assert detect_reduced_motion({"NO_MOTION": "1"}) is True


def test_character_width_counts_wide_combining_and_unsafe_glyphs():
    assert character_width("a") == 1
    assert character_width("中") == 2
    assert character_width("\u0301") == 0
    assert character_width("\x1b") == 1
    assert cell_glyph("\x1b") == ("\ufffd", 1)
    assert display_width("a中") == 3


def test_text_clamping_and_wrapping_respect_columns():
    assert slice_columns("abcdef", 1, 3) == "bc"
    # A wide glyph that overlaps the range is kept whole rather than split.
    assert slice_columns("中ab", 0, 2) == "中"
    assert slice_columns("a中b", 1, 3) == "中"
    assert truncate("abc", 5) == "abc"
    assert truncate("abcdef", 4) == "abc\u2026"
    assert truncate("abcdef", 0) == ""
    assert wrap_columns("abcdef", 2) == ["ab", "cd", "ef"]
    assert wrap_columns("a中b", 2) == ["a", "中", "b"]


def test_tab_expansion_aligns_to_stops_and_keeps_styles():
    assert expand_tabs("a\tb") == "a   b"
    assert expand_tabs("\tx", start_column=2) == "  x"
    assert expand_span_tabs((Span("a"), Span("\tb"))) == (Span("a"), Span("   b"))


def test_wrap_spans_breaks_rows_without_splitting_styles():
    rows = wrap_spans((Span("abcdef"),), 2)

    assert [[span.text for span in row] for row in rows] == [["ab"], ["cd"], ["ef"]]

    styled = wrap_spans((Span("ab", Style(bold=True)), Span("cd", Style(italic=True))), 10)

    assert [(span.text, span.style.bold, span.style.italic) for span in styled[0]] == [
        ("ab", True, False),
        ("cd", False, True),
    ]
    assert wrap_spans((), 10) == [()]


def test_canvas_tracks_wide_glyph_continuation_cells():
    canvas = Canvas(4, 1)

    consumed = canvas.draw_text(0, 0, "中a")

    assert consumed == 3
    assert canvas.cells[0][0].character == "中"
    assert canvas.cells[0][1].continuation is True
    assert canvas.cells[0][2].character == "a"


def test_canvas_restyle_changes_styles_without_touching_glyphs():
    canvas = Canvas(5, 1)
    canvas.draw_text(0, 0, "abcde")

    canvas.restyle(1, 0, 3, lambda style: replace(style, reverse=True))

    assert "".join(cell.character for cell in canvas.cells[0]) == "abcde"
    assert [cell.style.reverse for cell in canvas.cells[0]] == [False, True, True, True, False]


def test_renderer_downgrades_color_to_the_terminal_depth():
    output = StringIO()
    renderer = DifferentialRenderer(output, color_depth=ColorDepth.ANSI256)
    canvas = Canvas(8, 1)
    canvas.draw_text(0, 0, "red", Style(foreground="#ff0000"))

    renderer.render(canvas)

    frame = output.getvalue()
    assert "38;5;196" in frame
    assert "38;2;" not in frame

    output.seek(0)
    output.truncate()
    mono = DifferentialRenderer(output, color_depth=ColorDepth.MONO)
    mono.render(canvas)

    assert "38;2;" not in output.getvalue()
    assert "38;5;" not in output.getvalue()


def test_changed_bounds_covers_the_whole_row_without_a_previous_frame():
    canvas = Canvas(4, 1)

    assert _changed_bounds(canvas.cells[0], None) == (0, 3)


def test_changed_bounds_reports_an_empty_range_for_identical_rows():
    """The repaint window is a pure function, so its edges are tested directly."""
    canvas = Canvas(4, 1)
    canvas.set_cell(1, 0, "\u4f60")

    start, end = _changed_bounds(canvas.cells[0], list(canvas.cells[0]))

    assert end < start


def test_changed_bounds_reaches_back_to_the_leader_of_a_wide_glyph():
    before = Canvas(4, 1)
    before.set_cell(1, 0, "\u4f60")
    after = Canvas(4, 1)
    after.set_cell(1, 0, "\u4f60")
    after.set_cell(2, 0, "X")  # an overlay painting over the glyph's tail

    # Column 2 alone changed, but starting there would leave half a glyph.
    assert _changed_bounds(after.cells[0], before.cells[0]) == (1, 2)


def test_changed_bounds_reaches_forward_to_the_tail_of_a_wide_glyph():
    before = Canvas(4, 1)
    before.set_cell(1, 0, "\u4f60")
    after = Canvas(4, 1)
    after.set_cell(1, 0, "\u4f60")
    # Restyling skips continuation cells, so only the leader differs.
    after.restyle(1, 0, 1, lambda style: replace(style, reverse=True))

    assert _changed_bounds(after.cells[0], before.cells[0]) == (1, 2)
