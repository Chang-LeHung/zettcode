"""A frame that would only repeat the last one is not painted, and nothing the reader sees changes."""

from __future__ import annotations

import re
from io import StringIO

import pytest

from zettcode.app.agent.conversation.entries import EntryStatus, WaitEntry
from zettcode.app.agent.conversation.presenters import _running_label
from zettcode.app.agent.conversation.rows import (
    ANIMATION_FPS,
    ANIMATION_SECONDS,
    PULSE_FRAMES,
    RUNNING_GLYPHS,
    STATUS_BLINK_FRAMES,
    WAIT_RAMP,
    activity_glyph,
    blink_state,
    sweep_column,
    wait_picture,
)
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.tui import DARK, ColorDepth, Style, Terminal, TerminalCapabilities, TuiApp, Widget
from zettcode.tui.core.scheduler import Scheduler
from zettcode.tui.render import SweepSpan
from zettcode.tui.runner import TerminalRunner

FRAME = 1 / ANIMATION_FPS


class Clock:
    """A hand-driven clock shared by the transcript, the app and the scheduler."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class StubTerminal(Terminal):
    """A terminal that keeps what it was sent, so two runs can be compared byte for byte."""

    def __init__(self, width: int = 60, height: int = 14) -> None:
        super().__init__(
            input_fd=-1,
            output=StringIO(),
            capabilities=TerminalCapabilities(color_depth=ColorDepth.TRUECOLOR, width=width, height=height),
        )
        self._size = (width, height)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def write(self, value: str) -> None:
        self.output.write(value)


_CURSOR = re.compile(r"(\x1b\[\d+;\d+H\x1b\[\?25h)(?:\1)+")


def _sent(terminal: StubTerminal) -> str:
    """What the terminal was sent, with a cursor placement that merely repeats the one before it folded.

    The renderer places the cursor after every frame it writes, empty or not, so a run that paints
    every frame sends the same placement again and again. A terminal ignores the repeats; a run that
    skips frames sends fewer of them, and that is the only difference the two may have.
    """
    return _CURSOR.sub(r"\1", terminal.output.getvalue())


def _spans(title_width: int, frame: int) -> tuple[tuple[str, object], ...]:
    """What the waiting row's label is drawn as at one frame: text and style, run by run."""
    return tuple((span.text, span.style) for span in _running_label("x" * title_width, DARK, frame))


# -- the picture is a faithful name for what is drawn ------------------------------------------------


@pytest.mark.parametrize("title_width", [1, 4, 10, 11, 25])
def test_two_frames_with_the_same_picture_are_drawn_the_same_and_two_with_different_ones_are_not(title_width):
    """The skip is only safe if equal pictures mean equal pixels. It is only worth having if most
    different pictures look different; both are checked over two whole pulses."""
    drawn: dict[tuple[bool, int], set[tuple[tuple[str, object], ...]]] = {}
    for frame in range(2 * PULSE_FRAMES):
        drawn.setdefault(wait_picture(frame, title_width), set()).add(_spans(title_width, frame))

    assert all(len(variants) == 1 for variants in drawn.values()), "one picture, one drawing: skipping is safe"
    everything = {next(iter(variants)) for variants in drawn.values()}
    # The other direction is only about whether skipping is worth it, and it is not exact: the
    # highlight is symmetrical, so a word one column wide looks the same with it a column to the
    # left as a column to the right. No drawing is shared by more than two pictures.
    assert len(everything) * 2 >= len(drawn), f"{len(drawn)} pictures but only {len(everything)} drawings"


def test_a_pulse_has_a_few_dozen_pictures_not_a_hundred_and_eighty():
    """The measured reason for all of this: most frames repeat the one before."""
    pictures = {wait_picture(frame, 10) for frame in range(PULSE_FRAMES)}

    assert len(pictures) < PULSE_FRAMES // 3, f"{len(pictures)} pictures in {PULSE_FRAMES} frames"
    assert (False, 0) in pictures, "and the rest is one picture, however long it lasts"


