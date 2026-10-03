"""Golden snapshots: any rendering change has to show up as a reviewable diff.

Expected blocks are kept inline on purpose. A golden test that wrote its own
reference file would need write access to the checkout, which tests must not
have; keeping the block in the source means the reference moves through review
like any other code.
"""

from zettcode.app import Transcript, TranscriptView
from zettcode.tui import (
    DARK,
    Column,
    CompletionItem,
    CompletionPopup,
    Dialog,
    DialogAction,
    ListItem,
    ListView,
    StatusBar,
    Table,
    Text,
)
from zettcode.tui.testing import render_block
from zettcode.tui.widgets import Collapsible, MarkdownView
from zettcode.tui.widgets.diff import DiffView, build_unified


def test_golden_status_bar():
    assert render_block(StatusBar("left", "right"), width=16, height=1, theme=DARK) == (
        "left       right\n-- styles --\n0:0-4 fg#747d77\n0:11-16 fg#747d77"
    )


def test_golden_list_view():
    view = ListView([ListItem("a", label="alpha"), ListItem("b", label="beta")])

    assert render_block(view, width=16, height=3, theme=DARK) == (
        "\u25b8 alpha\n  beta\n\n-- styles --\n0:0-7 b,fg#f2f5f3,bg#2f4a38\n1:0-6 fg#f2f5f3"
    )


def test_golden_table():
    table = Table([Column("Name"), Column("N", align="right")], [["alpha", "1"]])

    assert render_block(table, width=18, height=5, theme=DARK) == (
        "Name       N\n"
        "\u2500\u2500\u2500\u2500\u2500   \u2500\u2500\u2500\u2500\n"
        "alpha      1\n"
        "\u2500\u2500\u2500\u2500\u2500   \u2500\u2500\u2500\u2500\n"
        "\n"
        "-- styles --\n"
        "0:0-4 fg#f2f5f3\n"
        "0:4-11 b,fg#f2f5f3\n"
        "0:11-12 fg#f2f5f3\n"
        "1:0-12 fg#a3ada6\n"
        "2:0-12 fg#f2f5f3\n"
        "3:0-12 fg#a3ada6"
    )


def test_golden_dialog():
    dialog = Dialog(
        Text("rm -rf build"),
        title="Confirm",
        actions=(DialogAction("Run"), DialogAction("Abort")),
    )

    assert render_block(dialog, width=24, height=8, theme=DARK) == (
        "\u250c\u2500 Confirm \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510\n"
        "\u2502rm -rf build          \u2502\n"
        "\u2502                      \u2502\n"
        "\u2502                      \u2502\n"
        "\u2502                      \u2502\n"
        "\u2502                      \u2502\n"
        "\u2502 Run   Abort          \u2502\n"
        "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518\n"
        "-- styles --\n"
        "1:1-13 fg#f2f5f3\n"
        "6:1-6 b,fg#0f1412,bg#79b88b\n"
        "6:7-14 fg#747d77"
    )


def test_golden_collapsible():
    assert render_block(Collapsible("Steps", Text("body")), width=16, height=3, theme=DARK) == (
        "\u25b8 Steps\n\n\n-- styles --\n0:0-7 b,fg#79b88b"
    )


def test_golden_markdown():
    view = MarkdownView("# Title\n\n- one\n- **two**")

    assert render_block(view, width=24, height=6, theme=DARK) == (
        "Title\n"
        "\n"
        "\n"
        "\u00b7 one\n"
        "\u00b7 two\n"
        "\n"
        "-- styles --\n"
        "0:0-5 b,fg#f2f5f3\n"
        "3:0-5 fg#f2f5f3\n"
        "4:0-2 fg#f2f5f3\n"
        "4:2-5 b,fg#f2f5f3"
    )


