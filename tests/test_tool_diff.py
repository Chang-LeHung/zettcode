"""A file edit shows its change, and a file write says how many lines it holds."""

from __future__ import annotations

import pytest

from zettcode.app.agent.conversation.entries import EditEntry, EntryStatus, ToolEntry, WriteEntry
from zettcode.app.agent.conversation.rendering import (
    DIFF_CONTEXT,
    MAX_DIFF_ROWS,
    EditTool,
    WriteTool,
    edit_diff,
    write_diff,
    written_lines,
)
from zettcode.app.agent.conversation.text import TOOL_EXPANDED_ROWS, TOOL_PREVIEW_ROWS
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.app.ui.widgets import TranscriptSource
from zettcode.tui import DARK, LIGHT


def _edit(old: str, new: str) -> dict[str, str]:
    return {"old_text": old, "new_text": new}


# -- the rows of an edit's diff ---------------------------------------------------------------------------


def test_a_one_line_replacement_is_a_deletion_and_an_addition():
    assert edit_diff([_edit("x = 1", "x = 2")]) == (("-", "x = 1"), ("+", "x = 2"))


def test_an_unchanged_line_either_side_of_a_change_is_kept_for_context():
    old = "a\nb\nc\nd\ne"
    new = "a\nb\nC\nd\ne"

    assert edit_diff([_edit(old, new)]) == ((" ", "b"), ("-", "c"), ("+", "C"), (" ", "d"))


def test_only_one_line_of_context_is_kept_not_the_whole_unchanged_run():
    old = "\n".join(f"line {i}" for i in range(20))
    new = old.replace("line 10", "LINE 10")

    rows = edit_diff([_edit(old, new)])

    assert [kind for kind, _ in rows] == [" ", "-", "+", " "] and DIFF_CONTEXT == 1


def test_two_changes_far_apart_in_one_edit_are_joined_by_a_break_not_by_the_lines_between():
    old = "\n".join(f"l{i}" for i in range(12))
    new = old.replace("l1", "L1").replace("l10", "L10")

    rows = edit_diff([_edit(old, new)])

    assert [("@", "\u2026")] == [row for row in rows if row[0] == "@"]
    assert ("-", "l1") in rows and ("-", "l10") in rows and (" ", "l5") not in rows


def test_pure_additions_and_pure_deletions_have_no_opposite_rows():
    assert edit_diff([_edit("keep", "keep\nnew line")]) == ((" ", "keep"), ("+", "new line"))
    assert edit_diff([_edit("keep\ngone", "keep")]) == ((" ", "keep"), ("-", "gone"))


def test_an_edit_that_changes_nothing_has_no_rows_at_all():
    assert edit_diff([_edit("same\nlines", "same\nlines")]) == ()


def test_several_edits_are_told_apart_by_a_labelled_break():
    rows = edit_diff([_edit("a", "b"), _edit("c", "d")])

    assert rows == (("@", "edit 1 of 2"), ("-", "a"), ("+", "b"), ("@", "edit 2 of 2"), ("-", "c"), ("+", "d"))


def test_a_single_edit_has_no_label():
    assert all(kind != "@" for kind, _ in edit_diff([_edit("a", "b")]))


@pytest.mark.parametrize(
    "edits",
    [None, "not edits", 7, [], [None], [{"old_text": "a"}], [{"old_text": 1, "new_text": "b"}], [["a", "b"]]],
)
def test_what_is_not_an_edit_is_skipped_not_guessed_at(edits):
    assert edit_diff(edits) == ()


def test_a_bad_edit_among_good_ones_does_not_cost_the_good_ones_their_place():
    rows = edit_diff([_edit("a", "b"), {"old_text": None}, _edit("c", "d")])

    assert rows == (("@", "edit 1 of 2"), ("-", "a"), ("+", "b"), ("@", "edit 2 of 2"), ("-", "c"), ("+", "d"))


