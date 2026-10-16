"""The show the header plays for a switch to the top of the scale: light crossing the row from right to left."""

from __future__ import annotations

import pytest

from test_zettcode_app import _harness, build_app
from zettcode.app.agent.conversation.effort_gauge import EFFORT_SECONDS, EffortFrame
from zettcode.app.agent.conversation.shimmer import (
    SHIMMER_LONGEST_PASS,
    ShimmerFrame,
    shimmer_frame,
    shimmer_schedule,
    shimmer_seconds,
    shimmer_width,
)
from zettcode.app.ui import app as app_module

LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
LEAD = 14
REACH = 80
SCREEN = 90


def at(level: str, pass_index: int, edge: int) -> float:
    """The moment, as a fraction of the show, a pass of the light sets off (``edge`` 0) or has gone (``edge`` 1)."""
    return shimmer_schedule(level, REACH)[pass_index][edge] / shimmer_seconds(level, REACH)


def frame(level: str, progress: float) -> ShimmerFrame:
    result = shimmer_frame(level, LEVELS, lead=LEAD, reach=REACH, progress=progress)
    assert result is not None
    return result


def brightest(shown: ShimmerFrame) -> int:
    return max(range(shown.width), key=lambda column: (shown.core[column], column))


@pytest.mark.parametrize("level", ["off", "medium", "xhigh", "an old name"])
def test_only_the_top_of_the_scale_gets_the_show(level: str):
    assert shimmer_frame(level, LEVELS, lead=LEAD, reach=REACH, progress=0.3) is None


@pytest.mark.parametrize("progress", [-0.1, 1.0, 1.5])
def test_outside_the_show_there_is_nothing_to_draw(progress: float):
    assert shimmer_frame("ultra", LEVELS, lead=LEAD, reach=REACH, progress=progress) is None
    assert shimmer_frame("ultra", (), lead=LEAD, reach=REACH, progress=0.3) is None


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_row_is_as_wide_at_every_moment_so_the_right_aligned_header_does_not_shiver(level: str):
    widths = {frame(level, step / 60).width for step in range(60)}

    assert widths == {shimmer_width(LEAD, len(LEVELS), level)}


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_light_crosses_from_the_right_towards_the_left(level: str):
    end = at(level, 1, 0)  # before the second pass comes in behind the first
    columns = []
    for step in range(1, 40):
        shown = frame(level, end * step / 40)
        if max(shown.core) > 0.5:  # while the light is over the right segment
            columns.append(brightest(shown))

    assert len(columns) >= 4
    assert columns == sorted(columns, reverse=True), columns
    assert columns[0] > columns[-1], "and it does get somewhere"


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_first_pass_ignites_the_columns_it_has_left_behind_and_never_puts_one_out(level: str):
    end = at(level, 0, 1)
    counts = []
    for step in range(60):
        shown = frame(level, end * step / 60)
        ignited = [column for column in range(shown.width) if shown.ignited[column]]
        counts.append(len(ignited))
        # What is lit is a run that starts at the right edge: the light leaves it behind.
        assert ignited == list(range(shown.width - len(ignited), shown.width))

    assert counts[0] == 0, "nothing is lit before the light arrives"
    assert counts == sorted(counts), "and nothing goes out again"
    assert frame(level, end + 0.01).ignited == (True,) * frame(level, end + 0.01).width


def test_the_gauge_lights_only_as_far_as_the_level_reaches():
    assert frame("max", 0.5).lit_cells == LEVELS.index("max") + 1
    assert frame("ultra", 0.5).lit_cells == len(LEVELS)


def test_ultra_twinkles_across_the_lit_row_and_max_keeps_to_its_light():
    ultra = max(max(frame("ultra", step / 60).glitter) for step in range(60))
    max_ = max(max(frame("max", step / 60).glitter) for step in range(60))

    assert ultra > 0.5
    assert max_ == 0.0
    assert min(frame("ultra", 0.05).glitter) == 0.0, "and not before the light has been"


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_sparkles_come_with_the_light_and_have_a_slot_even_when_they_are_dark(level: str):
    early = frame(level, 0.01)
    late = frame(level, 0.7)

    assert early.sparks == (" ", " ")
    assert all(len(spark) == 1 for spark in late.sparks)
    assert any(spark.strip() for step in range(40) for spark in frame(level, 0.4 + step / 200).sparks)


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_show_arrives_holds_and_leaves(level: str):
    presence = [frame(level, step / 100).presence for step in range(100)]

    assert presence[0] == 0.0
    assert max(presence) == 1.0
    assert presence[-1] < 0.2
    assert all(0.0 <= value <= 1.0 for value in presence)


