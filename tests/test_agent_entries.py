"""Typed transcript entries and their render caches."""

from dataclasses import fields

import pytest

from zettcode.app.agent.entries import (
    BaseEntry,
    EntryStatus,
    MarkdownEntry,
    ProcessingEntry,
    ThinkingEntry,
    ToolEntry,
)
from zettcode.app.agent.transcript import Transcript
from zettcode.tui import DARK, LIGHT, LineSource


def test_processing_becomes_thinking_without_losing_its_identity():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    pending = transcript.entries[-1]

    assert isinstance(pending, ProcessingEntry)
    transcript.start_thinking()
    thinking = transcript.entries[-1]

    assert isinstance(thinking, ThinkingEntry)
    assert thinking.id == pending.id
    assert thinking is transcript.entry(pending.id)
    assert transcript.start_thinking() is thinking


def test_markdown_entry_reuses_its_line_source_while_streaming():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.append_answer("first")
    answer = transcript.entries[-1]
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
    tool = transcript.entries[-1]
    assert isinstance(tool, ToolEntry)
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