def test_a_whole_file_in_the_arguments_is_cut_at_the_limit_and_says_so():
    big_old = "\n".join(f"old {i}" for i in range(MAX_DIFF_ROWS))
    big_new = "\n".join(f"new {i}" for i in range(MAX_DIFF_ROWS))

    rows = edit_diff([_edit(big_old, big_new)])

    assert len(rows) == MAX_DIFF_ROWS + 1
    assert rows[-1][0] == "@" and "more rows not kept" in rows[-1][1]


def test_a_smaller_limit_is_honoured():
    assert len(edit_diff([_edit("a\nb\nc", "x\ny\nz")], limit=2)) == 3


def test_blank_lines_are_rows_like_any_other():
    assert edit_diff([_edit("a\n\nb", "a\n\nB")]) == ((" ", ""), ("-", "b"), ("+", "B"))


# -- the lines a file write holds --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "lines"),
    [
        ("", 0),
        ("one", 1),
        ("one\n", 1),
        ("one\ntwo", 2),
        ("one\ntwo\n", 2),
        ("\n\n", 2),
        ("a\r\nb\r\n", 2),
        (None, 0),
        (5, 0),
    ],
)
def test_the_lines_a_write_holds(content, lines):
    assert written_lines(content) == lines


def _open(handler, name, **arguments):
    return handler.open_tool(name, arguments, id=1, call_id="c1", started_at=0.0)


def test_a_write_says_how_many_lines_it_wrote_beside_the_file():
    entry = _open(WriteTool(), "write_file", path="src/app.py", content="a\nb\nc\n")

    assert isinstance(entry, WriteEntry) and entry.title == "Wrote src/app.py" and entry.added == 3
    assert not hasattr(entry, "removed"), "a write has no deletions to count"


def test_a_write_with_no_content_argument_adds_nothing_to_the_row():
    assert _open(WriteTool(), "write_file", path="x").added == 0


def test_an_edit_entry_carries_its_counts_and_its_diff():
    entry = _open(EditTool(), "replace_in_file", path="a.py", edits=[_edit("x = 1", "x = 2\ny = 3")])

    assert isinstance(entry, EditEntry) and (entry.added, entry.removed) == (2, 1)
    assert entry.diff == (("-", "x = 1"), ("+", "x = 2"), ("+", "y = 3"))


# -- on the screen -------------------------------------------------------------------------------------------


def _screen(transcript: Transcript, width: int = 70) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(i, width).text.rstrip() for i in range(source.count(width))]


def _styled(transcript: Transcript, width: int = 70):
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(i, width) for i in range(source.count(width))]


def _edit_transcript(edits, *, status=EntryStatus.COMPLETED, output="Replaced 1 occurrence in a.py"):
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("fix it")
    transcript.start_tool("c1", "replace_in_file", {"path": "a.py", "edits": edits})
    transcript.complete_tool("c1", output, status=status)
    return transcript


def test_a_finished_edit_shows_its_diff_under_the_title():
    screen = _screen(_edit_transcript([_edit("x = 1", "x = 2")]))

    assert any("Edited a.py (1 edit) +1 -1" in row for row in screen)
    assert any("- x = 1" in row for row in screen) and any("+ x = 2" in row for row in screen)


def test_the_diff_stands_in_for_the_tools_own_one_line_answer():
    screen = "\n".join(_screen(_edit_transcript([_edit("x = 1", "x = 2")])))

    assert "Replaced 1 occurrence" not in screen


def test_additions_are_painted_as_additions_and_deletions_as_deletions():
    lines = _styled(_edit_transcript([_edit("x = 1", "x = 2")]))
    colours = {span.text: span.style.foreground for line in lines for span in line.spans}

    assert colours["- x = 1"] == DARK.deletion and colours["+ x = 2"] == DARK.addition


def test_context_lines_are_quiet_and_the_break_between_edits_is_quieter_still():
    lines = _styled(_edit_transcript([_edit("a\nb\nc", "a\nB\nc"), _edit("z", "y")]))
    colours = {span.text.strip(): span.style.foreground for line in lines for span in line.spans}

    assert colours["a"] == DARK.subtle and colours["edit 1 of 2"] == DARK.muted


