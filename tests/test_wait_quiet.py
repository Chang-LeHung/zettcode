"""The waiting row says when the model has gone quiet — and only when the model is what is being waited for."""

from __future__ import annotations

import pytest

from zettcode.app import Transcript, TranscriptSource
from zettcode.app.agent.conversation.entries import EntryStatus, WaitEntry
from zettcode.app.agent.conversation.projection import TranscriptProjector
from zettcode.app.agent.conversation.text import QUIET_SECONDS, STOP_HINT, quiet_text
from zettcode.tui import DARK, SEPARATOR


def _rendered(transcript: Transcript, width: int = 90) -> str:
    source = TranscriptSource(transcript, theme=DARK)
    return "\n".join(source.line(index, width).text for index in range(source.count(width)))


def _wait_line(transcript: Transcript, width: int = 90) -> str:
    return next(line for line in _rendered(transcript, width).splitlines() if "Processing" in line)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def pass_seconds(self, transcript: Transcript, seconds: float) -> None:
        """Let time go by in whole seconds, drawing a frame at each, as the loop does."""
        for _ in range(int(seconds)):
            self.now += 1.0
            transcript.advance_frame()


@pytest.fixture
def run():
    clock = Clock()
    transcript = Transcript(clock=clock)
    transcript.begin_turn("question")
    return clock, transcript


# -- the words ----------------------------------------------------------------------------------------------------


def test_a_short_silence_is_not_worth_mentioning():
    assert quiet_text(0) is None and quiet_text(QUIET_SECONDS - 0.1) is None


def test_a_silence_at_the_threshold_and_beyond_is_said_in_the_waiting_rows_own_units():
    assert quiet_text(QUIET_SECONDS) == "nothing from the model for 20s"
    assert quiet_text(95) == "nothing from the model for 1m 35s"
    assert quiet_text(3725) == "nothing from the model for 1h 2m 5s"


# -- the row -----------------------------------------------------------------------------------------------------


def test_a_request_that_is_answered_promptly_never_mentions_silence(run):
    clock, transcript = run

    clock.pass_seconds(transcript, 10)

    assert _wait_line(transcript).endswith(f"(10s {SEPARATOR} {STOP_HINT})")


def test_after_twenty_silent_seconds_the_row_says_the_model_has_said_nothing(run):
    clock, transcript = run

    clock.pass_seconds(transcript, 25)

    assert f"(25s {SEPARATOR} nothing from the model for 25s {SEPARATOR} {STOP_HINT})" in _wait_line(transcript)


def test_the_silence_keeps_counting_as_the_wait_goes_on(run):
    clock, transcript = run
    clock.pass_seconds(transcript, 25)
    first = _wait_line(transcript)

    clock.pass_seconds(transcript, 40)

    assert "for 25s" in first and "for 1m 5s" in _wait_line(transcript)


def test_the_row_still_names_the_key_that_stops_the_request_when_it_is_warning(run):
    clock, transcript = run

    clock.pass_seconds(transcript, 30)

    assert STOP_HINT in _wait_line(transcript, 120)


def test_the_warning_is_painted_in_the_warning_colour_and_the_rest_stays_quiet(run):
    clock, transcript = run
    clock.pass_seconds(transcript, 30)
    source = TranscriptSource(transcript, theme=DARK)
    spans = next(
        source.line(index, 120).spans
        for index in range(source.count(120))
        if "Processing" in source.line(index, 120).text
    )

    said = next(span for span in spans if "nothing from the model" in span.text)
    quiet = next(span for span in spans if span.text.strip().startswith("(30s"))

    assert said.style.foreground == DARK.warning and quiet.style.foreground == DARK.muted


def test_each_thing_the_agent_says_ends_the_silence(run):
    clock, transcript = run
    clock.pass_seconds(transcript, 25)
    assert "nothing from the model" in _wait_line(transcript)

    transcript.heard()
    clock.pass_seconds(transcript, 1)

    assert "nothing from the model" not in _wait_line(transcript)
    clock.pass_seconds(transcript, 18)
    assert "nothing from the model" not in _wait_line(transcript), (
        "19 seconds since it last spoke, not 44 since the start"
    )
    clock.pass_seconds(transcript, 3)
    assert "nothing from the model for 22s" in _wait_line(transcript)


def test_a_command_that_runs_for_minutes_is_not_the_model_going_quiet(run):
    clock, transcript = run
    transcript.start_tool("t1", "bash", {"command": "pytest"})
    transcript.heard()

    clock.pass_seconds(transcript, 120)

    assert "nothing from the model" not in _wait_line(transcript)
    assert transcript.entries[-1].quiet == 0.0


