"""Render-cost tests: caching has to be observable, not just claimed."""

from __future__ import annotations

from time import perf_counter

from zettcode.app import Transcript, TranscriptSource
from zettcode.app.agent import blocks as blocks_module
from zettcode.tui import DARK
from zettcode.tui.widgets import markdown as markdown_module


def spy_on_entries(monkeypatch) -> list[int]:
    """Record which transcript entries get rendered."""
    calls: list[int] = []
    real = blocks_module.render_entry

    def spy(entry, width, theme, frame, *, processors):
        calls.append(entry.id)
        return real(entry, width, theme, frame, processors=processors)

    monkeypatch.setattr(blocks_module, "render_entry", spy)
    return calls


def test_only_new_entries_are_rendered_when_the_transcript_grows(monkeypatch):
    calls = spy_on_entries(monkeypatch)
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("one")
    transcript.notice("two")
    transcript.begin_turn("three")
    source = TranscriptSource(transcript, theme=DARK)

    source.count(40)
    assert calls == [entry.id for entry in transcript.entries]

    calls.clear()
    transcript.notice("four")
    source.count(40)
    assert calls == [transcript.entries[-1].id]

    calls.clear()
    source.count(40)
    source.line(0, 40)
    assert calls == []


def test_streaming_an_answer_never_re_renders_completed_entries(monkeypatch):
    calls = spy_on_entries(monkeypatch)
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("prompt")
    transcript.notice("note")
    source = TranscriptSource(transcript, theme=DARK)
    source.count(40)
    calls.clear()

    for index in range(40):
        transcript.append_answer(f"word{index} ")
        source.count(40)

    assert calls == []
    # The rows carry the composer's left margin, so stripping each line before
    # joining makes the check independent of where the text wrapped.
    rendered = "".join(source.line(index, 40).text.strip() for index in range(source.count(40)))
    assert "word39" in rendered


def test_streaming_markdown_only_reparses_the_open_block(monkeypatch):
    parsed: list[str] = []
    real = markdown_module.render_markdown

    def spy(text, width, theme=DARK):
        parsed.append(text)
        return real(text, width, theme)

    monkeypatch.setattr(markdown_module, "render_markdown", spy)
    document = markdown_module.Markdown()
    document.append("first block\n\n")
    for index in range(20):
        document.append(f"open tail {index}\n")
        document.lines(40)

    closed = [text for text in parsed if "first block" in text]

    assert len(closed) == 1


def test_first_paint_of_a_large_transcript_stays_bounded():
    transcript = Transcript(clock=lambda: 0.0)
    for index in range(2000):
        transcript.notice(f"line {index}")
    source = TranscriptSource(transcript, theme=DARK)

    start = perf_counter()
    total = source.count(80)
    for index in range(40):
        source.line(index, 80)
    first = perf_counter() - start

    assert total >= 4000
    assert first < 2.0


def test_painting_an_unchanged_frame_is_nearly_free():
    transcript = Transcript(clock=lambda: 0.0)
    for index in range(2000):
        transcript.notice(f"line {index}")
    source = TranscriptSource(transcript, theme=DARK)
    source.count(80)

    start = perf_counter()
    for _ in range(20):
        source.count(80)
        source.line(0, 80)
    elapsed = perf_counter() - start

    assert elapsed < 0.2