def test_the_light_that_crosses_the_left_segment_is_the_same_light():
    shown = frame("ultra", 0.2)
    centre = shown.bands[0]

    halo, core = shown.light(centre)
    far_halo, far_core = shown.light(centre + 40)

    assert halo == 1.0 and core == 1.0
    assert far_halo == 0.0 and far_core == 0.0
    # Over the right segment the two descriptions agree column for column.
    early = frame("ultra", 0.06)
    assert max(early.core) > 0.5
    for column in range(early.width):
        assert early.light(early.width - 1 - column) == (early.glow[column], early.core[column])


# -- in the shell -------------------------------------------------------------------------------


def shell(monkeypatch):
    app = build_app()
    app.app.resize(90, 14)
    harness = _harness(app)
    harness.render()
    clock = [1_000.0]
    monkeypatch.setattr(app_module, "monotonic", lambda: clock[0])
    return app, clock


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_a_switch_to_the_top_of_the_scale_plays_the_show_and_lasts_longer(monkeypatch, level: str):
    app, clock = shell(monkeypatch)

    app.change_effort(level)
    clock[0] += EFFORT_SECONDS * 0.5
    assert isinstance(app._effort_gauge(), ShimmerFrame)

    clock[0] += EFFORT_SECONDS * 0.6  # past the ordinary gauge's time
    app.settle_effort_animation()
    assert app._effort_animation is not None, "still going: the show is longer"
    assert "effort" in app.app.scheduler.animations

    clock[0] += shimmer_seconds(level, SCREEN)
    app.settle_effort_animation()
    assert app._effort_animation is None
    assert "effort" not in app.app.scheduler.animations
    assert app._header_right().text.strip().endswith(level) or level in app._header_right().text


def test_every_other_level_keeps_the_ordinary_gauge(monkeypatch):
    app, clock = shell(monkeypatch)

    app.change_effort("xhigh")
    clock[0] += EFFORT_SECONDS * 0.4

    assert isinstance(app._effort_gauge(), EffortFrame)


def test_the_header_row_keeps_its_width_through_the_whole_show(monkeypatch):
    app, clock = shell(monkeypatch)
    app.change_effort("ultra")
    started = clock[0]

    widths = set()
    for step in range(1, 40):
        clock[0] = started + shimmer_seconds("ultra", SCREEN) * step / 40
        widths.add(app._header_right().width)

    assert len(widths) == 1, widths


def test_the_light_goes_over_the_left_segment_too_and_leaves_it_as_it_was(monkeypatch):
    app, clock = shell(monkeypatch)
    resting = [(span.text, span.style.foreground, span.style.bold) for span in app._header_left().spans]
    app.change_effort("ultra")
    started = clock[0]

    changed = False
    for step in range(1, 100):
        clock[0] = started + shimmer_seconds("ultra", SCREEN) * step / 100
        line = app._header_left()
        assert line.text == "".join(text for text, _, _ in resting) or line.text.startswith(resting[0][0][0])
        if [(span.style.foreground, span.style.bold) for span in line.spans] != [(f, b) for _, f, b in resting]:
            changed = True
    clock[0] = started + shimmer_seconds("ultra", SCREEN) * 1.5
    app.settle_effort_animation()

    assert changed, "the light reached the left side"
    assert [(span.text, span.style.foreground, span.style.bold) for span in app._header_left().spans] == resting


def test_the_ordinary_gauge_leaves_the_left_segment_alone(monkeypatch):
    app, clock = shell(monkeypatch)
    before = app._header_left()
    app.change_effort("xhigh")
    clock[0] += EFFORT_SECONDS * 0.4

    assert app._header_left() == before


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_the_light_crosses_a_wider_header_in_longer_not_at_a_higher_pace_until_the_cap(level: str):
    narrow = shimmer_schedule(level, 60)[0]
    wide = shimmer_schedule(level, 100)[0]
    pace_narrow = (60 + 16) / (narrow[1] - narrow[0])
    pace_wide = (100 + 16) / (wide[1] - wide[0])

    assert pace_narrow == pytest.approx(pace_wide), "the same columns a second"
    assert pace_narrow < 40, "and a gentle one"


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_a_very_wide_header_is_not_kept_waiting(level: str):
    first, *_ = shimmer_schedule(level, 400)[0:1]

    assert first[1] - first[0] <= SHIMMER_LONGEST_PASS + 1e-9
    assert shimmer_seconds(level, 400) < 12


@pytest.mark.parametrize("level", ["max", "ultra"])
def test_each_pass_after_the_first_is_a_little_quicker(level: str):
    durations = [end - start for start, end in shimmer_schedule(level, REACH)]

    assert durations == sorted(durations, reverse=True)
    assert durations[0] / durations[-1] < 2.0, "a little, not a blur"
