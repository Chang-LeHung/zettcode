"""Tests for unified-diff parsing, word emphasis, and rendering."""

from zettcode.tui import Canvas, DiffLine, DiffSegment, Rect, build_unified, paired_rows, parse_unified, word_diff
from zettcode.tui.core.theme import DARK
from zettcode.tui.widgets.diff import DiffView

SAMPLE = """\
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+gamma
 delta
"""


def row_text(canvas: Canvas, y: int) -> str:
    return "".join(cell.character for cell in canvas.cells[y] if not cell.continuation)


def test_word_diff_marks_only_the_changed_tokens():
    old, new = word_diff("the quick brown fox", "the slow brown fox")

    assert old == (DiffSegment("the ", False), DiffSegment("quick", True), DiffSegment(" brown fox", False))
    assert new == (DiffSegment("the ", False), DiffSegment("slow", True), DiffSegment(" brown fox", False))
    assert word_diff("same", "same") == ((DiffSegment("same", False),), (DiffSegment("same", False),))


def test_paired_rows_mark_only_the_tokens_a_row_rewrote():
    rows = paired_rows([("-", "x = 1"), ("+", "x = 2"), ("+", "y = 3")])

    assert [sign for sign, _ in rows] == ["-", "+", "+"]
    assert rows[0][1] == (DiffSegment("x = ", False), DiffSegment("1", True))
    assert rows[1][1] == (DiffSegment("x = ", False), DiffSegment("2", True))
    assert rows[2][1] == (DiffSegment("y = 3", False),), "an addition with no removal beside it is the whole line"


def test_paired_rows_leave_context_and_labels_whole():
    rows = paired_rows([(" ", "unchanged"), ("@", "edit 1 of 2"), ("+", "new")])

    assert rows == [
        (" ", (DiffSegment("unchanged", False),)),
        ("@", (DiffSegment("edit 1 of 2", False),)),
        ("+", (DiffSegment("new", False),)),
    ]


def test_a_break_between_two_edits_keeps_their_lines_from_pairing():
    rows = paired_rows([("-", "x = 1"), ("@", "edit 2 of 2"), ("+", "x = 2")])

    assert rows[0][1] == (DiffSegment("x = 1", False),)
    assert rows[2][1] == (DiffSegment("x = 2", False),)


def test_a_row_with_nothing_to_be_compared_with_is_plain():
    alone = paired_rows([("-", "gone")])
    longer = paired_rows([("-", "a 1"), ("-", "b 2"), ("+", "a 3")])

    assert alone == [("-", (DiffSegment("gone", False),))]
    assert longer[0][1] == (DiffSegment("a ", False), DiffSegment("1", True)), "the pair the run can make"
    assert longer[1][1] == (DiffSegment("b 2", False),), "the rest of the longer run has no answer"
    assert longer[2][1] == (DiffSegment("a ", False), DiffSegment("3", True))


def test_a_removal_after_an_addition_starts_a_run_of_its_own():
    """Unified diff never emits that order; a row built by hand must not pair across it either."""
    rows = paired_rows([("-", "a 1"), ("+", "a 2"), ("-", "b 3")])

    assert rows[0][1] == (DiffSegment("a ", False), DiffSegment("1", True))
    assert rows[1][1] == (DiffSegment("a ", False), DiffSegment("2", True))
    assert rows[2][1] == (DiffSegment("b 3", False),)


def test_a_line_rewritten_outright_is_marked_all_the_way_through():
    """Nothing of the removed line survived, so nothing of it is left plain: GitHub's choice, not delta's."""
    rows = paired_rows([("-", "import os"), ("+", "def total():")])

    for sign, segments in rows:
        assert all(segment.emphasis for segment in segments if segment.text.strip()), sign


def test_parse_unified_tracks_kinds_numbers_and_emphasis():
    lines = parse_unified(SAMPLE)

    assert [line.kind for line in lines] == ["meta", "meta", "hunk", "context", "remove", "add", "context"]
    context, removed, added = lines[3], lines[4], lines[5]
    assert (context.text, context.old_number, context.new_number) == ("alpha", 1, 1)
    assert (removed.text, removed.old_number) == ("beta", 2)
    assert (added.text, added.new_number) == ("gamma", 2)
    assert removed.segments[0].emphasis is True
    assert added.segments[0].emphasis is True
    assert lines[6].old_number == 3 and lines[6].new_number == 3


def test_build_unified_diffs_two_texts():
    lines = build_unified("a\nb\nc", "a\nB\nc")

    assert [line.kind for line in lines] == ["meta", "meta", "hunk", "context", "remove", "add", "context"]
    assert [(line.text, line.old_number, line.new_number) for line in lines[3:]] == [
        ("a", 1, 1),
        ("b", 2, None),
        ("B", None, 2),
        ("c", 3, 3),
    ]


def test_diff_view_renders_a_gutter_and_highlights_changed_words():
    view = DiffView(parse_unified(SAMPLE))
    view.layout(Rect(0, 0, 40, 8))
    canvas = Canvas(40, 8)

    view.render(canvas)

    assert view.gutter == 11
    assert "gamma" in row_text(canvas, 5)
    assert row_text(canvas, 4).lstrip().startswith("2")
    emphasised = [
        cell
        for row, band in ((4, DARK.deletion_emphasis_fill), (5, DARK.addition_emphasis_fill))
        for cell in canvas.cells[row]
        if cell.style.background == band and cell.character.strip()
    ]
    assert emphasised, "the words the diff rewrote sit on the deeper band of their own side"
    assert {cell.style.foreground for cell in emphasised} == {DARK.deletion, DARK.addition}


def test_diff_view_without_numbers_uses_no_gutter():
    assert DiffView([DiffLine("add", "new")]).gutter == 0
    assert DiffView(parse_unified("@@ -1 +1 @@\n-old\n+new\n")).gutter == 11
