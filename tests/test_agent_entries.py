"""Typed transcript entries and their render caches."""

from dataclasses import fields

import pytest

from zettcode.app.agent.entries import (
    BaseEntry,
    Entry,
    EntryStatus,
    MarkdownEntry,
    ProcessingEntry,
    TextEntry,
    ThinkingEntry,
    ToolEntry,
)
from zettcode.app.agent.transcript import Transcript
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

    assert isinstance(pending, ProcessingEntry)
    thinking = transcript.start_thinking()

    assert isinstance(thinking, ThinkingEntry) and thinking is not pending
    assert transcript.entries[-1] is pending
    assert [entry.kind for entry in transcript.entries] == ["user", "thinking", "pending"]

    transcript.start_tool("call-1", "read_file", {"path": "app.py"})
    transcript.append_answer("an answer")

    assert [entry.kind for entry in transcript.entries] == ["user", "thinking", "tool", "answer", "pending"]
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
    assert isinstance(row, ProcessingEntry)
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

    source = answer.block_for(24, DARK, frame=0)
    transcript.append_answer(" second")

    assert isinstance(source, LineSource)
    assert answer.block_for(24, DARK, frame=100) is source
    assert "first second" in "\n".join(source.line(index, 24).text for index in range(source.count(24)))
    assert answer.block_for(12, LIGHT, frame=200) is source


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
    assert ProcessingEntry(id=2, started_at=0.0, status="running").status is EntryStatus.RUNNING
    with pytest.raises(ValueError):
        ToolEntry(id=3, call_id="call-3", tool="read_file", title="Read app.py", status="unknown")


def test_kind_lives_on_the_base_or_as_a_fixed_class_value():
    assert "kind" in {field.name for field in fields(BaseEntry)}
    assert "kind" not in {field.name for field in fields(ProcessingEntry)}
    assert "kind" not in {field.name for field in fields(ThinkingEntry)}
    assert "kind" not in {field.name for field in fields(ToolEntry)}
    assert ProcessingEntry(id=1, started_at=0.0).kind == "pending"
    assert ThinkingEntry(id=2).kind == "thinking"
    assert ToolEntry(id=3, call_id="call-3", tool="read_file", title="Read app.py").kind == "tool"


def test_static_entry_cache_does_not_rebuild_on_animation_frames():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.notice("ready")
    notice = transcript.entries[-1]

    first = notice.block_for(20, DARK, frame=0)
    assert isinstance(first, LineSource)
    assert notice.block_for(20, DARK, frame=100) is first
    assert notice.block_for(20, LIGHT, frame=100) is not first


def _painted(entry: Entry, *, frame: int = 0, width: int = 48) -> list[str]:
    """Return the entry's rendered rows, styles included, at one frame."""
    block = entry.block_for(width, DARK, frame=frame)
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
    entry = ProcessingEntry(id=1, started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.title = "Waiting"
    assert _painted(entry) != before

    entry = ProcessingEntry(id=2, started_at=0.0, duration=1.0)
    before = _painted(entry)
    entry.duration = 2.0
    assert _painted(entry) != before

    entry = ProcessingEntry(id=3, started_at=0.0)
    assert _painted(entry, frame=1) != _painted(entry, frame=0)


def test_a_thinking_row_rebuilds_for_expansion_text_status_timer_and_frame():
    """Reasoning is collapsible, timed, and animated, so all of it is keyed."""
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

    entry = ThinkingEntry(id=4, text="reasoning", started_at=0.0)
    assert _painted(entry, frame=1) != _painted(entry, frame=0)


def test_a_tool_row_rebuilds_for_every_field_the_renderer_reads():
    """The tool row's words, body, state, language, and sweep are all keyed."""
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
    assert _painted(entry, frame=1) != _painted(entry, frame=0)
