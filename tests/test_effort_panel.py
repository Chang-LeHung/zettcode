"""The ``/effort`` panel: a knob that slides along a rail of levels, and applies the one it stops on."""

from __future__ import annotations

import asyncio

from test_zettcode_app import (
    EFFORT_SECONDS,
    _announcements,
    _effort_page,
    _harness,
    _start_a_request,
    _stop,
    _type_command,
    _typed_while_running,
    app_module,
    build_app,
)
from zettcode.app.ui.widgets.effort_page import KNOB, LIT, SLIDE_SECONDS

LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


class Clock:
    """A clock the test moves, standing in for the application's."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def open_panel(app=None, *, steps: Clock | None = None):
    app = app or build_app()
    harness = _harness(app)
    harness.render()
    if steps is not None:
        app.app.clock = steps
    await _type_command(app, harness, "/effort")
    return app, harness


def knob_column(harness) -> int:
    row = next(line for line in harness.render().text.splitlines() if KNOB in line)
    return row.index(KNOB)


def lit_cells(harness) -> int:
    row = next(line for line in harness.render().text.splitlines() if KNOB in line)
    return row.count(LIT)


async def test_the_panel_is_a_rail_with_a_node_and_a_name_for_every_level():
    app, harness = await open_panel()

    text = harness.render().text

    assert app.app.screens.top.name == "page"
    assert app.composer.text == "", "no menu and no subcommand: the panel is the choice"
    assert _effort_page(app).levels == LEVELS
    assert all(level in text for level in LEVELS)
    assert text.count(KNOB) == 1
    assert "now" in text, "the level in force is marked"
    assert _effort_page(app).level == "medium"


async def test_the_arrows_only_slide_the_knob_and_change_nothing():
    app, harness = await open_panel()

    harness.press("right")
    harness.press("right")

    assert _effort_page(app).level == "xhigh"
    assert app.agent.effort == "medium", "nothing is applied until Enter"
    assert app._effort_animation is None, "and the header does not play its gauge for a preview"
    assert _announcements(app) == []


async def test_the_knob_travels_there_and_lights_the_rail_behind_it():
    clock = Clock()
    app, harness = await open_panel(steps=clock)
    page = _effort_page(app)
    start = knob_column(harness)
    lit_before = lit_cells(harness)

    harness.press("right")
    harness.press("right")
    harness.press("right")
    assert page.moving
    assert "effort-panel" in "".join(app.app.scheduler.animations), "the frame loop is kept awake while it moves"
    assert knob_column(harness) == start, "it sets off from where it was"

    clock.now += SLIDE_SECONDS * 0.4
    middle = knob_column(harness)
    assert start < middle, "on its way"
    assert lit_cells(harness) > lit_before, "the stretch behind it is lit as it goes"

    clock.now += SLIDE_SECONDS
    app.app.tick()
    arrived = knob_column(harness)
    assert middle < arrived
    assert not page.moving
    assert not any(token.startswith("effort-panel") for token in app.app.scheduler.animations), (
        "and the loop is given back"
    )


async def test_a_second_press_mid_slide_carries_on_from_where_the_knob_is():
    clock = Clock()
    app, harness = await open_panel(steps=clock)
    page = _effort_page(app)
    harness.press("right")
    clock.now += SLIDE_SECONDS * 0.5
    here = page.position()
    assert 3.0 < here < 4.0

    harness.press("right")

    assert page.position() == here, "no jump back to the node it was leaving"
    clock.now += SLIDE_SECONDS * 2
    assert page.position() == 5.0


async def test_it_stops_at_both_ends_of_the_scale():
    app, harness = await open_panel()
    page = _effort_page(app)

    for _ in range(12):
        harness.press("right")
    assert page.level == "ultra"
    for _ in range(12):
        harness.press("left")
    assert page.level == "off"
    harness.press("end")
    assert page.level == "ultra"
    harness.press("home")
    assert page.level == "off"


async def test_enter_applies_the_level_and_only_then_the_header_plays_its_gauge(monkeypatch):
    app = build_app()
    harness = _harness(app)
    harness.render()
    clock = [5_000.0]
    monkeypatch.setattr(app_module, "monotonic", lambda: clock[0])
    await _type_command(app, harness, "/effort")
    harness.press("right")
    assert app._effort_animation is None

    harness.press("enter")

    assert app.app.screens.top.name == "main"
    assert app.agent.effort == "high"
    assert app._effort_animation is not None, "the header's own animation starts once it is selected"
    assert "effort" in app.app.scheduler.animations
    clock[0] += EFFORT_SECONDS * 0.4
    middle = app._header_right().text
    assert middle.count("\u2501") + middle.count("\u2578") >= 1, middle
    assert _announcements(app) == ["Reasoning effort changed from medium to high."]

    clock[0] += EFFORT_SECONDS * 2
    app.settle_effort_animation()
    assert app._effort_animation is None
    assert app._header_right().text.strip().endswith("high")


async def test_enter_without_moving_changes_nothing():
    app, harness = await open_panel()

    harness.press("enter")

    assert app.app.screens.top.name == "main"
    assert app.agent.effort == "medium"
    assert _announcements(app) == []
    assert app._effort_animation is None


async def test_escape_puts_the_panel_away_and_applies_nothing():
    app, harness = await open_panel()
    harness.press("right")
    harness.press("right")

    harness.press("escape")

    assert app.app.screens.top.name == "main"
    assert app.agent.effort == "medium"
    assert _announcements(app) == []
    assert app._effort_animation is None
    assert not any(token.startswith("effort-panel") for token in app.app.scheduler.animations)


async def test_putting_the_panel_away_mid_slide_gives_the_frame_loop_back():
    app, harness = await open_panel(steps=Clock())
    harness.press("right")
    assert any(token.startswith("effort-panel") for token in app.app.scheduler.animations)

    harness.press("escape")

    assert not any(token.startswith("effort-panel") for token in app.app.scheduler.animations)


async def test_a_click_sends_the_knob_to_the_nearest_level():
    app, harness = await open_panel()
    harness.render()
    page = _effort_page(app)
    left, right = page._rail()
    column = page._column(page.levels.index("max"), left, right)

    harness.click(column + 1, page.rect.y + 5)

    assert page.level == "max"
    assert app.agent.effort == "medium"


async def test_under_reduced_motion_the_knob_jumps():
    app = build_app()
    app.app.reduced_motion = True
    app, harness = await open_panel(app)
    page = _effort_page(app)

    harness.press("right")

    assert not page.moving
    assert page.position() == 4.0
    assert not any(token.startswith("effort-panel") for token in app.app.scheduler.animations)


async def test_over_a_running_request_enter_applies_the_level_and_leaves_the_waiting_rows_motion_alone():
    app = build_app(block=True)
    harness = _harness(app)
    await _start_a_request(harness)

    await _typed_while_running(app, harness, "/effort")
    harness.press("right")
    harness.press("enter")

    assert app.agent.effort == "high"
    assert app._effort_animation is None, "the waiting row owns the motion"
    assert not app.task.done()
    await _stop(app)


async def test_on_a_narrow_screen_the_knobs_name_is_always_written_and_nothing_runs_off_the_edge():
    app = build_app()
    app.app.resize(30, 14)
    app, harness = await open_panel(app)

    for _ in range(7):
        harness.press("right")
    text = harness.render().text

    assert _effort_page(app).level == "ultra"
    assert "ultra" in text
    assert all(len(line) <= 30 for line in text.splitlines())


async def test_a_typed_level_still_switches_at_once_without_a_panel():
    app = build_app()
    harness = _harness(app)

    await _type_command(app, harness, "/effort ultra")

    assert app.agent.effort == "ultra"
    assert app.app.screens.top.name == "main"
    asyncio.get_event_loop()  # the command has finished; nothing is left running
