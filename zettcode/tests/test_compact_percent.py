"""Where a request is compacted, set from ``/context``: the knob on its rail, the glide, and what Enter writes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from test_context_page import report_of
from zettcode._compat import tomllib
from zettcode.app.agent.agent import TerminalAgent
from zettcode.app.ui.widgets import ContextPage
from zettcode.app.ui.widgets.context_page import KNOB, LIT, SLIDE_SECONDS
from zettcode.config import load_config
from zettcode.engine import core as runtime_module
from zettcode.engine.core import ZettCodeEngine
from zettcode.tui.testing import Harness

BASE = """\
# my config
[[models]]
model = "gpt-5-mini"
token = "sk-one"
compact_percent = 75

# second
[[models]]
model = "gpt-4o"
token = "sk-two"
"""


class Clock:
    """A clock the test moves, standing in for the application's."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class Opened:
    """A page over a report, with the clock in the test's hand and the applications it was asked for kept."""

    def __init__(self, percent: float | None = 80.0, *, reduced: bool = False, width: int = 100) -> None:
        self.applied: list[float] = []
        self.clock = Clock()
        self.page = ContextPage(
            report_of(window=200_000, reported=40_000),
            model="m",
            trigger=160_000,
            compact_percent=percent,
            on_apply=self.applied.append if percent is not None else None,
        )
        self.harness = Harness(self.page, width=width, height=34, clock=self.clock)
        self.harness.app.reduced_motion = reduced
        self.harness.render()

    def text(self) -> str:
        return self.harness.render().text


# -- the keys ---------------------------------------------------------------------------------------------------


def test_left_and_right_move_the_share_five_percent_at_a_time_and_stop_at_the_ends():
    opened = Opened(83.0)

    opened.harness.press("right")
    assert opened.page.percent == 85, "to the multiple of five above"
    opened.harness.press("left")
    assert opened.page.percent == 80, "and below"
    opened.harness.press("left")
    assert opened.page.percent == 75
    for _ in range(40):
        opened.harness.press("right")
    assert opened.page.percent == 100
    for _ in range(40):
        opened.harness.press("left")
    assert opened.page.percent == 1, "the share is never nothing"


def test_minus_and_plus_are_not_keys_of_the_page():
    opened = Opened(80.0)

    opened.harness.write("+")
    opened.harness.write("-")

    assert opened.page.percent == 80


def test_nothing_is_applied_until_enter_and_enter_on_an_unmoved_share_applies_nothing():
    opened = Opened(80.0)

    opened.harness.press("enter")
    assert opened.applied == []
    opened.harness.press("left")
    assert opened.applied == [] and opened.page.changed
    opened.harness.press("enter")

    assert opened.applied == [75.0]


def test_escape_leaves_through_the_owner_and_applies_nothing():
    left: list[str] = []
    page = ContextPage(
        report_of(), compact_percent=80.0, on_apply=lambda share: None, on_cancel=lambda: left.append("x")
    )
    harness = Harness(page, width=80, height=30)

    harness.press("left")
    harness.press("escape")

    assert left == ["x"]


def test_a_page_given_no_share_is_a_report_and_its_arrows_do_nothing():
    opened = Opened(None)

    opened.harness.press("left")
    opened.harness.press("enter")

    assert opened.page.percent is None and not opened.page.adjustable
    assert opened.applied == [] and "Compress at" not in opened.text()


# -- the glide --------------------------------------------------------------------------------------------------


def test_the_knob_glides_from_where_it_was_to_where_it_is_going_by_the_clock():
    opened = Opened(80.0)
    opened.harness.press("left")

    assert opened.page.knob_at(opened.clock.now) == 80, "it sets off from where it was"
    opened.clock.now += SLIDE_SECONDS / 2
    middle = opened.page.knob_at(opened.clock.now)
    assert 75 < middle < 80
    opened.clock.now += SLIDE_SECONDS
    assert opened.page.knob_at(opened.clock.now) == 75


def test_a_new_press_in_mid_glide_sets_off_from_where_the_knob_is_not_from_where_it_was_going():
    opened = Opened(80.0)
    opened.harness.press("left")
    opened.clock.now += SLIDE_SECONDS / 2
    here = opened.page.knob_at(opened.clock.now)

    opened.harness.press("left")

    assert opened.page.knob_at(opened.clock.now) == pytest.approx(here)
    assert opened.page.percent == 70


def test_the_mark_under_the_gauge_travels_with_the_knob():
    opened = Opened(80.0)
    before = opened.text()
    assert "compacts at 160,000" in before

    opened.harness.press("left")
    opened.clock.now += SLIDE_SECONDS / 2
    during = opened.text()
    shown = [int(word.replace(",", "")) for word in during.split() if word.replace(",", "").isdigit()]
    assert any(150_000 < number < 160_000 for number in shown), "the mark reads a point between the two"
    assert "compacts at 160,000" not in during
    opened.clock.now += SLIDE_SECONDS
    assert "compacts at 150,000" in opened.text()