def test_a_failed_edit_shows_its_error_and_not_a_diff_of_what_did_not_happen():
    screen = "\n".join(
        _screen(
            _edit_transcript(
                [_edit("x = 1", "x = 2")], status=EntryStatus.FAILED, output="old_text was not found in a.py"
            )
        )
    )

    assert "old_text was not found" in screen and "- x = 1" not in screen and "+ x = 2" not in screen


def test_while_the_call_runs_there_is_no_diff_yet_only_that_it_is_running():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("fix it")
    transcript.start_tool("c1", "replace_in_file", {"path": "a.py", "edits": [_edit("x", "y")]})

    screen = "\n".join(_screen(transcript))

    assert "Running" in screen and "- x" not in screen


def test_a_long_diff_shows_a_preview_and_counts_the_rest():
    old = "\n".join(f"old {i}" for i in range(30))
    new = "\n".join(f"new {i}" for i in range(30))
    screen = _screen(_edit_transcript([_edit(old, new)]))

    shown = [row for row in screen if row.lstrip(" \u2514").startswith(("- ", "+ "))]
    assert len(shown) == TOOL_PREVIEW_ROWS
    assert any(f"{60 - TOOL_PREVIEW_ROWS} more rows" in row for row in screen)


def test_clicking_a_long_diff_open_shows_a_screenful_and_it_can_be_closed_again():
    old = "\n".join(f"old {i}" for i in range(50))
    new = "\n".join(f"new {i}" for i in range(50))
    transcript = _edit_transcript([_edit(old, new)])
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))

    assert transcript.toggle(tool.id) is True
    opened = [row for row in _screen(transcript) if row.lstrip(" \u2514").startswith(("- ", "+ "))]
    assert len(opened) == TOOL_EXPANDED_ROWS

    assert transcript.toggle(tool.id) is True
    closed = [row for row in _screen(transcript) if row.lstrip(" \u2514").startswith(("- ", "+ "))]
    assert len(closed) == TOOL_PREVIEW_ROWS


def test_a_row_with_a_diff_is_foldable_even_when_the_tool_said_nothing_and_shows_the_arrow():
    transcript = _edit_transcript([_edit("x", "y")], output="")
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))

    assert tool.text == "" and tool.foldable
    heading = next(
        row for row in _screen(transcript) if row.lstrip().startswith(("\u2713", "\u2714")) or "Edited" in row
    )
    assert heading.rstrip().endswith("\u25b8")


def test_a_failed_edit_with_no_message_is_not_foldable_and_has_nothing_to_open():
    transcript = _edit_transcript([_edit("x", "y")], status=EntryStatus.FAILED, output="")
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))

    assert not tool.foldable and transcript.toggle(tool.id) is False


def test_a_long_line_is_cut_at_the_width_not_wrapped_into_the_rows_below():
    screen = _screen(_edit_transcript([_edit("short", "x" * 400)]), width=50)

    assert all(len(row) <= 50 for row in screen)
    assert sum(1 for row in screen if row.lstrip(" \u2514").startswith("+ ")) == 1


def test_control_characters_in_an_edit_cannot_reach_the_canvas():
    screen = "\n".join(_screen(_edit_transcript([_edit("a", "b\x1b[31m red \x07")])))

    assert "\x1b" not in screen and "\x07" not in screen


def test_a_write_row_shows_the_count_in_the_addition_colour_and_no_body():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("make it")
    transcript.start_tool("c1", "write_file", {"path": "new.py", "content": "a\nb\n"})
    transcript.complete_tool("c1", "Wrote 4 bytes to new.py")

    lines = _styled(transcript)
    colours = {span.text.strip(): span.style.foreground for line in lines for span in line.spans}

    assert colours["+2"] == DARK.addition
    assert any("Wrote new.py" in line.text for line in lines)