@pytest.mark.parametrize("title_width", [1, 10, 25])
def test_the_presenter_and_the_picture_agree_on_how_far_a_pass_travels(title_width):
    """`wait_picture` counts with the ramp the presenter draws with, so they cannot drift apart."""
    label = SweepSpan("x" * title_width, Style(foreground=DARK.accent_bright), ramp=WAIT_RAMP)

    assert label.travel == title_width + 2 * WAIT_RAMP
    assert wait_picture(1, title_width) == (True, sweep_column(1, label.travel))


def test_the_icon_is_in_the_state_the_blink_says():
    for frame in range(2 * STATUS_BLINK_FRAMES):
        assert activity_glyph(frame) == RUNNING_GLYPHS[0 if blink_state(frame) else 1]


def test_the_icon_turns_over_twice_in_a_blink():
    states = [blink_state(frame) for frame in range(STATUS_BLINK_FRAMES)]

    flips_inside = sum(1 for a, b in zip(states, states[1:], strict=False) if a != b)
    assert flips_inside == 1 and states[0] != states[-1], "one flip inside a period, and one more where it wraps"


# -- a step that repeats the picture changes nothing -------------------------------------------------


def _waiting(started_at: float = 0.0) -> tuple[Transcript, Clock]:
    clock = Clock()
    clock.now = started_at
    transcript = Transcript(clock=clock)
    transcript.begin_turn("question")  # a turn opens its own wait row
    assert isinstance(transcript.entries[-1], WaitEntry) and transcript.entries[-1].running
    return transcript, clock


def test_a_step_that_repeats_the_picture_returns_false_and_moves_nothing():
    transcript, clock = _waiting()
    transcript.advance_frame()
    clock.now = 1 / 120
    results = []

    for step in range(2, 400):
        clock.now = step / 120
        before = (transcript.frame, transcript.version)
        changed = transcript.advance_frame()
        results.append(changed)
        if not changed:
            assert (transcript.frame, transcript.version) == before, f"step {step} said nothing changed, and moved"

    assert results.count(False) > results.count(True), "most steps repeat the last picture"


def test_a_step_that_changes_the_picture_moves_the_frame_and_the_version():
    transcript, clock = _waiting()
    transcript.advance_frame()
    frame, version = transcript.frame, transcript.version

    moved = False
    for step in range(1, 40):
        clock.now = step / 120
        if transcript.advance_frame():
            moved = True
            break

    assert moved and transcript.frame > frame and transcript.version == version + 1


def test_over_a_whole_pulse_far_fewer_steps_are_taken_than_the_clock_offers():
    transcript, clock = _waiting()
    taken = 0

    for step in range(1, PULSE_FRAMES * 2 + 1):
        clock.now = step / 120
        taken += transcript.advance_frame()

    assert taken < PULSE_FRAMES * 2 // 3, f"{taken} of {PULSE_FRAMES * 2} steps"


def test_the_timer_crossing_a_whole_second_is_a_change_even_while_the_highlight_rests():
    """The wait row rests for the last second of each pulse and reads whole seconds, so a timer that
    ticks over then has to be drawn although nothing else moves."""
    transcript, clock = _waiting(started_at=0.2)
    clock.now = 1.6  # inside the rest, timer reads 1
    transcript.advance_frame()
    wait = transcript.entries[-1]
    assert isinstance(wait, WaitEntry) and round(wait.duration or 0) == 1

    changes = []
    for step in range(1, 40):
        clock.now = 1.6 + step / 120  # up to 1.93 s, still in the rest; the timer rounds to 2 at 1.7 s
        changes.append(transcript.advance_frame())

    assert changes.count(True) == 1, "exactly one step takes the timer to 2 s"
    assert round(wait.duration or 0) == 2