def test_the_page_asks_for_frames_while_the_knob_moves_and_stops_when_it_arrives_or_is_put_away():
    opened = Opened(80.0)
    token = opened.page._token
    assert token not in opened.harness.app.scheduler.animations

    opened.harness.press("left")
    assert token in opened.harness.app.scheduler.animations
    assert opened.page.on_tick() is True
    opened.clock.now += SLIDE_SECONDS + 0.01
    assert opened.page.on_tick() is True, "the frame it lands on is drawn"
    assert token not in opened.harness.app.scheduler.animations
    assert opened.page.on_tick() is False

    opened.harness.press("left")
    opened.page.on_unmount()
    assert token not in opened.harness.app.scheduler.animations


def test_with_reduced_motion_the_knob_is_simply_there():
    opened = Opened(80.0, reduced=True)

    opened.harness.press("left")

    assert opened.page.knob_at(opened.clock.now) == 75
    assert opened.page._token not in opened.harness.app.scheduler.animations


# -- the picture ------------------------------------------------------------------------------------------------


def _rail_row(opened: Opened):
    canvas = opened.harness.app.render()
    left, row, width = opened.page._rail
    return [canvas.cells[row][left + cell] for cell in range(width)]


def test_the_rail_runs_through_several_colours_and_the_knob_is_one_dot_with_nothing_following_it():
    opened = Opened(80.0)
    cells = _rail_row(opened)
    colours = {cell.style.foreground for cell in cells}
    assert len(colours) >= 4, "calm to hot, lit and dimmed: not one colour"
    assert sum(cell.character == KNOB for cell in cells) == 1

    opened.harness.press("left")
    for step in range(1, 12):
        opened.clock.now = 1_000.0 + SLIDE_SECONDS * step / 12
        moving = _rail_row(opened)
        assert sum(cell.character == KNOB for cell in moving) == 1, "one knob, never two, at any instant"
        knob = next(index for index, cell in enumerate(moving) if cell.character == KNOB)
        assert all(cell.character == LIT for cell in moving[:knob]), "lit up to the knob and nothing else"
        assert all(cell.character != LIT for cell in moving[knob + 1 :]), "nothing trails behind it"


def test_the_rail_is_wide_enough_that_five_percent_is_several_cells():
    opened = Opened(80.0, width=100)
    _, _, width = opened.page._rail

    assert width >= 60 and width * 0.05 >= 3


def test_the_lit_stretch_ends_at_the_knob_and_the_number_beside_it_follows():
    opened = Opened(50.0)
    cells = _rail_row(opened)
    knob = next(index for index, cell in enumerate(cells) if cell.character == KNOB)
    assert all(cell.character == LIT for cell in cells[:knob])
    assert 0.4 < knob / (len(cells) - 1) < 0.6
    assert "50%" in opened.text()

    opened.harness.press("left")
    assert "was 50%" in opened.text()


def test_a_click_on_the_rail_sends_the_knob_there_and_a_click_elsewhere_does_nothing():
    opened = Opened(80.0)
    opened.harness.render()
    left, row, width = opened.page._rail

    opened.harness.click(left + width - 1, row)
    assert opened.page.percent == 100
    opened.harness.click(left, row)
    assert opened.page.percent == 1
    opened.harness.click(left, row - 3)
    assert opened.page.percent == 1


def test_a_narrow_page_keeps_the_number_and_drops_the_rail():
    opened = Opened(80.0, width=30)

    text = opened.text()

    assert "Compress at" in text and "80%" in text
    assert opened.page._rail is None


# -- writing it down --------------------------------------------------------------------------------------------


@pytest.fixture
def agent(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    monkeypatch.setattr(runtime_module.os, "chdir", lambda _path: None)
    workspace = tmp_path / "work"
    workspace.mkdir()
    config = replace(
        load_config(workspace, path=path),
        store=tmp_path / "sessions",
        plugins_enabled=False,
        skills_enabled=False,
        mcp_enabled=False,
    )
    return TerminalAgent(ZettCodeEngine.preview(config)), path


def models_in(path: Path) -> list[dict]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["models"]


def test_the_share_is_written_to_the_models_entry_and_changes_when_it_is_compacted_at_once(agent):
    shell, path = agent
    window = shell.active_model.context_window

    model, unwritten = shell.change_compact_percent(60)

    assert unwritten is None
    assert models_in(path)[0]["compact_percent"] == 60 and "compact_percent" not in models_in(path)[1]
    assert path.read_text(encoding="utf-8").startswith("# my config\n") and "# second" in path.read_text(
        encoding="utf-8"
    )
    assert shell.active_model.compact_percent == 60 and model.compaction_max_tokens == round(window * 0.6)
    assert shell.runtime.compaction.max_tokens == round(window * 0.6), "the next request is compacted there"


def test_a_share_that_is_not_one_is_refused_and_nothing_is_written(agent):
    shell, path = agent
    before = path.read_text(encoding="utf-8")

    for bad in (0, -5, 100.5):
        with pytest.raises(ValueError, match="more than 0 and at most 100"):
            shell.change_compact_percent(bad)

    assert path.read_text(encoding="utf-8") == before and shell.active_model.compact_percent == 75


def test_a_file_that_cannot_be_edited_still_changes_this_run_and_says_why(agent):
    shell, path = agent
    path.write_text("models = []\n", encoding="utf-8")

    model, unwritten = shell.change_compact_percent(50)

    assert unwritten is not None and shell.active_model.compact_percent == 50
    assert shell.runtime.compaction.max_tokens == round(model.context_window * 0.5)