def test_golden_diff_gutter_and_word_emphasis():
    view = DiffView(build_unified("a\nb\nc", "a\nB\nc"))

    assert render_block(view, width=30, height=8, theme=DARK) == (
        "           --- a\n"
        "           +++ b\n"
        "           @@ -1,3 +1,3 @@\n"
        "   1    1  a\n"
        "   2      -b\n"
        "        2 +B\n"
        "   3    3  c\n"
        "\n"
        "-- styles --\n"
        "0:0-16 d,fg#747d77\n"
        "1:0-16 d,fg#747d77\n"
        "2:0-10 d,fg#747d77\n"
        "2:10-26 d,fg#9bddad\n"
        "3:0-10 d,fg#747d77\n"
        "3:10-12 fg#a3ada6\n"
        "4:0-10 d,fg#747d77\n"
        "4:10-11 b,fg#dc8178\n"
        "4:11-12 b,fg#dc8178,bg#2f4a38\n"
        "5:0-10 d,fg#747d77\n"
        "5:10-11 b,fg#79b88b\n"
        "5:11-12 b,fg#79b88b,bg#2f4a38\n"
        "6:0-10 d,fg#747d77\n"
        "6:10-12 fg#a3ada6"
    )


def test_golden_transcript_blocks():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.welcome("hi")
    transcript.begin_turn("find the bug")
    transcript.start_thinking()
    transcript.append_thinking("weighing options")
    transcript.complete_thinking()
    transcript.start_tool("1", "read_file", {"path": "app.py"})
    transcript.complete_tool("1", "line one\nline two")
    transcript.append_answer("# Result\n\nFixed `parse`.")

    assert render_block(TranscriptView(transcript, theme=DARK), width=44, height=18, theme=DARK) == (
        "  hi\n"
        "\n"
        "\n"
        "\u203a find the bug\n"
        "\n"
        "\n"
        "  \u25b8 Thinking  0 ms\n"
        "\n"
        "  \u2713 Read app.py  0 ms \u25b8\n"
        "      \u2514 line one\n"
        "        line two\n"
        "\n"
        "  Result\n"
        "\n"
        "\n"
        "  Fixed parse.\n"
        "\n"
        "\n"
        "-- styles --\n"
        "0:0-4 fg#a3ada6\n"
        "2:0-44 fg#f2f5f3,bg#222725\n"
        "3:0-44 fg#f2f5f3,bg#222725\n"
        "4:0-44 fg#f2f5f3,bg#222725\n"
        "6:0-18 b,fg#79b88b\n"
        "8:0-15 b,fg#79b88b\n"
        "8:15-23 fg#747d77\n"
        "9:0-8 fg#a3ada6\n"
        "9:8-16 fg#f2f5f3\n"
        "10:0-8 fg#a3ada6\n"
        "10:8-16 fg#f2f5f3\n"
        "12:0-8 b,fg#f2f5f3\n"
        "15:0-8 fg#f2f5f3\n"
        "15:8-13 fg#9bddad\n"
        "15:13-14 fg#f2f5f3"
    )


def test_user_prompt_surface_wraps_and_keeps_full_width():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("abcdef" * 2)
    source = TranscriptView(transcript, theme=DARK).transcript_source
    user_rows = [source.line(index, 12) for index in range(5)]

    # The arrow sits flush left and the text under it uses the full width.
    assert [line.text.strip() for line in user_rows] == ["", "", "\u203a abcdefabcd", "ef", ""]
    assert all(len(line.text) == 12 for line in user_rows[1:])
    assert all(line.spans[0].style.background == DARK.surface_alt for line in user_rows[1:])


def test_golden_completion_popup():
    """The slash menu: a command column, a muted description, a full-width band."""
    popup = CompletionPopup(
        [
            CompletionItem("/new", description="start a fresh session"),
            CompletionItem("/use", description="switch to a session: /use <id>"),
        ]
    )

    assert render_block(popup, width=44, height=4, theme=DARK) == (
        " /new  start a fresh session\n"
        " /use  switch to a session: /use <id>\n"
        "\n"
        "\n"
        "-- styles --\n"
        "0:0-7 b,fg#f2f5f3,bg#2f4a38\n"
        "0:7-28 fg#747d77,bg#2f4a38\n"
        "0:28-44 b,fg#f2f5f3,bg#2f4a38\n"
        "1:0-5 fg#f2f5f3\n"
        "1:7-37 fg#747d77"
    )
