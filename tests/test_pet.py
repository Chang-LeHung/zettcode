"""The pet: its sprite and moods, where it stands, how the mouse moves it, and the switch that hides it."""

from __future__ import annotations

from dataclasses import replace

import pytest

from test_statusline import config_file, hidden_in, notices, open_panel  # noqa: F401 - the fixture is used by name
from test_zettcode_app import _harness, build_app
from zettcode.app.pets import DEFAULT_PET, GLAD, IDLE, WORKING, Pet
from zettcode.app.ui.widgets.pet import GLAD_SECONDS, MARGIN, MIN_WIDTH
from zettcode.app.ui.widgets.statusline_page import PARTS, ROW_OF
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.statusline import NAMES, PET, unknown
from zettcode.tui.render import display_width


class Clock:
    now = 1_000.0

    def __call__(self):
        return self.now


def shell(width: int = 100, height: int = 30, *, hidden: tuple[str, ...] = ()):
    """A shell on a screen of the given size, with the clock in the test's hands."""
    app = build_app()
    app.agent.runtime.config = replace(app.agent.runtime.config, statusline_hidden=hidden)
    harness = _harness(app)
    clock = Clock()
    app.app.clock = clock
    harness.resize(width, height)
    harness.render()
    return app, harness, clock


def stands(app, harness):
    """The rectangle the pet occupies after a frame has been painted."""
    harness.render()
    return app.pet.rect


def row_text(app, rect, row: int) -> str:
    cells = app.app.render().cells[rect.y + row][rect.x : rect.x + rect.width]
    return "".join(cell.character for cell in cells)


def sprite_row(pose: str, step: int, row: int) -> str:
    return "".join(span.text for span in DEFAULT_PET.lines(pose, step)[row].spans)


def drag(harness, rect, dx: int, dy: int, *, grab: tuple[int, int] = (2, 1)) -> None:
    x, y = rect.x + grab[0], rect.y + grab[1]
    assert harness.mouse_down(x, y)
    harness.mouse_move(x + dx, y + dy)
    harness.mouse_up(x + dx, y + dy)


# -- the sprite ------------------------------------------------------------------------------------------------


def test_the_default_pet_is_the_mark_drawn_small_with_a_mood_for_work_and_for_a_pat():
    assert DEFAULT_PET.name == "zett"
    assert (DEFAULT_PET.width, DEFAULT_PET.height) == (9, 3)
    assert DEFAULT_PET.frames(IDLE) == 1 and DEFAULT_PET.frames(WORKING) > 1 and DEFAULT_PET.frames(GLAD) > 1
    for pose in (IDLE, WORKING, GLAD):
        for step in range(DEFAULT_PET.frames(pose)):
            lines = DEFAULT_PET.lines(pose, step)
            assert len(lines) == DEFAULT_PET.height
            assert all(display_width(sprite_row(pose, step, row)) == DEFAULT_PET.width for row in range(len(lines)))
    assert DEFAULT_PET.lines(WORKING, 0) != DEFAULT_PET.lines(WORKING, 1), "the heart beats"
    assert DEFAULT_PET.lines(WORKING, 2) == DEFAULT_PET.lines(WORKING, 0), "and the steps go round"


def test_a_pet_without_a_rest_or_with_frames_that_disagree_is_refused():
    palette = {"A": "#ffffff"}
    with pytest.raises(ValueError, match="no 'idle' pose"):
        Pet("x", palette, {GLAD: (("AA", "AA"),)})
    with pytest.raises(ValueError, match="not 2x2"):
        Pet("x", palette, {IDLE: (("AA", "AA"),), GLAD: (("AAA", "AAA"),)})
    with pytest.raises(ValueError, match="whole cells"):
        Pet("x", palette, {IDLE: (("AA", "AA", "AA"),)})
    with pytest.raises(ValueError, match="no frames"):
        Pet("x", palette, {IDLE: (("AA", "AA"),), GLAD: ()})


def test_a_mood_the_pet_lacks_shows_its_rest():
    plain = Pet("plain", {"A": "#ffffff"}, {IDLE: (("AA", "AA"),)})
    assert plain.lines(GLAD, 3) == plain.lines(IDLE)
    assert plain.frames(WORKING) == 1


