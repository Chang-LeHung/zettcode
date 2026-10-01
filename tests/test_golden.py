"""Golden snapshots: any rendering change has to show up as a reviewable diff.

Expected blocks are kept inline on purpose. A golden test that wrote its own
reference file would need write access to the checkout, which tests must not
have; keeping the block in the source means the reference moves through review
like any other code.
"""

from zettcode.app import Transcript, TranscriptView
from zettcode.tui_framework import (
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
from zettcode.tui_framework.testing import render_block
from zettcode.tui_framework.widgets import Collapsible, MarkdownView
from zettcode.tui_framework.widgets.diff import DiffView, build_unified


def test_golden_status_bar():
    assert render_block(StatusBar("left", "right"), width=16, height=1, theme=DARK) == (
        "left       right\n-- styles --\n0:0-4 fg#747d77\n0:11-16 fg#747d77"
    )


def test_golden_list_view():
    view = ListView([ListItem("a", label="alpha"), ListItem("b", label="beta")])

    assert render_block(view, width=16, height=3, theme=DARK) == (
        "\u25b8 alpha\n  beta\n\n-- styles --\n0:0-7 b,fg#e6e9e7,bg#2f4a38\n1:0-6 fg#e6e9e7"
    )


def test_golden_table():
    table = Table([Column("Name"), Column("N", align="right")], [["alpha", "1"]])

    assert render_block(table, width=18, height=5, theme=DARK) == (
        "Name       N\n"
        "\u2500\u2500\u2500\u2500\u2500   \u2500\u2500\u2500\u2500\n"
        "alpha      1\n"
        "\n"
        "\n"
        "-- styles --\n"
        "0:0-4 fg#e6e9e7\n"
        "0:4-11 b,fg#e6e9e7\n"
        "0:11-12 fg#e6e9e7\n"
        "1:0-12 d,fg#343a36\n"
        "2:0-12 fg#e6e9e7"
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
        "1:1-13 fg#e6e9e7\n"
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
        "0:0-5 b,fg#e6e9e7\n"
        "3:0-5 fg#e6e9e7\n"
        "4:0-2 fg#e6e9e7\n"
        "4:2-5 b,fg#e6e9e7"
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

    assert render_block(TranscriptView(transcript, theme=DARK), width=44, height=16, theme=DARK) == (
        "hi\n"
        "\n"
        "\u276f find the bug\n"
        "\n"
        "\u25b8 Thinking  0 ms\n"
        "\n"
        '\u2713 read_file {"path":"app.py"}  0 ms \u25b8\n'
        "    \u2514 line one\n"
        "      line two\n"
        "\n"
        "Result\n"
        "\n"
        "\n"
        "Fixed parse.\n"
        "\n"
        "\n"
        "-- styles --\n"
        "0:0-2 fg#a3ada6\n"
        "2:0-14 b,fg#e6e9e7\n"
        "4:0-16 b,fg#79b88b\n"
        "6:0-37 b,fg#79b88b\n"
        "7:0-14 fg#a3ada6\n"
        "8:0-14 fg#a3ada6\n"
        "10:0-6 b,fg#e6e9e7\n"
        "13:0-6 fg#e6e9e7\n"
        "13:6-11 fg#d8c07a\n"
        "13:11-12 fg#e6e9e7"
    )


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
        "0:0-7 b,fg#e6e9e7,bg#2f4a38\n"
        "0:7-28 fg#747d77,bg#2f4a38\n"
        "0:28-44 b,fg#e6e9e7,bg#2f4a38\n"
        "1:0-5 fg#e6e9e7\n"
        "1:7-37 fg#747d77"
    )
