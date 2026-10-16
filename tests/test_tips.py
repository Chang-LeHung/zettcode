"""The tips under the waiting row: when they appear, how they change, and that each is true of this program."""

from __future__ import annotations

import re

import pytest

from zettcode.app import Transcript, TranscriptSource
from zettcode.app.agent.conversation.rows import TIP_AFTER, TIP_EVERY, tip_text
from zettcode.app.agent.conversation.tips import TIPS, TipDeck
from zettcode.tui import DARK

A, B, C = "first tip", "second tip", "third tip"


def _rendered(transcript: Transcript, width: int = 90) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(index, width).text.rstrip() for index in range(source.count(width))]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def pass_seconds(self, transcript: Transcript, seconds: int) -> None:
        for _ in range(seconds):
            self.now += 1.0
            transcript.advance_frame()


def _running(tips=(A, B, C), *, width: int = 90):
    clock = Clock()
    transcript = Transcript(clock=clock)
    transcript.tip_deck = TipDeck(tips, shuffle=lambda items: None)
    transcript.begin_turn("question")
    return clock, transcript


# -- when a tip is shown -----------------------------------------------------------------------------------------


def test_no_tip_is_shown_until_the_request_has_run_for_a_few_seconds():
    assert tip_text((A, B), 0) is None and tip_text((A, B), TIP_AFTER - 0.1) is None
    assert tip_text((A, B), TIP_AFTER) == A


def test_no_tip_when_there_are_none_or_the_time_is_not_known():
    assert tip_text((), 100) is None and tip_text((A,), None) is None


def test_each_tip_stays_for_a_while_and_they_come_round_again():
    assert [tip_text((A, B, C), TIP_AFTER + TIP_EVERY * n + 1) for n in range(5)] == [A, B, C, A, B]
    assert tip_text((A, B, C), TIP_AFTER + TIP_EVERY - 0.1) == A


# -- what is drawn ------------------------------------------------------------------------------------------------


def test_the_tip_stands_under_the_waiting_row_once_it_is_time_and_not_before():
    clock, transcript = _running()

    clock.pass_seconds(transcript, int(TIP_AFTER) - 1)
    assert not any("Tip:" in line for line in _rendered(transcript))

    clock.pass_seconds(transcript, 2)
    rows = _rendered(transcript)
    waiting = next(i for i, line in enumerate(rows) if "Processing" in line)
    assert rows[waiting + 1] == f"  \u2514 Tip: {A}", "directly under it, hung from a hook like a tool's result"


def test_the_tip_is_replaced_by_the_next_as_the_request_goes_on():
    clock, transcript = _running()

    clock.pass_seconds(transcript, int(TIP_AFTER + TIP_EVERY) + 2)

    text = "\n".join(_rendered(transcript))
    assert f"Tip: {B}" in text and f"Tip: {A}" not in text


def test_a_tip_is_one_more_line_in_the_quiet_ink_and_changes_nothing_else_about_the_row():
    clock, transcript = _running()
    clock.pass_seconds(transcript, 3)
    before = _rendered(transcript)
    clock.pass_seconds(transcript, 4)
    after = _rendered(transcript)

    assert len(after) == len(before) + 1
    source = TranscriptSource(transcript, theme=DARK)
    tip_row = next(source.line(i, 90) for i in range(source.count(90)) if "Tip:" in source.line(i, 90).text)
    assert {span.style.foreground for span in tip_row.spans if span.text.strip()} == {DARK.muted}


def test_a_tip_is_hung_the_way_a_tools_result_is_with_the_same_hook_and_indent():
    from zettcode.app.agent.conversation.rows import CONTENT_INDENT

    clock, transcript = _running(("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",))
    clock.pass_seconds(transcript, 7)

    rows = [line for line in _rendered(transcript, 30) if line.strip()]

    tip = rows[rows.index(next(r for r in rows if "Tip:" in r)) :]
    assert tip[0].startswith(" " * CONTENT_INDENT + "\u2514 Tip:")
    assert all(
        r.startswith(" " * CONTENT_INDENT * 2) and not r.startswith(" " * (CONTENT_INDENT * 2 + 1)) for r in tip[1:]
    )