# -- where it stands --------------------------------------------------------------------------------------------


def test_the_pet_stands_at_the_right_edge_halfway_down_the_conversation_and_is_painted_there():
    app, harness, _ = shell()
    rect, view = stands(app, harness), app.view.rect

    assert (rect.width, rect.height) == (9, 3)
    assert rect.right == view.right - MARGIN
    assert abs((rect.y - view.y) - (view.height - rect.height) / 2) <= 1
    assert [row_text(app, rect, row) for row in range(3)] == [sprite_row(IDLE, 0, row) for row in range(3)], (
        "the cells of the frame are the cells of the sprite"
    )


def test_the_pet_is_not_drawn_where_the_conversation_is_too_narrow_or_too_short_for_it():
    app, harness, _ = shell(width=MIN_WIDTH - 1)
    assert stands(app, harness).empty
    app, harness, _ = shell(height=9)
    assert stands(app, harness).empty
    app, harness, _ = shell(width=MIN_WIDTH, height=30)
    assert not stands(app, harness).empty, "and at the least width it is"


def test_a_pet_that_is_hidden_takes_no_cell_and_catches_no_click():
    app, harness, _ = shell(hidden=("pet",))
    assert stands(app, harness).empty
    harness.mouse_down(app.view.rect.right - MARGIN - 3, app.view.rect.y + app.view.rect.height // 2)
    assert app.pet._grab is None

    app.agent.runtime.config = replace(app.agent.runtime.config, statusline_hidden=())
    app.app.request_layout()
    assert not stands(app, harness).empty, "and showing it again puts it back where it stood"


def test_the_conversation_shows_through_the_cells_the_pet_leaves_empty():
    app, harness, _ = shell()
    app.transcript.append_answer("\n\n".join("word " * 19 for _ in range(40)))
    harness.render()
    rect = stands(app, harness)
    with_pet = [[cell.character for cell in row] for row in app.app.render().cells]
    app.agent.runtime.config = replace(app.agent.runtime.config, statusline_hidden=("pet",))
    app.app.request_layout()
    harness.render()
    without = [[cell.character for cell in row] for row in app.app.render().cells]

    empty = [
        (row, column)
        for row in range(rect.height)
        for column in range(rect.width)
        if sprite_row(IDLE, 0, row)[column] == " "
    ]
    assert empty, "the sprite has corners with nothing in them"
    for row, column in empty:
        assert with_pet[rect.y + row][rect.x + column] == without[rect.y + row][rect.x + column]
    outside = [
        (y, x)
        for y in range(len(with_pet))
        for x in range(len(with_pet[0]))
        if not (rect.y <= y < rect.bottom and rect.x <= x < rect.right)
    ]
    assert all(with_pet[y][x] == without[y][x] for y, x in outside), "and nothing else is touched"


# -- the mouse --------------------------------------------------------------------------------------------------


def test_dragging_the_pet_moves_it_by_the_distance_the_pointer_went_and_marks_nothing_for_copying():
    app, harness, _ = shell()
    before = stands(app, harness)
    copied = app.app.clipboard

    drag(harness, before, -30, 4)

    after = stands(app, harness)
    assert (after.x, after.y) == (before.x - 30, before.y + 4)
    assert app.app._select_anchor is None, "the drag moved the pet, it did not select the cells it crossed"
    assert app.app.clipboard == copied, "so nothing was copied when the button came up"
    assert app.pet.mood == IDLE, "and a drag is not a pat"


def test_a_press_beside_the_pet_is_not_the_pets():
    app, harness, _ = shell()
    rect = stands(app, harness)
    harness.mouse_down(rect.x - 1, rect.y + 1)
    harness.mouse_up(rect.x - 1, rect.y + 1)
    assert app.pet._grab is None and app.pet.mood == IDLE


def test_a_drag_cannot_take_the_pet_out_of_the_conversation():
    app, harness, _ = shell()
    view = app.view.rect
    drag(harness, stands(app, harness), -500, -500)
    rect = stands(app, harness)
    assert (rect.x, rect.y) == (view.x, view.y)

    drag(harness, rect, 500, 500)
    rect = stands(app, harness)
    assert rect.right == view.right - MARGIN and rect.bottom == view.bottom, "the composer below is not covered"


def test_the_pet_keeps_its_place_in_the_conversation_when_the_terminal_is_resized():
    app, harness, _ = shell()
    drag(harness, stands(app, harness), -500, -500)
    harness.resize(140, 44)
    rect = stands(app, harness)
    assert (rect.x, rect.y) == (app.view.rect.x, app.view.rect.y), "in the corner it was left in"

    drag(harness, rect, 32, 6)
    fx, fy = app.pet.fx, app.pet.fy
    harness.resize(100, 30)
    stands(app, harness)
    assert (app.pet.fx, app.pet.fy) == (fx, fy)


def test_a_pat_pleases_the_pet_and_the_clock_ends_it():
    app, harness, clock = shell()
    rect = stands(app, harness)
    token = app.pet._token

    harness.mouse_down(rect.x + 3, rect.y + 1)
    harness.mouse_up(rect.x + 3, rect.y + 1)

    assert app.pet.mood == GLAD and token in app.app.scheduler.animations
    harness.render()
    assert [row_text(app, rect, row) for row in range(3)] == [sprite_row(GLAD, 0, row) for row in range(3)]
    clock.now += GLAD_SECONDS / 2
    harness.render()
    assert row_text(app, rect, 1) == sprite_row(GLAD, 1, 1), "the second frame of the mood"
    clock.now += GLAD_SECONDS
    harness.render()
    assert app.pet.mood == IDLE and token not in app.app.scheduler.animations
    assert row_text(app, rect, 1) == sprite_row(IDLE, 0, 1)


def test_the_wheel_over_the_pet_scrolls_the_conversation_as_it_would_anywhere_else():
    app, harness, _ = shell()
    app.transcript.append_answer("\n\n".join(f"paragraph {n}" for n in range(200)))
    harness.render()
    rect = stands(app, harness)
    assert not app.view.scrolled_up

    harness.scroll(rect.x + 2, rect.y + 1, up=True)

    assert app.view.scrolled_up


# -- the moods --------------------------------------------------------------------------------------------------


def test_the_heart_beats_while_a_request_runs_and_stays_still_with_reduced_motion():
    app, harness, clock = shell()
    rect = stands(app, harness)
    assert app.pet.mood == IDLE
    app._busy = True
    harness.render()
    assert app.pet.mood == WORKING
    first = [row_text(app, rect, row) for row in range(3)]
    clock.now += 0.5
    assert app.pet.on_tick(), "the next frame is a different picture, and the loop is told so"
    harness.render()
    second = [row_text(app, rect, row) for row in range(3)]
    assert first == [sprite_row(WORKING, 0, row) for row in range(3)]
    assert second == [sprite_row(WORKING, 1, row) for row in range(3)] and first != second

    app.app.reduced_motion = True
    clock.now += 0.5
    harness.render()
    assert [row_text(app, rect, row) for row in range(3)] == first


# -- the switch -------------------------------------------------------------------------------------------------


def test_the_pet_is_a_part_of_the_status_line_panel_under_a_heading_of_its_own(tmp_path):
    assert NAMES[-1] == "pet" and PARTS[-1] == PET and ROW_OF["pet"] == "Companion"
    assert unknown(["pet", "app"]) == []
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), statusline_hidden=("pet",))
    assert config.statusline_hidden == ("pet",)


async def test_the_panel_hides_the_pet_and_writes_it_down(config_file):  # noqa: F811
    app, harness = await open_panel(None, size=(120, 44))
    assert not app.pet.rect.empty
    text = harness.render().text
    assert "Companion" in text and PET.summary[:30] in text

    harness.press("end")
    harness.press("left")
    harness.press("enter")

    assert hidden_in(config_file) == {"pet": False}
    assert app.agent.statusline_hidden == {"pet"}
    assert notices(app) == [f"Status line: 1 of {len(NAMES)} parts hidden (pet)"]
    assert stands(app, harness).empty
