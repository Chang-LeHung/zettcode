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
    Span,
    StatusBar,
    Style,
    Table,
    Text,
    TextLine,
)
from zettcode.tui.testing import render_block
from zettcode.tui.widgets import Collapsible, MarkdownView
from zettcode.tui.widgets.diff import DiffView, build_unified


def test_golden_status_bar():
    assert render_block(StatusBar("left", "right"), width=16, height=1, theme=DARK) == (
        "left       right\n-- styles --\n0:0-4 fg#7a8478\n0:11-16 fg#7a8478"
    )


def test_golden_status_bar_keeps_plugin_styles():
    """A styled segment keeps its colours; a bare span inherits the bar style."""
    left = TextLine((Span("L", Style(foreground="#ff0000", bold=True)), Span("x")))

    assert render_block(StatusBar(left, "R"), width=6, height=1, theme=DARK) == (
        "Lx   R\n-- styles --\n0:0-1 b,fg#ff0000\n0:1-2 fg#7a8478\n0:5-6 fg#7a8478"
    )


def test_golden_list_view():
    view = ListView([ListItem("a", label="alpha"), ListItem("b", label="beta")])

    assert render_block(view, width=16, height=3, theme=DARK) == (
        "▸ alpha\n  beta\n\n-- styles --\n0:0-7 b,fg#f2f5f3,bg#4a5f52\n1:0-6 fg#f2f5f3"
    )


def test_golden_table():
    table = Table([Column("Name"), Column("N", align="right")], [["alpha", "1"]])

    assert render_block(table, width=18, height=5, theme=DARK) == (
        "Name       N\n"
        "─────   ────\n"
        "alpha      1\n"
        "─────   ────\n"
        "\n"
        "-- styles --\n"
        "0:0-4 fg#f2f5f3\n"
        "0:4-11 b,fg#f2f5f3\n"
        "0:11-12 fg#f2f5f3\n"
        "1:0-12 fg#9da9a0\n"
        "2:0-12 fg#f2f5f3\n"
        "3:0-12 fg#9da9a0"
    )


def test_golden_dialog():
    dialog = Dialog(
        Text("rm -rf build"),
        title="Confirm",
        actions=(DialogAction("Run"), DialogAction("Abort")),
    )

    assert render_block(dialog, width=24, height=8, theme=DARK) == (
        "┌─ Confirm ────────────┐\n"
        "│rm -rf build          │\n"
        "│                      │\n"
        "│                      │\n"
        "│                      │\n"
        "│                      │\n"
        "│ Run   Abort          │\n"
        "└──────────────────────┘\n"
        "-- styles --\n"
        "1:1-13 fg#f2f5f3\n"
        "6:1-6 b,fg#2d353b,bg#a7c080\n"
        "6:7-14 fg#7a8478"
    )


def test_golden_collapsible():
    assert render_block(Collapsible("Steps", Text("body")), width=16, height=3, theme=DARK) == (
        "▸ Steps\n\n\n-- styles --\n0:0-7 b,fg#a7c080"
    )


def test_golden_markdown():
    view = MarkdownView("# Title\n\n- one\n- **two**")

    assert render_block(view, width=24, height=6, theme=DARK) == (
        "Title\n"
        "\n"
        "\n"
        "  · one\n"
        "  · two\n"
        "\n"
        "-- styles --\n"
        "0:0-5 b,fg#f2f5f3\n"
        "3:0-7 fg#f2f5f3\n"
        "4:0-4 fg#f2f5f3\n"
        "4:4-7 b,fg#f2f5f3"
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
        "0:0-16 d,fg#7a8478\n"
        "1:0-16 d,fg#7a8478\n"
        "2:0-10 d,fg#7a8478\n"
        "2:10-26 d,fg#83c092\n"
        "3:0-10 d,fg#7a8478\n"
        "3:10-12 fg#9da9a0\n"
        "4:0-10 d,fg#7a8478\n"
        "4:10-11 b,fg#e67e80\n"
        "4:11-12 b,fg#e67e80,bg#4a5f52\n"
        "5:0-10 d,fg#7a8478\n"
        "5:10-11 b,fg#a7c080\n"
        "5:11-12 b,fg#a7c080,bg#4a5f52\n"
        "6:0-10 d,fg#7a8478\n"
        "6:10-12 fg#9da9a0"
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
    transcript.settle_wait("Processed for 1.2 s \u00b7 09:41")

    assert render_block(TranscriptView(transcript, theme=DARK), width=44, height=18, theme=DARK) == (
        "  hi\n"
        "\n"
        "\n"
        "› find the bug\n"
        "\n"
        "\n"
        "  ▸ Thinking  0.0 s\n"
        "\n"
        "  ✓ Read app.py  0.0 s ▸\n"
        "      └ line one\n"
        "        line two\n"
        "\n"
        "  Result\n"
        "\n"
        "\n"
        "  Fixed parse.\n"
        "\n"
        "  Processed for 1.2 s \u00b7 09:41\n"
        "-- styles --\n"
        "0:0-4 fg#9da9a0\n"
        "2:0-44 fg#f2f5f3,bg#343f44\n"
        "3:0-44 fg#f2f5f3,bg#343f44\n"
        "4:0-44 fg#f2f5f3,bg#343f44\n"
        "6:0-19 fg#83c092\n"
        "8:0-15 fg#b8a6e0\n"
        "8:15-24 fg#7a8478\n"
        "9:0-8 fg#7a8478\n"
        "9:8-16 fg#f2f5f3\n"
        "10:0-8 fg#7a8478\n"
        "10:8-16 fg#f2f5f3\n"
        "12:0-8 b,fg#f2f5f3\n"
        "15:0-8 fg#f2f5f3\n"
        "15:8-13 fg#9bddad\n"
        "15:13-14 fg#f2f5f3\n"
        "17:0-29 fg#7a8478"
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
            CompletionItem("/resume", description="resume a session: /resume [id]"),
        ]
    )

    assert render_block(popup, width=44, height=4, theme=DARK) == (
        " /new     start a fresh session\n"
        " /resume  resume a session: /resume [id]\n"
        "\n"
        "\n"
        "-- styles --\n"
        "0:0-10 b,fg#f2f5f3,bg#4a5f52\n"
        "0:10-31 fg#7a8478,bg#4a5f52\n"
        "0:31-44 b,fg#f2f5f3,bg#4a5f52\n"
        "1:0-8 fg#f2f5f3\n"
        "1:10-40 fg#7a8478"
    )