def test_a_second_running_row_with_its_own_timer_is_a_change_when_its_own_second_turns():
    """The reasoning row above the wait row has its own start, so its timer turns over at its own
    moment, which can fall inside the rest where nothing else moves."""
    transcript, clock = _waiting(started_at=0.0)  # the wait row reads whole seconds from 0.0
    clock.now = 0.3
    transcript.start_thinking()  # and the reasoning row from 0.3
    clock.now = 1.6  # inside the rest, both timers read 1
    transcript.advance_frame()

    changes = []
    for step in range(1, 36):
        clock.now = 1.6 + step / 120  # to 1.89 s: the wait row's timer turned at 1.5, the reasoning row's at 1.8
        changes.append(transcript.advance_frame())

    assert changes.count(True) == 1, "one step, the one that takes the reasoning row's timer to 2 s"


def test_the_same_step_twice_is_one_change():
    transcript, clock = _waiting()
    clock.now = 0.5

    first = transcript.advance_frame()
    second = transcript.advance_frame()

    assert first is True and second is False


def test_a_settled_request_has_no_row_to_rebuild_whatever_the_icon_does():
    """The icon is the status bar's and turns over on its own; no row is running, so none is touched."""
    transcript, clock = _waiting()
    transcript.settle_wait("Processed for 0s")
    version = transcript.version

    for step in range(1, 400):
        clock.now = step / 120
        transcript.advance_frame()

    assert transcript.version == version


def test_the_picture_covers_a_wait_row_whose_title_is_wider():
    """The title is what the highlight crosses, so its width sets how many pictures a pass has."""
    narrow, clock = _waiting()
    wide = Transcript(clock=clock)
    wide.begin_turn("question")
    wide.entries[-1].title = "Processing the very long request"
    counts = {}
    for name, transcript in (("narrow", narrow), ("wide", wide)):
        taken = 0
        for step in range(1, 181):
            clock.now = step / 120
            taken += transcript.advance_frame()
        counts[name] = taken

    assert counts["wide"] > counts["narrow"], "a longer word has more columns to cross"


# -- the widget protocol: a widget has to say "no" to let a frame be skipped -------------------------


class _Silent(Widget):
    """Does nothing on a tick: the base class's answer."""


class _Forgetful(Widget):
    """Overrides ``on_tick`` and returns nothing, as every override written before this did."""

    def __init__(self) -> None:
        super().__init__()
        self.ticks = 0

    def on_tick(self) -> None:
        self.ticks += 1


class _Sure(Widget):
    def __init__(self, answer: bool) -> None:
        super().__init__()
        self.answer, self.ticks = answer, 0

    def on_tick(self) -> bool:
        self.ticks += 1
        return self.answer


def test_a_widget_that_does_nothing_on_a_tick_reports_no_change():
    app = TuiApp(_Silent(), width=10, height=3)
    app.mount()

    assert app.tick() is False


def test_a_widget_that_overrides_on_tick_and_returns_nothing_is_taken_to_have_changed():
    """The cautious reading: forgetting to say "no" must never freeze the screen."""
    app = TuiApp(_Forgetful(), width=10, height=3)
    app.mount()

    assert app.tick() is True


def test_one_widget_saying_yes_is_enough_and_every_widget_is_still_given_the_clock():
    from zettcode.tui import VBox
    from zettcode.tui.layout import Slot

    quiet, loud = _Sure(False), _Sure(True)
    also_quiet = _Sure(False)
    app = TuiApp(VBox([Slot(quiet, size=1), Slot(loud, size=1), Slot(also_quiet, size=1)]), width=10, height=3)
    app.mount()

    assert app.tick() is True
    assert (quiet.ticks, loud.ticks, also_quiet.ticks) == (1, 1, 1), "a yes does not skip the widgets after it"


def test_every_widget_saying_no_is_no_change():
    from zettcode.tui import VBox
    from zettcode.tui.layout import Slot

    app = TuiApp(VBox([Slot(_Sure(False), size=1), Slot(_Sure(False), size=1)]), width=10, height=3)
    app.mount()

    assert app.tick() is False


