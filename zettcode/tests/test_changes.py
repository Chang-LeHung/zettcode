"""At the end of a turn the files it changed are listed once; a turn that changed none says nothing."""

from __future__ import annotations

from pathlib import Path, PurePath

import pytest

from zettcode.app.agent.conversation.changes import changed_files, shown_path
from zettcode.app.agent.conversation.entries import ChangesEntry, EntryStatus, FileSummary
from zettcode.app.agent.conversation.presenters import DEFAULT_PRESENTERS, MAX_CHANGED_ROWS
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.app.ui.widgets import TranscriptSource
from zettcode.tui import DARK

#: A workspace that is absolute on every platform, built from the platform's own root.
ROOT = PurePath(Path.cwd().anchor)
WORK = ROOT / "work" / "project"


def _edit(old: str, new: str) -> dict[str, str]:
    return {"old_text": old, "new_text": new}


def _turn(*calls, status=EntryStatus.COMPLETED) -> Transcript:
    """A transcript holding one turn in which each ``(tool, arguments)`` ran."""
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("do it")
    for index, (tool, arguments) in enumerate(calls):
        transcript.start_tool(f"c{index}", tool, arguments)
        transcript.complete_tool(f"c{index}", "ok", status=status, wait=False)
    return transcript


def _text(transcript: Transcript, width: int = 70) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(i, width).text.rstrip() for i in range(source.count(width))]


def _stripped(transcript: Transcript, width: int = 70) -> list[str]:
    """The rows without the margin the whole conversation is indented by."""
    return [row.strip() for row in _text(transcript, width)]


# -- adding it up -----------------------------------------------------------------------------------------


def test_one_edit_is_one_file_with_its_counts():
    t = _turn(("replace_in_file", {"path": "a.py", "edits": [_edit("x", "y\nz")]}))

    assert changed_files(t.entries) == (FileSummary("a.py", added=2, removed=1),)


def test_a_write_counts_every_line_as_added():
    t = _turn(("write_file", {"path": "new.py", "content": "a\nb\nc\n"}))

    assert changed_files(t.entries) == (FileSummary("new.py", added=3),)


def test_several_changes_to_one_file_are_one_row_with_the_totals():
    t = _turn(
        ("replace_in_file", {"path": "a.py", "edits": [_edit("x", "y")]}),
        ("replace_in_file", {"path": "a.py", "edits": [_edit("p\nq", "r")]}),
    )

    assert changed_files(t.entries) == (FileSummary("a.py", added=2, removed=3),)


def test_files_are_listed_in_the_order_they_were_first_touched():
    t = _turn(
        ("write_file", {"path": "b.py", "content": "x"}),
        ("write_file", {"path": "a.py", "content": "x"}),
        ("replace_in_file", {"path": "b.py", "edits": [_edit("x", "y")]}),
    )

    assert [f.path for f in changed_files(t.entries)] == ["b.py", "a.py"]


def test_the_same_file_named_two_ways_is_one_file():
    t = _turn(
        ("write_file", {"path": "src/a.py", "content": "x"}),
        ("replace_in_file", {"path": str(WORK / "src" / "a.py"), "edits": [_edit("x", "y")]}),
        ("replace_in_file", {"path": "./src/a.py", "edits": [_edit("y", "z")]}),
    )

    files = changed_files(t.entries, WORK)

    assert [f.path for f in files] == ["src/a.py"] and files[0].added == 3


def test_a_failed_call_changed_nothing_and_is_not_counted():
    t = _turn(("replace_in_file", {"path": "a.py", "edits": [_edit("x", "y")]}), status=EntryStatus.FAILED)

    assert changed_files(t.entries) == ()


def test_a_skipped_call_never_ran_and_is_not_counted():
    t = _turn(("write_file", {"path": "a.py", "content": "x"}), status=EntryStatus.SKIPPED)

    assert changed_files(t.entries) == ()


def test_reading_searching_and_running_are_not_changes():
    t = _turn(
        ("read_file", {"path": "a.py"}),
        ("grep", {"pattern": "x"}),
        ("bash", {"command": "ls"}),
    )

    assert changed_files(t.entries) == ()


def test_a_deleted_file_is_listed_as_deleted():
    t = _turn(("delete_file", {"path": "old.py"}))

    assert changed_files(t.entries) == (FileSummary("old.py", deleted=True),)


def test_a_file_written_and_then_deleted_is_deleted_and_one_deleted_and_then_written_exists():
    gone = _turn(("write_file", {"path": "a.py", "content": "x\ny"}), ("delete_file", {"path": "a.py"}))
    back = _turn(("delete_file", {"path": "a.py"}), ("write_file", {"path": "a.py", "content": "x\ny"}))

    assert changed_files(gone.entries) == (FileSummary("a.py", deleted=True),)
    assert changed_files(back.entries) == (FileSummary("a.py", added=2),)