async def test_an_edit_replayed_from_a_stored_session_shows_its_diff_too(tmp_path):
    """A resumed session opens its rows through the same chain, so its edits are as readable as live ones."""
    from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

    from zettcode.app.agent.conversation.replay import replay
    from zettcode.app.agent.storage import SessionStore

    store = SessionStore(tmp_path)
    await store.append("s", "r", UserMessage(content="fix it"))
    await store.append(
        "s",
        "r",
        AssistantMessage(
            tool_calls=(ToolCall("c1", "replace_in_file", {"path": "a.py", "edits": [_edit("x = 1", "x = 2")]}),)
        ),
    )
    await store.append("s", "r", ToolMessage(tool_call_id="c1", name="replace_in_file", content="Replaced 1"))

    replayed = replay(store.read("s"))

    screen = _screen(replayed.transcript)
    assert any("- x = 1" in row for row in screen) and any("+ x = 2" in row for row in screen)


def test_a_long_line_is_one_row_and_the_rows_after_it_are_the_next_changes_not_its_overflow():
    """Cut, not wrapped: the rows after the long one are the next lines of the diff, in order."""
    transcript = _edit_transcript([_edit("a\nb\nc", f"{'x' * 300}\nB\nC")])
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))
    transcript.toggle(tool.id)  # six rows are more than the preview shows
    screen = _screen(transcript, width=40)

    signs = [row.lstrip(" \u2514")[:2] for row in screen if row.lstrip(" \u2514").startswith(("- ", "+ "))]

    assert signs == ["- ", "- ", "- ", "+ ", "+ ", "+ "], signs
    assert sum(1 for row in screen if "x" * 5 in row) == 1


# -- the colours are the ordinary ones ------------------------------------------------------------------------


@pytest.mark.parametrize("theme", [DARK, LIGHT], ids=["dark", "light"])
def test_by_default_an_addition_is_the_palettes_accent_and_a_deletion_its_error_colour(theme):
    """The look the rows had before the roles existed, kept: bright pure red and green were too loud."""
    assert theme.diff_added is None and theme.diff_removed is None
    assert theme.addition == theme.accent and theme.deletion == theme.error


def test_changing_the_accent_changes_the_diff_with_it_until_the_diff_is_given_a_colour_of_its_own():
    from dataclasses import replace

    moved = replace(DARK, accent="#112233", error="#445566")
    assert (moved.addition, moved.deletion) == ("#112233", "#445566")

    own = replace(moved, diff_added="#00ff00", diff_removed="#ff0000")
    assert (own.addition, own.deletion) == ("#00ff00", "#ff0000")


def test_a_diff_is_painted_in_the_light_palette_in_the_light_palettes_colours():
    transcript = _edit_transcript([_edit("x = 1", "x = 2")])
    source = TranscriptSource(transcript, theme=LIGHT)
    lines = [source.line(i, 70) for i in range(source.count(70))]
    colours = {span.text: span.style.foreground for line in lines for span in line.spans}

    assert colours["- x = 1"] == LIGHT.deletion and colours["+ x = 2"] == LIGHT.addition


def test_a_theme_file_can_change_the_diff_colours():
    from zettcode.tui.theme_file import theme_from_toml

    theme = theme_from_toml('[ui]\ndiff_added = "#00ff00"\ndiff_removed = "#ff0000"\n')

    assert (theme.addition, theme.deletion) == ("#00ff00", "#ff0000")
    assert theme.accent == DARK.accent, "and nothing else moved"


# -- a file write shows its content, all of it added ---------------------------------------------------------


def _write_transcript(content, *, status=EntryStatus.COMPLETED, output="Wrote 12 bytes to new.py"):
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("make it")
    transcript.start_tool("c1", "write_file", {"path": "new.py", "content": content})
    transcript.complete_tool("c1", output, status=status)
    return transcript


def test_a_write_diff_is_every_line_of_the_file_as_an_addition():
    assert write_diff("a\nb\n") == (("+", "a"), ("+", "b"))


@pytest.mark.parametrize("content", [None, 5, "", ["a"]])
def test_a_write_with_nothing_to_show_has_no_diff(content):
    assert write_diff(content) == ()


def test_a_blank_line_in_a_written_file_is_an_added_line_like_any_other():
    assert write_diff("a\n\nb") == (("+", "a"), ("+", ""), ("+", "b"))