# -- the scheduler says why a frame is due -----------------------------------------------------------


def test_a_requested_repaint_is_marked_as_requested():
    clock = Clock()
    scheduler = Scheduler(clock=clock)
    scheduler.poll()
    scheduler.request_repaint()

    assert scheduler.pending is True
    assert scheduler.poll() is True and scheduler.requested is True
    assert scheduler.pending is False


def test_a_frame_that_falls_due_on_an_animation_alone_is_marked_as_not_requested():
    clock = Clock()
    scheduler = Scheduler(clock=clock)
    scheduler.poll()
    scheduler.animate("spin")
    clock.now = 1.0

    assert scheduler.poll() is True
    assert scheduler.requested is False


def test_a_request_that_arrives_with_an_animation_due_is_a_request():
    clock = Clock()
    scheduler = Scheduler(clock=clock)
    scheduler.poll()
    scheduler.animate("spin")
    scheduler.request_repaint()
    clock.now = 1.0

    assert scheduler.poll() is True and scheduler.requested is True


def test_the_first_frame_is_a_requested_one():
    assert Scheduler().poll() is True


# -- the loop: what is skipped, and that the screen is the same ---------------------------------------


def _app_waiting_on(clock: Clock):
    """A real shell with a request running, driven by a hand clock, and the runner that paints it."""
    from test_zettcode_app import build_app

    app = build_app()
    # Steps are multiples of a float, so "an interval has passed since the last frame" is decided by
    # rounding error about half the time; a half-interval makes every step count as the frame it is.
    app.app.scheduler.interval = FRAME / 2
    app.app.clock = clock
    app.transcript.clock = clock
    app.app.resize(60, 14)
    terminal = StubTerminal(60, 14)
    runner = TerminalRunner(app.app, terminal=terminal)
    app.transcript.begin_turn("a question that takes a while")
    app._set_busy(True)
    runner.paint()
    return app, runner, terminal


def _drive(app, runner, clock, steps, *, gated: bool, events=None):
    """Advance the clock a step at a time and paint the way the loop does; return frames painted."""
    painted = 0
    renders = [0]
    real = app.app.render

    def counting():
        renders[0] += 1
        return real()

    app.app.render = counting
    for step in range(1, steps + 1):
        clock.now = step * FRAME
        if events and step in events:
            events[step](app)
        if app.app.scheduler.poll(now=clock.now):
            runner.paint(animation_only=gated and not app.app.scheduler.requested)
            painted += 1
    app.app.render = real
    return renders[0]


def test_skipping_repeated_frames_sends_the_terminal_exactly_what_painting_every_one_would():
    """The whole claim, tested the only way that counts: the bytes are identical, step for step."""
    outputs = []
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        _drive(app, runner, clock, steps=int(3.2 / FRAME), gated=gated)
        outputs.append(_sent(terminal))

    assert outputs[0] == outputs[1]
    assert len(outputs[0]) > 1000, "and something was drawn"


def test_the_two_runs_stay_identical_at_every_step_not_just_at_the_end():
    clocks = [Clock(), Clock()]
    runs = [_app_waiting_on(clocks[0]), _app_waiting_on(clocks[1])]
    for step in range(1, int(2.6 / FRAME) + 1):
        for gated, (app, runner, _), clock in zip((False, True), runs, clocks, strict=True):
            clock.now = step * FRAME
            if app.app.scheduler.poll(now=clock.now):
                runner.paint(animation_only=gated and not app.app.scheduler.requested)
        assert _sent(runs[0][2]) == _sent(runs[1][2]), f"diverged at step {step}"


