"""The panel ``/config`` opens for one model: names on the left, values on the right, one Enter to save them all."""

from __future__ import annotations

import pytest

from test_config_command import shell  # noqa: F401 - the fixture and the file it starts from
from zettcode.app.ui.widgets import ModelSettingsPage, model_settings_rows
from zettcode.app.ui.widgets.model_settings_page import Action, Setting
from zettcode.tui import MouseAction, MouseEvent


async def _open(fx, name: str = "GPT-4o") -> None:
    await fx.command("/config")
    fx.choose(name)


# -- a screen too short for every row ----------------------------------------------------------------------------


async def test_a_short_screen_shows_the_rows_around_the_cursor_and_marks_that_there_are_more(shell):  # noqa: F811
    fx = shell()
    fx.app.app.resize(110, 16)
    await _open(fx)
    screen = fx.screen()
    assert "Token" in screen and "Remove" not in screen and "\u25bc" in screen and "\u25b2" not in screen

    fx.harness.press("up")  # round to the last row

    screen = fx.screen()
    assert fx.panel.focus_key() == "remove"
    assert "Remove" in screen and "\u25b2" in screen and "\u25bc" not in screen
    assert "Token" not in screen.split("Remove")[0].splitlines()[-1]


async def test_every_row_can_be_reached_and_used_on_a_short_screen(shell):  # noqa: F811
    fx = shell()
    fx.app.app.resize(110, 16)
    await _open(fx)

    fx.act("use")

    assert fx.app.agent.active_model.model == "gpt-4o"


async def test_a_press_on_a_row_that_scrolled_away_goes_nowhere(shell):  # noqa: F811
    fx = shell()
    fx.app.app.resize(110, 16)
    await _open(fx)
    fx.harness.press("up")

    fx.harness.mouse_down(5, 0)  # the conversation above the panel

    assert fx.panel.focus_key() == "remove"


async def test_the_wheel_moves_the_cursor_a_row(shell):  # noqa: F811
    fx = shell()
    await _open(fx)
    row = next(i for i, line in enumerate(fx.screen().splitlines()) if "Address" in line)

    fx.harness.dispatch(MouseEvent(x=20, y=row, action=MouseAction.SCROLL_DOWN))
    assert fx.panel.focus_key() == "api"
    fx.harness.dispatch(MouseEvent(x=20, y=row, action=MouseAction.SCROLL_UP))
    fx.harness.dispatch(MouseEvent(x=20, y=row, action=MouseAction.SCROLL_UP))

    assert fx.panel.focus_key() == "remove", "and it goes round, as the arrows do"


# -- the switch is the one the status line page has ---------------------------------------------------------------


async def test_a_switch_slides_to_its_other_end_and_lands(shell):  # noqa: F811
    fx = shell()
    await _open(fx)
    now = [0.0]
    fx.app.app.clock = lambda: now[0]
    fx.go("web_search")
    row = next(
        child for child in fx.panel.children if getattr(child, "setting", None) and child.setting.key == "web_search"
    )

    fx.harness.press("right")
    assert row.rail.moving and row.rail.selected == 1 and 0.0 <= row.rail.position(now[0]) < 1.0
    now[0] = 5.0
    fx.app.app.tick()

    assert not row.rail.moving and row.rail.position(now[0]) == 1.0


async def test_under_reduced_motion_a_switch_jumps(shell):  # noqa: F811
    fx = shell()
    fx.app.app.reduced_motion = True
    await _open(fx)
    fx.go("multimodal")
    row = next(
        child for child in fx.panel.children if getattr(child, "setting", None) and child.setting.key == "multimodal"
    )

    fx.harness.press("right")

    assert not row.rail.moving and row.rail.position(0.0) == 1.0


# -- the page on its own ----------------------------------------------------------------------------------------------


def test_the_height_of_a_panel_is_its_rows_a_blank_before_the_actions_and_the_chrome():
    assert model_settings_rows(11, 2) == 5 + 11 + 3
    assert model_settings_rows(3, 0) == 5 + 3


def test_a_panel_needs_a_setting():
    with pytest.raises(ValueError, match="at least one setting"):
        ModelSettingsPage("x", [], on_save=lambda v: None, on_action=lambda a, v: None, on_cancel=lambda: None)


def test_the_editor_of_a_row_that_is_not_typed_is_an_error():
    page = ModelSettingsPage(
        "x",
        [Setting("on", "On", "switch", words=("off", "on")), Setting("name", "Name")],
        [Action("go", "Go", "does it")],
        on_save=lambda v: None,
        on_action=lambda a, v: None,
        on_cancel=lambda: None,
    )

    assert page.editor("name").text == ""
    with pytest.raises(KeyError):
        page.editor("on")
    with pytest.raises(KeyError):
        page.editor("go")
    assert page.values == {"on": False, "name": ""}