def test_a_tip_longer_than_the_row_wraps_between_words_and_keeps_its_inset():
    clock, transcript = _running(("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",))
    clock.pass_seconds(transcript, 7)

    rows = [line for line in _rendered(transcript, 30) if line.strip()]

    tip = rows[rows.index(next(r for r in rows if "Tip:" in r)) :]
    assert len(tip) > 1 and all(len(r) <= 30 for r in tip)
    assert len({len(r) - len(r.lstrip()) for r in tip[1:]}) == 1, "the rows after the first line up under its text"


def test_a_settled_row_keeps_no_tip():
    clock, transcript = _running()
    clock.pass_seconds(transcript, 8)
    assert any("Tip:" in line for line in _rendered(transcript))

    transcript.settle_wait("Processed for 8s")

    assert not any("Tip:" in line for line in _rendered(transcript))


def test_without_a_deck_nothing_is_shown_however_long_it_takes():
    clock = Clock()
    transcript = Transcript(clock=clock)
    transcript.begin_turn("question")

    clock.pass_seconds(transcript, 40)

    assert not any("Tip:" in line for line in _rendered(transcript))


def test_a_tip_that_appears_is_a_change_the_loop_draws_and_a_second_that_repeats_it_is_not():
    clock, transcript = _running()
    clock.pass_seconds(transcript, int(TIP_AFTER) - 1)

    clock.now += 1.0
    assert transcript.advance_frame() is True, "the tip is new on screen"
    version = transcript.version
    clock.now += 0.01
    transcript.advance_frame()
    assert transcript.version == version, "a step inside the same second draws nothing new"


# -- the deck ---------------------------------------------------------------------------------------------------


def test_each_request_begins_one_tip_further_along_and_all_the_tips_are_in_every_request():
    deck = TipDeck((A, B, C), shuffle=lambda items: None)

    assert deck.next() == (A, B, C)
    assert deck.next() == (B, C, A)
    assert deck.next() == (C, A, B)
    assert deck.next() == (A, B, C), "and round again"


def test_the_order_is_chosen_once_when_the_deck_is_made():
    deck = TipDeck((A, B, C), shuffle=lambda items: items.reverse())

    assert deck.next() == (C, B, A)


def test_an_empty_deck_hands_out_nothing():
    assert TipDeck((), shuffle=lambda items: None).next() == ()


def test_the_real_deck_is_shuffled_and_hands_out_every_tip():
    assert sorted(TipDeck().next()) == sorted(TIPS)


# -- the tips themselves ------------------------------------------------------------------------------------------


def test_the_tips_are_unique_single_sentences_short_enough_to_read_in_a_glance():
    assert len(set(TIPS)) == len(TIPS) >= 15
    for tip in TIPS:
        assert tip == tip.strip() and "\n" not in tip and tip.endswith("."), tip
        assert len(tip) <= 110, f"too long: {tip}"


def test_every_command_a_tip_names_is_one_the_shell_has():
    from test_zettcode_app import build_app

    names = {command.name for command in build_app().commands}
    named = {name for tip in TIPS for name in re.findall(r"(?<![\w/])(/[a-z][a-z-]*)", tip)}

    assert named, "the tips do mention commands"
    assert named <= names, f"not commands: {sorted(named - names)}"


@pytest.mark.parametrize("tip", [t for t in TIPS if "tips = false" in t])
def test_the_tip_that_says_how_to_turn_tips_off_names_a_key_the_configuration_reads(tip):
    from zettcode.config import TRANSCRIPT_KEYS

    assert "tips" in TRANSCRIPT_KEYS and "[transcript]" in tip


def test_the_moments_a_tip_changes_are_whole_seconds_because_the_loop_draws_a_new_picture_only_on_one():
    assert TIP_AFTER == int(TIP_AFTER) and TIP_EVERY == int(TIP_EVERY)
