"""Render-cost tests: caching has to be observable, not just claimed."""

from __future__ import annotations

from time import perf_counter

from zettcode.app import Transcript, TranscriptSource
from zettcode.app.agent.conversation.entries import WaitEntry
from zettcode.app.agent.conversation.presenters import DEFAULT_PRESENTERS
from zettcode.app.agent.conversation.pulse import ANIMATION_SECONDS
from zettcode.tui import DARK
from zettcode.tui.widgets import markdown as markdown_module


def spy_on_entries(monkeypatch) -> list[int]:
    """Record which transcript entries get rendered.

    A render is a presenter's ``lines`` call: that is the work the look-keyed cache
    exists to avoid, so counting it is counting what the cache saved.
    """
    calls: list[int] = []
    for presenter in DEFAULT_PRESENTERS.presenters:
        owner = type(presenter)

        def spy(self, entry, width, theme, frame, _real=owner.lines):
            calls.append(entry.id)
            return _real(self, entry, width, theme, frame)

        monkeypatch.setattr(owner, "lines", spy)
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

    # The notice lands above the pinned wait row, which shifts down one index.
    # Only the notice is rendered: the view asks for the row again, and its
    # unchanged block comes back from the cache.
    assert transcript.entries[-1].kind == "wait"
    assert calls == [transcript.entries[-2].id]

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
    # Above the default display cap on purpose: this measures the cost of many
    # entries, and the cap would trim most of them away.
    transcript = Transcript(clock=lambda: 0.0, max_entries=4000)
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
    transcript = Transcript(clock=lambda: 0.0, max_entries=4000)
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


def test_ticks_within_one_animation_step_do_not_invalidate_the_transcript(monkeypatch):
    """A busy shell repaints far faster than the animation advances.

    Every version bump makes the view measure every entry again, so a frame
    that lands inside the step it already sits on must leave the version and
    the render cache untouched; otherwise the cost grows with the transcript.
    """
    calls = spy_on_entries(monkeypatch)
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("prompt")
    source = TranscriptSource(transcript, theme=DARK)
    source.count(40)

    calls.clear()
    version = transcript.version
    # Fifty ticks that together stay inside the step the transcript already sits on.
    for _ in range(50):
        now[0] += ANIMATION_SECONDS / 100
        transcript.advance_frame()
        source.count(40)

    assert transcript.version == version
    assert calls == []


def test_crossing_an_animation_step_repaints_only_the_running_row(monkeypatch):
    """One step forward updates the timer and re-renders just the live row."""
    calls = spy_on_entries(monkeypatch)
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("prompt")
    running = transcript.entries[-1]
    assert isinstance(running, WaitEntry)
    source = TranscriptSource(transcript, theme=DARK)
    source.count(40)

    calls.clear()
    now[0] = 2.5 * ANIMATION_SECONDS
    transcript.advance_frame()
    source.count(40)

    assert transcript.frame == 2
    assert running.duration == now[0]
    assert calls == [running.id]


def test_an_animation_step_without_a_running_row_leaves_the_version_alone():
    """A finished transcript has nothing to repaint, so a tick must not dirty it."""
    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("prompt")
    transcript.append_answer("done")
    transcript.settle_wait("Processed for 0s \u00b7 09:41")
    version = transcript.version

    now[0] = 10.5 * ANIMATION_SECONDS
    transcript.advance_frame()

    assert transcript.frame == 10
    assert transcript.version == version


def test_a_trim_rebuilds_the_view_aligned_with_the_remaining_entries():
    """Dropping the oldest entries must not leave the block index off by the trim."""
    transcript = Transcript(clock=lambda: 0.0, max_entries=32)
    source = TranscriptSource(transcript, theme=DARK)

    for index in range(100):
        transcript.notice(f"line {index}")
        source.count(40)

    rendered = "\n".join(source.line(index, 40).text for index in range(source.count(40)))
    assert "line 0" not in rendered
    assert "line 99" in rendered
    assert source.entry_at(0, 40) is transcript.entries[0]