def test_the_silence_is_counted_again_once_the_command_is_over(run):
    clock, transcript = run
    transcript.start_tool("t1", "bash", {"command": "pytest"})
    clock.pass_seconds(transcript, 100)
    transcript.complete_tool("t1", "ok")
    transcript.heard()

    clock.pass_seconds(transcript, 22)

    assert "nothing from the model for 22s" in _wait_line(transcript)


def test_reasoning_that_is_streaming_is_not_silence(run):
    clock, transcript = run
    transcript.start_thinking()
    transcript.heard()

    clock.pass_seconds(transcript, 60)

    assert "nothing from the model" not in _wait_line(transcript)


def test_a_compaction_in_flight_is_waited_for_in_its_own_row(run):
    clock, transcript = run
    transcript.start_compaction()

    clock.pass_seconds(transcript, 60)

    assert "nothing from the model" not in _wait_line(transcript)


def test_a_settled_row_says_nothing_about_silence(run):
    clock, transcript = run
    clock.pass_seconds(transcript, 40)

    transcript.settle_wait("Processed for 40s")

    assert "nothing from the model" not in _rendered(transcript)
    wait = next(entry for entry in transcript.entries if isinstance(entry, WaitEntry))
    assert wait.status is not EntryStatus.RUNNING


def test_hearing_with_no_request_running_does_nothing_and_does_not_fail():
    transcript = Transcript(clock=Clock())

    transcript.heard()

    assert transcript.entries == []


def test_hearing_changes_nothing_a_reader_could_see_so_it_moves_no_version(run):
    _, transcript = run
    before = transcript.version

    transcript.heard()

    assert transcript.version == before


# -- who calls it ---------------------------------------------------------------------------------------------------


async def test_every_event_the_agent_emits_ends_a_silence_through_the_projector(run):
    from zett_agent.events import AgentEvent, AgentEventType

    clock, transcript = run
    projector = TranscriptProjector(transcript)
    clock.pass_seconds(transcript, 25)
    assert "nothing from the model" in _wait_line(transcript)

    await projector.dispatch(AgentEvent(type=AgentEventType.MODEL_STARTED, session_id="s"))
    clock.pass_seconds(transcript, 1)

    assert "nothing from the model" not in _wait_line(transcript)


async def test_a_text_delta_is_heard_as_well_as_drawn(run):
    from zett_agent.events import AgentEvent, AgentEventType

    clock, transcript = run
    projector = TranscriptProjector(transcript)

    clock.pass_seconds(transcript, 15)
    await projector.dispatch(AgentEvent(type=AgentEventType.TEXT_DELTA, session_id="s", delta="Hel"))
    clock.pass_seconds(transcript, 15)

    assert "nothing from the model" not in _wait_line(transcript), "15 seconds since the last word"
    assert "Hel" in _rendered(transcript)


def test_two_moments_that_differ_only_in_the_silence_are_not_the_same_picture(run):
    """The loop skips a frame whose picture repeats the last; a warning that should go must not be skipped."""
    from zettcode.app.agent.conversation.transcript import Transcript as T

    clock, transcript = run
    wait = next(entry for entry in transcript.entries if isinstance(entry, WaitEntry))
    quiet, heard = wait, WaitEntry(id=99, started_at=wait.started_at)
    quiet.quiet, heard.quiet = 25.0, 0.0

    assert T._picture(7, clock.now, [quiet]) != T._picture(7, clock.now, [heard])
    heard.quiet = 21.0
    assert T._picture(7, clock.now, [quiet]) != T._picture(7, clock.now, [heard]), "25s and 21s read differently"
    heard.quiet = 5.0
    quiet.quiet = 6.0
    assert T._picture(7, clock.now, [quiet]) == T._picture(7, clock.now, [heard]), "below the threshold nothing is said"


# -- a request that ended having produced nothing ----------------------------------------------------------------


def test_a_request_with_nothing_in_it_said_nothing(run):
    _, transcript = run

    assert transcript.turn_said_nothing() is True


def test_a_notice_alone_is_not_an_answer(run):
    """An MCP server starting is news about the request, not what the model sent back."""
    _, transcript = run
    transcript.notice("Starting MCP server 'docs' (process)\u2026")

    assert transcript.turn_said_nothing() is True


@pytest.mark.parametrize("kind", ["answer", "tool", "thinking"])
def test_an_answer_a_tool_or_reasoning_is_something(run, kind):
    _, transcript = run
    if kind == "answer":
        transcript.append_answer("Hello")
    elif kind == "tool":
        transcript.start_tool("t", "read_file", {"path": "a.py"})
    else:
        transcript.start_thinking()

    assert transcript.turn_said_nothing() is False


def test_only_this_requests_rows_count_not_an_earlier_ones(run):
    clock, transcript = run
    transcript.append_answer("an earlier answer")
    transcript.settle_wait("Processed for 1s")
    transcript.begin_turn("next question")

    assert transcript.turn_said_nothing() is True
