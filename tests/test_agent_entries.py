"""Typed transcript entries and their render caches."""

import inspect
from dataclasses import fields

import pytest

from zettcode.app.agent.conversation.entries import (
    Entry,
    EntryKind,
    EntryStatus,
    MarkdownEntry,
    NoticeLevel,
    TextEntry,
    ThinkingEntry,
    TimedEntry,
    ToolEntry,
    WaitEntry,
)
from zettcode.app.agent.conversation.presenters import block_for
from zettcode.app.agent.conversation.rows import move_frames
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.tui import DARK, LIGHT, LineSource


def test_the_transcript_drops_the_oldest_entries_at_the_display_cap():
    """A long session keeps a bounded scrollback, without losing the newest rows."""
    transcript = Transcript(clock=lambda: 0.0, max_entries=32)

    for index in range(100):
        transcript.notice(f"line {index}")

    texts = [entry.text for entry in transcript.entries]
    assert texts[-1] == "line 99"
    assert "line 0" not in texts
    assert len(texts) <= 32 + max(8, 32 // 32)


def test_the_wait_row_is_pinned_under_every_row_the_reply_produces():
    """Reasoning, tools, and the answer land above it; the row itself stays put.

    It is the last entry for as long as the request runs, and nothing promotes
    it into the reasoning row or drops it when the answer starts: the one line
    that says work is going on has to stay where the reader is looking.
    """
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    pending = transcript.entries[-1]

    assert isinstance(pending, WaitEntry)
    thinking = transcript.start_thinking()

    assert isinstance(thinking, ThinkingEntry) and thinking is not pending
    assert transcript.entries[-1] is pending
    assert [entry.kind for entry in transcript.entries] == ["user", "thinking", "wait"]

    transcript.start_tool("call-1", "read_file", {"path": "app.py"})
    transcript.append_answer("an answer")

    assert [entry.kind for entry in transcript.entries] == ["user", "thinking", "tool", "answer", "wait"]
    assert transcript.entries[-1] is pending
    assert pending.status is EntryStatus.RUNNING


def test_settling_the_wait_row_writes_the_line_the_request_ended_on():
    """It keeps its place, takes the elapsed time it measured, and stops running."""
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("question")
    transcript.append_answer("an answer")
    now[0] = 12.5

    assert transcript.settle_wait("Processed for 12s · 09:41") is True

    row = transcript.entries[-1]
    assert isinstance(row, WaitEntry)
    assert row.status is EntryStatus.COMPLETED
    assert row.text == "Processed for 12s · 09:41"
    assert row.duration == 12.5
    # Settling is once per request: there is nothing left to settle.
    assert transcript.settle_wait("again") is False


def test_markdown_entry_reuses_its_line_source_while_streaming():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.append_answer("first")
    # The answer is the entry above the pinned wait row, which stays last.
    answer = transcript.entries[-2]
    assert isinstance(answer, MarkdownEntry)

    source = block_for(answer, 24, DARK, frame=0)
    transcript.append_answer(" second")

    assert isinstance(source, LineSource)
    assert block_for(answer, 24, DARK, frame=100) is source
    assert "first second" in "\n".join(source.line(index, 24).text for index in range(source.count(24)))
    assert block_for(answer, 12, LIGHT, frame=200) is source


def test_tool_statuses_are_enum_values_and_validate_before_mutating():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.start_tool("call-1", "read_file", {"path": "app.py"})
    tool = next(entry for entry in transcript.entries if isinstance(entry, ToolEntry))
    assert tool.status is EntryStatus.RUNNING

    with pytest.raises(ValueError):
        transcript.complete_tool("call-1", "result", status="unknown")
    assert tool.text == ""
    assert tool.status is EntryStatus.RUNNING

    transcript.complete_tool("call-1", "not found", status="failed")
    assert tool.status is EntryStatus.FAILED
    assert transcript.toggle(tool.id)


def test_entry_constructors_convert_known_statuses_and_reject_unknown_ones():
    assert ThinkingEntry(id=1, status="completed").status is EntryStatus.COMPLETED
    assert WaitEntry(id=2, started_at=0.0, status="running").status is EntryStatus.RUNNING
    with pytest.raises(ValueError):
        ToolEntry(id=3, call_id="call-3", tool="read_file", title="Read app.py", status="unknown")


def test_a_kind_is_given_by_the_class_that_has_one_and_by_the_caller_that_does_not():
    """A wait, reasoning, or tool row is one kind of thing; a text or Markdown row is several.

    The first three declare their kind once, as a field that is not a constructor
    argument; the other two take it, because one class serves several kinds. Either
    way it is an :class:`EntryKind`, and still compares equal to its plain word.
    """
    for fixed in (WaitEntry, ThinkingEntry, ToolEntry):
        assert "kind" in {field.name for field in fields(fixed)}
        assert "kind" not in inspect.signature(fixed).parameters, fixed.__name__
    for chosen in (TextEntry, MarkdownEntry):
        assert "kind" in inspect.signature(chosen).parameters, chosen.__name__

    assert WaitEntry(id=1, started_at=0.0).kind is EntryKind.WAIT
    assert ThinkingEntry(id=2).kind is EntryKind.THINKING
    assert ToolEntry(id=3, call_id="call-3", tool="read_file", title="Read app.py").kind is EntryKind.TOOL
    assert WaitEntry(id=4, started_at=0.0).kind == "wait"
    assert TextEntry(id=5, kind="user", text="hi").kind is EntryKind.USER, "a plain word is accepted"


def test_a_kind_that_is_not_a_kind_is_refused_and_so_is_one_the_class_cannot_be():
    with pytest.raises(ValueError):
        TextEntry(id=1, kind="other", text="x")
    with pytest.raises(ValueError, match="not plain text"):
        TextEntry(id=2, kind=EntryKind.TOOL, text="x")
    with pytest.raises(ValueError, match="not Markdown"):
        MarkdownEntry(id=3, kind=EntryKind.USER)
    with pytest.raises(ValueError):
        TextEntry(id=4, kind="notice", text="x", level="loud")
    assert TextEntry(id=5, kind="notice", text="x", level="error").level is NoticeLevel.ERROR


def test_the_rows_that_take_time_share_one_base_and_one_idea_of_running():
    """The wait row, reasoning, and a tool call are the same kind of thing to the transcript.

    Which is why one ``isinstance`` and one ``running`` stand where the same pair of
    classes used to be listed in four places.
    """
    rows = (
        WaitEntry(id=1, started_at=0.0),
        ThinkingEntry(id=2),
        ToolEntry(id=3, call_id="c", tool="bash", title="Ran ls"),
    )
    assert all(isinstance(row, TimedEntry) and row.running for row in rows)
    assert not isinstance(TextEntry(id=4, kind="notice", text="x"), TimedEntry)
    for row in rows:
        row.status = EntryStatus.COMPLETED
        assert not row.running


def test_static_entry_cache_does_not_rebuild_on_animation_frames():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.notice("ready")
    notice = transcript.entries[-1]

    first = block_for(notice, 20, DARK, frame=0)
    assert isinstance(first, LineSource)
    assert block_for(notice, 20, DARK, frame=100) is first
    assert block_for(notice, 20, LIGHT, frame=100) is not first


def _painted(entry: Entry, *, frame: int = 0, width: int = 48) -> list[str]:
    """Return the entry's rendered rows, styles included, at one frame."""
    block = block_for(entry, width, DARK, frame=frame)
    return [repr(block.line(index, width)) for index in range(block.count(width))]


def test_a_text_row_rebuilds_when_its_text_or_level_changes():
    """The cache key holds every field the notice renderer reads."""
    entry = TextEntry(id=1, kind="notice", text="ready")
    before = _painted(entry)
    entry.text = "done"
    assert _painted(entry) != before

    entry = TextEntry(id=2, kind="notice", text="failed")
    before = _painted(entry)
    entry.level = "error"
    assert _painted(entry) != before


def test_a_processing_row_rebuilds_for_its_title_timer_and_frame():
    """A waiting row must repaint for the label, the timer, and the sweep."""
    entry = WaitEntry(id=1, started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.title = "Waiting"
    assert _painted(entry) != before

    entry = WaitEntry(id=2, started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.duration = 2.0
    assert _painted(entry) != before

    entry = WaitEntry(id=3, started_at=0.0)
    # Half way through the sweep, not one step on: a step is a hundred-and-twentieth of a
    # second, and the highlight has not yet moved a column.
    assert _painted(entry, frame=move_frames() // 2) != _painted(entry, frame=0)


def test_a_thinking_row_rebuilds_for_expansion_text_status_and_timer():
    """Reasoning is collapsible, timed, and still, so the frame is not keyed."""
    entry = ThinkingEntry(id=1, text="reasoning", started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.expanded = True
    assert _painted(entry) != before

    entry = ThinkingEntry(id=2, text="reasoning", expanded=True)
    before = _painted(entry)
    entry.text = "more reasoning"
    assert _painted(entry) != before

    entry = ThinkingEntry(id=3, text="reasoning", started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.status = EntryStatus.COMPLETED
    assert _painted(entry) != before

    # Only the waiting row sweeps, so a step through the transcript leaves a
    # running reasoning row exactly as it was.
    entry = ThinkingEntry(id=4, text="reasoning", started_at=0.0)
    assert _painted(entry, frame=1) == _painted(entry, frame=0)


def test_a_running_reasoning_or_tool_row_is_not_rebuilt_by_an_animation_step():
    """The frame is not in their key, because it is not in what they paint.

    A reasoning row and a running tool row are painted flat, so a step that
    moves only the waiting row must leave their cached block alone; the waiting
    row itself has to rebuild, which is the half that keeps the sweep honest.
    """
    thinking = ThinkingEntry(id=1, text="reasoning", started_at=0.0, duration=1.0)
    tool = ToolEntry(id=2, call_id="c1", tool="read_file", title="Read app.py", started_at=0.0, duration=1.0)
    waiting = WaitEntry(id=3, started_at=0.0, duration=1.0)

    thinking_block = block_for(thinking, 48, DARK, frame=0)
    tool_block = block_for(tool, 48, DARK, frame=0)
    waiting_block = block_for(waiting, 48, DARK, frame=0)

    assert block_for(thinking, 48, DARK, frame=1) is thinking_block
    assert block_for(tool, 48, DARK, frame=1) is tool_block
    assert block_for(waiting, 48, DARK, frame=1) is not waiting_block


def test_a_step_brings_up_every_running_row_even_around_a_notice():
    """A notice lands beside the call it answered; it must not stop the walk.

    An approval or a command notice is inserted between the rows that are still
    running and the pinned wait row, and a batch's results can arrive out of
    order, so a walk that stopped at the first entry that was not a running row
    would leave a timer frozen at the moment the notice landed.
    """
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("question")
    transcript.start_tool("1", "read_file", {"path": "a.py"})
    transcript.start_tool("2", "read_file", {"path": "b.py"})
    now[0] = 1.0
    transcript.advance_frame()
    tools = [entry for entry in transcript.entries if isinstance(entry, ToolEntry)]
    assert [entry.duration for entry in tools] == [1.0, 1.0]

    transcript.notice("auto mode on for this run")
    transcript.complete_tool("2", "b content", wait=False)
    now[0] = 6.0
    transcript.advance_frame()

    # The call whose result never came is still counting; the one that answered
    # stays where it finished, and the pinned row counts the whole request.
    assert [entry.duration for entry in tools] == [6.0, 1.0]
    assert transcript.entries[-1].duration == 6.0


class _CountedEntries(list):
    """A transcript's entry list that records how many entries were read."""

    def __init__(self, entries: list[Entry]) -> None:
        super().__init__(entries)
        self.reads = 0

    def __getitem__(self, index):
        self.reads += 1
        return super().__getitem__(index)


def test_an_animation_step_reads_only_the_rows_of_this_request():
    """The walk is bounded by the request, so a step's cost is flat in the session.

    No behavioural test can tell two bounds apart — skipping a notice reads the
    same as never reaching it — so this counts what one step looks at: fifty
    rows of history must not be re-read ten times a second.
    """
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    for index in range(50):
        transcript.notice(f"line {index}")
    transcript.begin_turn("question")
    entries = _CountedEntries(transcript.entries)
    transcript.entries = entries

    now[0] = 1.0
    transcript.advance_frame()

    # One read of the list, which is the pinned row: the walk never reaches the
    # fifty notices behind it. The count covers every read of the list, so a
    # peek at the tail anywhere in a step would fail this too.
    assert entries.reads == 1


def test_a_settled_wait_row_is_not_rebuilt_by_an_animation_step():
    """A settled row is dead text: the frame is not part of what it draws."""
    row = WaitEntry(
        id=1,
        started_at=0.0,
        duration=1.0,
        text="Processed for 1.0 s \u00b7 09:41",
        status=EntryStatus.COMPLETED,
    )
    first = block_for(row, 48, DARK, frame=0)

    assert block_for(row, 48, DARK, frame=1) is first


def test_a_tool_row_rebuilds_for_every_field_the_renderer_reads():
    """The tool row's words, body, state, and language are all keyed."""
    entry = ToolEntry(id=1, call_id="c1", tool="read_file", title="Read app.py")
    before = _painted(entry)
    entry.title = "Read main.py"
    assert _painted(entry) != before

    # A running row refuses to open, so expansion is observed on a settled row.
    entry = ToolEntry(
        id=2,
        call_id="c2",
        tool="read_file",
        title="Read app.py",
        text="print(1)",
        status=EntryStatus.COMPLETED,
    )
    before = _painted(entry)
    entry.expanded = True
    assert _painted(entry) != before

    entry = ToolEntry(
        id=3,
        call_id="c3",
        tool="read_file",
        title="Read app.py",
        expanded=True,
        status=EntryStatus.COMPLETED,
    )
    before = _painted(entry)
    entry.text = "print(2)"
    assert _painted(entry) != before

    entry = ToolEntry(id=6, call_id="c6", tool="replace_in_file", title="Edited app.py", status=EntryStatus.COMPLETED)
    before = _painted(entry)
    entry.added, entry.removed = 12, 3
    assert _painted(entry) != before, "the counts change what the row looks like"

    entry = ToolEntry(id=4, call_id="c4", tool="read_file", title="Read app.py", started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.status = EntryStatus.COMPLETED
    assert _painted(entry) != before

    entry = ToolEntry(
        id=5,
        call_id="c5",
        tool="read_file",
        title="Read app.py",
        text="x = 1",
        expanded=True,
        language="python",
        status=EntryStatus.COMPLETED,
    )
    before = _painted(entry)
    entry.language = None
    assert _painted(entry) != before

    entry = ToolEntry(id=6, call_id="c6", tool="read_file", title="Read app.py", started_at=0.0)
    assert _painted(entry, frame=1) == _painted(entry, frame=0)