def test_a_long_file_is_cut_at_the_limit_and_says_how_many_were_not_kept():
    rows = write_diff("\n".join(f"line {i}" for i in range(MAX_DIFF_ROWS + 25)))

    assert len(rows) == MAX_DIFF_ROWS + 1
    assert rows[-1] == ("@", "\u2026 25 more rows not kept")
    assert all(sign == "+" for sign, _ in rows[:-1])


def test_a_file_exactly_at_the_limit_is_kept_whole_with_no_note():
    rows = write_diff("\n".join("x" for _ in range(MAX_DIFF_ROWS)))

    assert len(rows) == MAX_DIFF_ROWS and all(sign == "+" for sign, _ in rows)


def test_a_finished_write_shows_the_new_file_under_its_title_as_additions():
    screen = _screen(_write_transcript("def f():\n    return 1\n"))

    assert any("Wrote new.py +2" in row for row in screen)
    assert any("+ def f():" in row for row in screen) and any("+     return 1" in row for row in screen)


def test_the_write_diff_stands_in_for_the_tools_own_answer():
    screen = "\n".join(_screen(_write_transcript("a\nb\n")))

    assert "Wrote 12 bytes" not in screen


def test_written_lines_are_painted_in_the_addition_colour_and_nothing_is_painted_as_removed():
    lines = _styled(_write_transcript("a\nb\n"))
    colours = {span.text: span.style.foreground for line in lines for span in line.spans}

    assert colours["+ a"] == DARK.addition and colours["+ b"] == DARK.addition
    assert not any(c == DARK.deletion for c in colours.values())


def test_a_failed_write_shows_its_error_and_not_the_file_it_did_not_write():
    screen = "\n".join(
        _screen(_write_transcript("secret = 1\n", status=EntryStatus.FAILED, output="permission denied: new.py"))
    )

    assert "permission denied" in screen and "secret = 1" not in screen


def test_while_the_write_runs_the_content_is_not_shown_yet():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("make it")
    transcript.start_tool("c1", "write_file", {"path": "new.py", "content": "later\n"})

    screen = "\n".join(_screen(transcript))

    assert "Running" in screen and "+ later" not in screen


def test_a_long_written_file_shows_a_preview_and_opens_to_a_screenful():
    content = "\n".join(f"row {i}" for i in range(60))
    transcript = _write_transcript(content)
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))

    closed = [r for r in _screen(transcript) if r.lstrip(" \u2514").startswith("+ ")]
    assert len(closed) == TOOL_PREVIEW_ROWS and any(
        f"{60 - TOOL_PREVIEW_ROWS} more rows" in r for r in _screen(transcript)
    )
    assert transcript.toggle(tool.id) is True
    opened = [r for r in _screen(transcript) if r.lstrip(" \u2514").startswith("+ ")]
    assert len(opened) == TOOL_EXPANDED_ROWS


def test_an_empty_file_that_was_written_has_nothing_to_unfold_beyond_the_answer():
    transcript = _write_transcript("")
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))

    assert tool.added == 0 and tool.diff == () and tool.foldable, "the tool's answer is still a body"
    assert not any(row.lstrip(" \u2514").startswith("+ ") for row in _screen(transcript))


def test_control_characters_in_a_written_file_cannot_reach_the_canvas():
    screen = "\n".join(_screen(_write_transcript("hi\x1b[31m red \x07\n")))

    assert "\x1b" not in screen and "\x07" not in screen


def test_a_write_replayed_from_a_stored_session_shows_its_content_too(tmp_path):
    import asyncio

    from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

    from zettcode.app.agent.conversation.replay import replay
    from zettcode.app.agent.storage import SessionStore

    async def store_it():
        store = SessionStore(tmp_path)
        await store.append("s", "r", UserMessage(content="make it"))
        await store.append(
            "s",
            "r",
            AssistantMessage(tool_calls=(ToolCall("c1", "write_file", {"path": "new.py", "content": "x = 1\n"}),)),
        )
        await store.append("s", "r", ToolMessage(tool_call_id="c1", name="write_file", content="Wrote 6 bytes"))
        return store.read("s")

    screen = _screen(replay(asyncio.run(store_it())).transcript)

    assert any("+ x = 1" in row for row in screen)