def test_most_frames_of_a_long_wait_are_not_built_at_all():
    counts = {}
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        counts[gated] = _drive(app, runner, clock, steps=int(2.5 / FRAME), gated=gated)

    assert counts[False] >= 290, "every step was a frame"
    assert counts[True] < counts[False] * 0.4, f"{counts[True]} of {counts[False]} frames were built"


def test_typing_in_the_middle_of_a_wait_is_painted_at_once_and_matches():
    """A frame someone asked for is never skipped, even when it lands between two identical ones."""

    def type_x(app):
        app.composer.paste("x")
        app.app.invalidate()

    events = {50: type_x, 51: type_x, 200: type_x}
    outputs = []
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        _drive(app, runner, clock, steps=int(2.0 / FRAME), gated=gated, events=events)
        outputs.append(_sent(terminal))

    assert outputs[0] == outputs[1]
    # The comparison is not an empty one: what was typed was drawn, in the composer's own colours.
    # (The renderer may merge neighbouring cells into one write, so this counts writes, not letters.)
    assert outputs[1].count("mx\x1b[0m") >= 2


def test_a_flash_that_expires_during_a_wait_is_cleared_on_time_and_matches():
    def flash(app):
        app.flash("copied 3 chars to clipboard", seconds=0.6)

    outputs = []
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        _drive(app, runner, clock, steps=int(1.6 / FRAME), gated=gated, events={20: flash})
        outputs.append(_sent(terminal))

    assert outputs[0] == outputs[1]
    assert "copied 3 chars" in outputs[1]


def test_a_theme_change_during_a_wait_repaints_every_cell_and_matches():
    def theme(app):
        """What a palette change does to the loop: every cell must be sent again."""
        app.app.refreshed = True
        app.app.invalidate()

    outputs = []
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        _drive(app, runner, clock, steps=int(1.0 / FRAME), gated=gated, events={30: theme})
        outputs.append(_sent(terminal))

    assert outputs[0] == outputs[1]


def test_a_resize_during_a_wait_is_painted_and_matches():
    def resize(app):
        app.app.resize(40, 10)

    outputs = []
    for gated in (False, True):
        clock = Clock()
        app, runner, terminal = _app_waiting_on(clock)
        _drive(app, runner, clock, steps=int(1.0 / FRAME), gated=gated, events={30: resize})
        outputs.append(_sent(terminal))

    assert outputs[0] == outputs[1]


def test_a_callback_waiting_for_the_next_paint_runs_even_when_the_frame_is_only_animation():
    """`after_next_paint` promises its callback runs right after a frame is written; a skipped frame
    would let it wait for the next real one, which may be a long way off."""
    clock = Clock()
    app, runner, terminal = _app_waiting_on(clock)
    ran = []
    runner.after_next_paint(lambda: ran.append(True))
    clock.now = 0.05  # an animation-only moment, nothing requested

    runner.paint(animation_only=True)

    assert ran == [True]


def test_an_idle_screen_with_no_animation_is_not_painted_at_all_and_never_was():
    """Nothing here changes that: no token, no request, no frame."""
    clock = Clock()
    scheduler = Scheduler(clock=clock)
    scheduler.poll()
    clock.now = 5.0

    assert scheduler.poll() is False and scheduler.delay() is None


def test_a_reader_who_asked_for_reduced_motion_still_gets_no_animation():
    clock = Clock()
    app, runner, terminal = _app_waiting_on(clock)
    app.app.reduced_motion = True
    before = app.transcript.frame

    for step in range(1, 120):
        clock.now = step * FRAME
        app.app.tick()

    assert app.transcript.frame == before


def test_the_frame_rate_the_reader_asked_for_is_still_what_the_clock_offers():
    """The steps are as fine as ever; what changed is that a step that repeats a picture is not drawn."""
    assert ANIMATION_FPS == 120 and ANIMATION_SECONDS == pytest.approx(1 / 120)
    assert EntryStatus.RUNNING.value == "running"