def test_a_call_with_no_path_cannot_be_named_and_is_left_out():
    t = _turn(("write_file", {"content": "x"}))

    assert changed_files(t.entries) == ()


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        ("a.py", "a.py"),
        ("./a.py", "a.py"),
        ("src/../a.py", "src/../a.py"),
        (str(WORK / "a.py"), "a.py"),
        (str(WORK / "src" / "a.py"), "src/a.py"),
        (str(ROOT / "elsewhere" / "a.py"), str(ROOT / "elsewhere" / "a.py")),
        (str(ROOT / "work" / "project-two" / "a.py"), str(ROOT / "work" / "project-two" / "a.py")),
    ],
)
def test_a_path_is_shown_relative_to_the_workspace_only_when_it_is_inside_it(given, shown):
    assert shown_path(given, WORK) == shown


def test_with_no_workspace_a_path_is_left_as_the_call_named_it():
    given = str(WORK / "a.py")

    assert shown_path(given, None) == given


# -- the turn's summary --------------------------------------------------------------------------------------


def test_a_turn_that_changed_a_file_says_so_once_above_the_pinned_row():
    t = _turn(("replace_in_file", {"path": "a.py", "edits": [_edit("x", "y")]}))
    t.wait_for_model()

    assert t.summarize_changes() is True

    kinds = [entry.kind for entry in t.entries]
    assert kinds.index("changes") == len(kinds) - 2 and kinds[-1] == "wait", "above the wait row, not below it"
    assert sum(1 for k in kinds if k == "changes") == 1


def test_a_turn_that_changed_nothing_adds_nothing():
    t = _turn(("read_file", {"path": "a.py"}))
    before = len(t.entries)

    assert t.summarize_changes() is False and len(t.entries) == before
    assert not any(entry.kind == "changes" for entry in t.entries)


def test_only_this_turns_changes_are_in_its_summary():
    t = _turn(("write_file", {"path": "old.py", "content": "x"}))
    t.settle_wait("Processed for 1s")
    t.begin_turn("again")
    t.start_tool("c9", "write_file", {"path": "new.py", "content": "x"})
    t.complete_tool("c9", "ok", wait=False)

    t.summarize_changes()

    summary = [e for e in t.entries if isinstance(e, ChangesEntry)][-1]
    assert [f.path for f in summary.files] == ["new.py"]


def test_one_file_is_one_line_with_its_counts():
    t = _turn(("replace_in_file", {"path": "src/app.py", "edits": [_edit("a\nb", "c\nd\ne")]}))
    t.summarize_changes()

    assert "Changed src/app.py +3 -2" in _stripped(t)


def test_several_files_are_a_heading_and_one_row_each():
    t = _turn(
        ("replace_in_file", {"path": "src/app.py", "edits": [_edit("a", "b\nc")]}),
        ("write_file", {"path": "src/new.py", "content": "x\ny\nz\n"}),
        ("delete_file", {"path": "old.py"}),
    )
    t.summarize_changes()
    text = _stripped(t)

    assert "Changed 3 files" in text
    assert {"src/app.py +2 -1", "src/new.py +3", "old.py deleted"} <= set(text)


def test_a_long_list_is_cut_and_says_how_many_more():
    calls = [("write_file", {"path": f"f{i}.py", "content": "x"}) for i in range(MAX_CHANGED_ROWS + 5)]
    t = _turn(*calls)
    t.summarize_changes()
    text = _stripped(t)

    assert f"Changed {MAX_CHANGED_ROWS + 5} files" in text
    listed = [row for row in text if row.startswith("f") and row.endswith(".py +1")]
    assert len(listed) == MAX_CHANGED_ROWS, "the rows under the heading are capped; the tool rows above are not"
    assert any("and 5 more" in row for row in text)


def test_a_long_path_is_cut_to_the_width_and_keeps_its_counts():
    t = _turn(("write_file", {"path": "very/deep/" * 12 + "file.py", "content": "x\ny"}))
    t.summarize_changes()

    row = next(r for r in _text(t, width=40) if r.strip().startswith("Changed "))

    assert len(row) <= 40 and row.endswith("+2")


def test_the_counts_wear_the_diff_colours_and_the_rest_is_quiet():
    t = _turn(("replace_in_file", {"path": "a.py", "edits": [_edit("x", "y\nz")]}))
    t.summarize_changes()
    source = TranscriptSource(t, theme=DARK)
    spans = [
        s
        for i in range(source.count(70))
        for s in source.line(i, 70).spans
        if "Changed" in "".join(x.text for x in source.line(i, 70).spans)
    ]
    colours = {s.text.strip(): s.style.foreground for s in spans}

    assert colours["+2"] == DARK.addition and colours["-1"] == DARK.deletion
    assert colours["Changed a.py"] == DARK.muted


def test_the_summary_is_drawn_by_its_own_presenter_and_is_its_own_kind():
    entry = ChangesEntry(id=1, files=(FileSummary("a.py", added=1),))

    assert type(DEFAULT_PRESENTERS.for_entry(entry)).__name__ == "ChangesPresenter"
