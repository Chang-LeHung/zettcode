"""The ``/self-compact`` panel: one rail for this session and one for the default, applied together with Enter."""

from __future__ import annotations

import pytest

from test_zettcode_app import _harness, _start_a_request, _stop, _type_command, _typed_while_running, build_app, walk
from zettcode._compat import tomllib
from zettcode.app.ui.widgets.self_compact_page import KNOB, SelfCompactPage
from zettcode.app.ui.widgets.switch import SLIDE_SECONDS

MODEL = '[[models]]\nmodel = "m"\ntoken = "t"\n'


class Clock:
    """A clock the test moves, standing in for the application's."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    return path


def _page(app) -> SelfCompactPage:
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, SelfCompactPage))


async def open_panel(app=None, *, clock: Clock | None = None):
    app = app or build_app()
    harness = _harness(app)
    harness.render()
    if clock is not None:
        app.app.clock = clock
    await _type_command(app, harness, "/self-compact")
    return app, harness


def notices(app) -> list[str]:
    return [entry.text for entry in app.transcript.entries if entry.kind == "notice"]


async def test_the_panel_has_a_rail_for_this_session_and_one_for_every_session(config_file):
    app, harness = await open_panel()

    text = harness.render().text

    assert app.app.screens.top.name == "page"
    assert app.composer.text == "", "no menu: the panel is the choice"
    for words in ("Self-compaction", "This session", "Every session", "default (off)", "in effect here: off"):
        assert words in text
    assert text.count(KNOB) == 2, "one knob on each rail"
    assert "esc cancel" in text


async def test_the_panel_starts_where_the_settings_are(config_file):
    app = build_app()
    app.agent.use_self_compaction(True)
    app, _ = await open_panel(app)

    page = _page(app)

    assert (page.choice, page.default, page.effective) == (True, False, True)
    assert not page.changed


async def test_the_arrows_move_the_knob_of_the_active_row_and_change_nothing(config_file):
    app, harness = await open_panel()
    page = _page(app)

    harness.press("right")
    harness.press("right")

    assert page.choice is True
    assert page.default is False, "the other rail is where it was"
    assert app.agent.self_compaction_choice is None and not app.agent.self_compaction
    assert "(not applied)" in harness.render().text
    assert not notices(app)


async def test_up_and_down_choose_the_row_and_the_arrows_then_move_that_one(config_file):
    app, harness = await open_panel()
    page = _page(app)

    harness.press("down")
    harness.press("right")

    assert (page.choice, page.default) == (None, True)
    harness.press("up")
    harness.press("right")
    assert (page.choice, page.default) == (False, True)


async def test_the_default_option_names_what_it_would_be(config_file):
    app, harness = await open_panel()

    assert "default (off)" in harness.render().text
    harness.press("down")
    harness.press("right")
    text = harness.render().text

    assert "default (on)" in text
    assert "in effect here: on" in text, "the session has no choice, so it follows the default being set"


async def test_a_session_choice_beats_the_default_in_what_is_in_effect(config_file):
    app, harness = await open_panel()
    harness.press("right")  # session: off
    harness.press("down")
    harness.press("right")  # default: on

    page = _page(app)

    assert (page.choice, page.default, page.effective) == (False, True, False)
    assert "in effect here: off" in harness.render().text


async def test_it_stops_at_both_ends_of_a_rail(config_file):
    app, harness = await open_panel()
    page = _page(app)

    for _ in range(6):
        harness.press("right")
    assert page.choice is True
    for _ in range(6):
        harness.press("left")
    assert page.choice is None
    harness.press("end")
    assert page.choice is True
    harness.press("home")
    assert page.choice is None


async def test_enter_applies_both_rails_and_says_what_now_applies(config_file):
    app, harness = await open_panel()
    harness.press("right")
    harness.press("right")  # session: on
    harness.press("down")
    harness.press("right")  # default: on

    harness.press("enter")

    assert app.app.screens.top.name != "page", "the panel is put away"
    assert app.agent.self_compaction_choice is True
    assert app.agent.self_compaction_default is True
    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["compaction"] == {"self": True}
    assert notices(app) == ["Self-compaction is on: this session chose it; the default is on"]


async def test_enter_with_nothing_moved_changes_nothing(config_file):
    before = config_file.read_text(encoding="utf-8")
    app, harness = await open_panel()

    harness.press("enter")

    assert config_file.read_text(encoding="utf-8") == before, "the file is not rewritten for no change"
    assert app.agent.self_compaction_choice is None
    assert notices(app) == ["Self-compaction is off: this session follows the default (off)"]


async def test_escape_applies_nothing(config_file):
    before = config_file.read_text(encoding="utf-8")
    app, harness = await open_panel()
    harness.press("right")
    harness.press("down")
    harness.press("right")

    harness.press("escape")

    assert app.app.screens.top.name != "page"
    assert app.agent.self_compaction_choice is None and not app.agent.self_compaction_default
    assert config_file.read_text(encoding="utf-8") == before
    assert not notices(app)


async def test_a_default_that_cannot_be_written_is_reported_and_the_session_still_gets_its_choice(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    app, harness = await open_panel()
    harness.press("right")
    harness.press("right")  # session: on
    harness.press("down")
    harness.press("right")  # default: on, which needs a file that is not there

    harness.press("enter")

    assert app.agent.self_compaction_choice is True, "one part failing does not cost the other"
    assert app.agent.self_compaction_default is False
    errors = [e.text for e in app.transcript.entries if e.kind == "notice" and getattr(e, "level", None)]
    assert any("does not exist" in text for text in errors)
    assert not (tmp_path / "missing.toml").exists()


async def test_a_session_open_in_another_process_leaves_only_the_default_to_move(config_file):
    app = build_app()
    app.agent.runtime.held_elsewhere.add(app.agent.session_id)
    app.agent.runtime.retake_session()
    app, harness = await open_panel(app)
    page = _page(app)

    harness.press("up")
    harness.press("right")

    assert (page.choice, page.default) == (None, True), "the arrows went to the default"
    assert "open in another process" in harness.render().text


async def test_the_knob_travels_there_from_the_clock(config_file):
    clock = Clock()
    app, harness = await open_panel(clock=clock)
    page = _page(app)

    harness.press("right")
    harness.press("right")

    assert page.moving
    assert "self-compact-panel" in "".join(app.app.scheduler.animations), "the frame loop is kept awake"
    clock.now += SLIDE_SECONDS * 0.4
    assert 0.0 < page.session_rail.position(clock.now) < 2.0
    clock.now += SLIDE_SECONDS
    app.app.tick()
    assert not page.moving
    assert page.session_rail.position(clock.now) == 2.0
    assert not any(token.startswith("self-compact-panel") for token in app.app.scheduler.animations)


async def test_under_reduced_motion_the_knob_jumps(config_file):
    app = build_app()
    app.app.reduced_motion = True
    app, harness = await open_panel(app)
    page = _page(app)

    harness.press("right")

    assert not page.moving and page.session_rail.position(0.0) == 1.0


async def test_a_click_on_a_rail_sends_its_knob_to_the_option_nearest(config_file):
    app, harness = await open_panel()
    harness.render()
    page = _page(app)
    left, right = page._rail()

    harness.click(page._column(page.default_rail, 1, left, right), page.rect.y + 6)

    assert page.default is True and page.row == 1
    harness.click(page._column(page.session_rail, 2, left, right) - 1, page.rect.y + 4)
    assert page.choice is True and page.row == 0


@pytest.mark.parametrize("width", [24, 30, 40, 60, 100])
async def test_nothing_runs_off_the_edge_on_a_narrow_screen(config_file, width):
    app = build_app()
    app.app.resize(width, 14)
    app, harness = await open_panel(app)

    harness.press("right")
    harness.press("down")
    harness.press("right")
    lines = harness.render().text.splitlines()

    assert all(len(line) <= width for line in lines)
    assert any("Self-compaction" in line for line in lines)


async def test_over_a_running_request_enter_applies_it_and_leaves_the_request_alone(config_file):
    app = build_app(block=True)
    harness = _harness(app)
    await _start_a_request(harness)

    await _typed_while_running(app, harness, "/self-compact")
    harness.press("right")
    harness.press("right")
    harness.press("enter")

    assert app.agent.self_compaction_choice is True
    assert not app.task.done()
    await _stop(app)


async def test_the_status_line_says_when_it_is_on(config_file):
    app, harness = await open_panel()
    assert "self-compact" not in harness.render().text.strip().splitlines()[-1]
    harness.press("right")
    harness.press("right")

    harness.press("enter")

    assert "self-compact" in harness.render().text.strip().splitlines()[-1]


async def test_typed_words_still_work_without_the_panel(config_file):
    app = build_app()
    harness = _harness(app)

    await _type_command(app, harness, "/self-compact global on")

    assert app.app.screens.top.name != "page"
    assert app.agent.self_compaction_default is True
    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["compaction"] == {"self": True}