def test_the_icon_turning_over_is_a_change_even_while_the_highlight_rests():
    """Frame 270 is inside the rest (180 to 299) and is where the icon turns over again: nothing else
    moves there, so only the icon can make it a change. Frames 90 and 180, where it also turns, are
    no use for this — the highlight happens to move at those too."""
    transcript, clock = _waiting(started_at=0.0)
    clock.now = 269 * FRAME
    transcript.advance_frame()
    assert not blink_state(269) == blink_state(270), "the icon does turn over at frame 270"
    assert wait_picture(269, 10) == wait_picture(270, 10) == (False, 0), "and the row is at rest on both sides"

    clock.now = 270 * FRAME

    assert transcript.advance_frame() is True


# -- the guards inside `paint`: what keeps an animation-only frame from being skipped -----------------
#
# `animation_only` is already False for a frame somebody asked for, so the loop never reaches these
# with a request in hand. They are for what happens *during* the frame — a widget asking for a repaint
# while it is being ticked, a palette adopted between the poll and the paint — and they are tested by
# calling `paint(animation_only=True)` in exactly those states.


def _quiet_app(clock: Clock):
    """A waiting shell that has just painted, with the clock where it was: the next step changes nothing."""
    app, runner, terminal = _app_waiting_on(clock)
    clock.now = 0.05
    app.app.tick()
    app.app.scheduler.poll(now=clock.now)  # take whatever was pending
    runner.paint()
    return app, runner, terminal


def _renders_during(app, call) -> int:
    renders = [0]
    real = app.app.render

    def counting():
        renders[0] += 1
        return real()

    app.app.render = counting
    try:
        call()
    finally:
        app.app.render = real
    return renders[0]


def test_a_step_that_changes_nothing_is_skipped_to_begin_with():
    """The control for the rest: in this state an animation-only frame costs no render at all."""
    clock = Clock()
    app, runner, terminal = _quiet_app(clock)
    before = terminal.output.getvalue()

    renders = _renders_during(app, lambda: runner.paint(animation_only=True))

    assert renders == 0 and terminal.output.getvalue() == before


def test_a_repaint_requested_while_the_widgets_were_ticked_is_not_skipped():
    """The flash and the effort gauge ask this way: they invalidate from inside `on_tick`."""
    clock = Clock()
    app, runner, _ = _quiet_app(clock)
    real_tick = app.app.tick

    def tick_and_ask():
        changed = real_tick()
        app.app.invalidate()  # a widget asked for a frame, and said nothing about it in its return value
        return changed

    app.app.tick = tick_and_ask

    assert _renders_during(app, lambda: runner.paint(animation_only=True)) == 1


def test_a_layout_that_is_stale_is_not_skipped():
    clock = Clock()
    app, runner, _ = _quiet_app(clock)
    app.app._layout_dirty = True  # without the repaint request `request_layout` also makes
    app.app.scheduler.poll(now=clock.now)

    assert app.app.layout_pending and not app.app.scheduler.pending
    assert _renders_during(app, lambda: runner.paint(animation_only=True)) == 1


def test_a_palette_adopted_since_the_last_frame_is_not_skipped_and_resends_every_cell():
    clock = Clock()
    app, runner, terminal = _quiet_app(clock)
    before = len(terminal.output.getvalue())
    app.app.refreshed = True  # what adopting a theme does

    renders = _renders_during(app, lambda: runner.paint(animation_only=True))

    assert renders == 1 and app.app.refreshed is False
    assert len(terminal.output.getvalue()) - before > 500, "every cell was sent again, not a handful"


def test_a_callback_waiting_for_the_next_paint_is_not_left_waiting_by_a_quiet_frame():
    """With nothing else to draw the frame would be skipped, and the callback with it."""
    clock = Clock()
    app, runner, _ = _quiet_app(clock)
    ran = []
    runner.after_next_paint(lambda: ran.append(True))

    renders = _renders_during(app, lambda: runner.paint(animation_only=True))

    assert ran == [True] and renders == 1
