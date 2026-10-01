"""Tests for unified-diff parsing, word emphasis, and rendering."""

from zettcode.tui_framework import Canvas, DiffLine, DiffSegment, Rect, build_unified, parse_unified, word_diff
from zettcode.tui_framework.core.theme import DARK
from zettcode.tui_framework.widgets.diff import DiffView

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
        for row in canvas.cells[4:6]
        for cell in row
        if cell.style.background == DARK.selection and cell.character.strip()
    ]
    assert emphasised


def test_diff_view_without_numbers_uses_no_gutter():
    assert DiffView([DiffLine("add", "new")]).gutter == 0
    assert DiffView(parse_unified("@@ -1 +1 @@\n-old\n+new\n")).gutter == 11
