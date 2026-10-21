"""The pet over the conversation: where it stands, how the mouse moves it, its moods, and the switch that hides it."""

from __future__ import annotations

from dataclasses import replace

import pytest

from test_statusline import config_file, hidden_in, notices, open_panel  # noqa: F401 - the fixture is used by name
from test_zettcode_app import _harness, _type_command, build_app
from zettcode._compat import tomllib
from zettcode.app.pets import GLAD, IDLE, WORKING, PetCatalog, bundled_pets
from zettcode.app.ui.widgets.pet import FRAME_SECONDS, GLAD_SECONDS, MARGIN, MIN_WIDTH
from zettcode.app.ui.widgets.statusline_page import PARTS, ROW_OF
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.config_edit import set_pet_position
from zettcode.statusline import NAMES, PET, unknown

#: The pet a shell starts with when nothing says otherwise.
CAT = PetCatalog(bundled_pets()).load("cat")


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


def painted(app, rect) -> list[list[tuple]]:
    """What the frame holds where the pet stands: each cell's character and colours."""
    rows = app.app.render().cells[rect.y : rect.bottom]
    return [[(c.character, c.style.foreground, c.style.background) for c in row[rect.x : rect.right]] for row in rows]


def sprite(pose: str, step: int = 0, pet=CAT) -> list[list[tuple | None]]:
    """The sprite's cells as the canvas would hold them; a cell it leaves empty is ``None``."""
    rows = []
    for line in pet.lines(pose, step):
        row: list[tuple | None] = []
        for span in line.spans:
            for character in span.text:
                empty = character == " " and span.style.background is None
                row.append(None if empty else (character, span.style.foreground, span.style.background))
        rows.append(row)
    return rows


def shows(app, rect, pose: str, step: int = 0, pet=CAT) -> bool:
    """Whether the cells where the pet stands are those of one frame of the sprite.

    A cell the sprite leaves empty is the conversation's, and a cell with no background of its own takes the
    one that was under it.
    """
    return all(
        want is None or (want[:2] == got[:2] and (want[2] is None or want[2] == got[2]))
        for wanted, held in zip(sprite(pose, step, pet), painted(app, rect), strict=True)
        for want, got in zip(wanted, held, strict=True)
    )


def drag(harness, rect, dx: int, dy: int, *, grab: tuple[int, int] = (2, 1)) -> None:
    x, y = rect.x + grab[0], rect.y + grab[1]
    assert harness.mouse_down(x, y)
    harness.mouse_move(x + dx, y + dy)
    harness.mouse_up(x + dx, y + dy)


# -- where it stands --------------------------------------------------------------------------------------------


def test_the_pet_starts_as_the_cat_at_the_right_edge_halfway_down_its_ground():
    app, harness, _ = shell()
    rect, ground = stands(app, harness), app._pet_area()

    assert app.pet.pet.name == "cat"
    assert (rect.width, rect.height) == (CAT.width, CAT.height)
    assert rect.right == ground.right - MARGIN
    assert abs((rect.y - ground.y) - (ground.height - rect.height) / 2) <= 1
    assert shows(app, rect, IDLE), "the cells of the frame are the cells of the sprite"


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
        (row, column) for row in range(rect.height) for column in range(rect.width) if sprite(IDLE)[row][column] is None
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


def test_another_pet_stands_where_the_last_one_did():
    app, harness, _ = shell()
    drag(harness, stands(app, harness), -20, 3)
    before = (app.pet.fx, app.pet.fy)
    dog = app.agent.pets.load("dog")

    app.pet.set_pet(dog)

    rect = stands(app, harness)
    assert app.pet.pet is dog and (app.pet.fx, app.pet.fy) == before
    assert shows(app, rect, IDLE, pet=dog) and not shows(app, rect, IDLE, pet=CAT)


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


def test_a_drag_cannot_take_the_pet_out_of_the_conversation_and_the_composer_or_onto_the_bars():
    app, harness, _ = shell()
    ground = app._pet_area()
    drag(harness, stands(app, harness), -500, -500)
    rect = stands(app, harness)
    assert (rect.x, rect.y) == (ground.x, ground.y)
    assert rect.y == app.view.rect.y and rect.y > app.header.rect.y, "the header is not its ground"

    drag(harness, rect, 500, 500)
    rect = stands(app, harness)
    assert rect.right == ground.right - MARGIN and rect.bottom == ground.bottom
    assert rect.bottom == app.composer.rect.bottom and rect.bottom <= app.status.rect.y, "nor is the status line"


def test_the_pet_can_be_put_on_the_composer_and_what_it_leaves_empty_shows_the_draft():
    app, harness, _ = shell()
    app.composer.set_text("a draft that is long enough to reach the right-hand side of the box " * 2)
    harness.render()
    composer = app.composer.rect
    rect = stands(app, harness)
    # Pick the pet up and put it as low as it goes: the bottom of its ground is the bottom of the composer.
    x, y = rect.x + 3, rect.y + 1
    assert harness.mouse_down(x, y)
    harness.mouse_move(x, y + 500)
    harness.mouse_up(x, y + 500)

    rect = stands(app, harness)
    assert rect.bottom == composer.bottom and rect.bottom > composer.y, "it stands on the composer"
    assert rect.right == app._pet_area().right - MARGIN
    assert shows(app, rect, IDLE), "and is drawn over it"
    assert app.composer.text.startswith("a draft"), "the draft itself is untouched"


def test_a_press_on_the_pet_over_the_composer_is_the_pets_and_a_press_beside_it_is_the_composers():
    app, harness, _ = shell()
    composer = app.composer.rect
    rect = stands(app, harness)
    drag(harness, rect, 0, 500, grab=(2, 1))
    rect = stands(app, harness)
    assert rect.bottom > composer.y, "it stands on the composer"

    harness.mouse_down(rect.x - 3, composer.bottom - 1)
    harness.mouse_up(rect.x - 3, composer.bottom - 1)
    assert app.pet._grab is None, "beside it, the composer is pressed and the pet is not"
    assert app.composer.focused

    harness.mouse_down(rect.x + 3, composer.bottom - 1)
    assert app.pet._grab is not None, "on it, the pet"
    harness.mouse_up(rect.x + 3, composer.bottom - 1)


def test_the_ground_runs_from_the_top_of_the_conversation_to_the_bottom_of_the_composer_and_follows_it():
    app, harness, _ = shell()
    ground = app._pet_area()
    assert ground.y == app.view.rect.y and ground.bottom == app.composer.rect.bottom

    app.composer.set_text("one\ntwo\nthree")
    harness.render()
    grown = app._pet_area()
    assert grown.bottom == app.composer.rect.bottom and grown.y == ground.y
    assert grown.height >= ground.height - 3, "the composer took rows from the conversation but not from the ground"


async def test_an_open_panel_covers_the_pet_wherever_it_stands(config_file):  # noqa: F811
    app, harness, _ = shell(width=120, height=44)
    drag(harness, stands(app, harness), 0, 500)
    rect = stands(app, harness)
    assert shows(app, rect, IDLE), "on the composer, the pet is drawn"

    await _type_command(app, harness, "/statusline")
    harness.render()

    assert app.app.screens.top.name == "page"
    assert not shows(app, rect, IDLE), "a panel opened over it hides it, as it hides the conversation"


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


def test_the_pet_follows_the_pointer_back_at_once_after_the_pointer_went_past_the_edge():
    """The pointer went on after the pet stopped at the edge; the way back must not first cross the overshoot."""
    app, harness, _ = shell(width=100, height=30)
    start = stands(app, harness)
    edge = start.x
    x, y = start.x + 7, start.y + 3  # held at its middle
    assert harness.mouse_down(x, y)

    for pointer in (x + 20, x + 60, x + 400):
        harness.mouse_move(pointer, y)
        assert stands(app, harness).x == edge, "the edge stops it"

    harness.mouse_move(x + 399, y)
    assert stands(app, harness).x == edge - 1, "and one cell back moves it one cell"
    harness.mouse_move(x + 390, y)
    assert stands(app, harness).x == edge - 10
    harness.mouse_up(x + 390, y)


def test_the_same_holds_for_the_other_edges_and_for_a_hold_at_the_far_side_of_the_pet():
    app, harness, _ = shell(width=100, height=30)
    view = app._pet_area()
    rect = stands(app, harness)
    # Held at its right-hand column and its bottom row, and pushed into the bottom-right corner.
    x, y = rect.right - 1, rect.bottom - 1
    assert harness.mouse_down(x, y)
    harness.mouse_move(x + 200, y + 200)
    corner = stands(app, harness)
    assert corner.right == view.right - MARGIN and corner.bottom == view.bottom

    harness.mouse_move(x + 199, y + 198)
    back = stands(app, harness)
    assert (back.x, back.y) == (corner.x - 1, corner.y - 2), "both directions come back at the first step"

    # And into the top-left corner, from there.
    harness.mouse_move(x - 500, y - 500)
    top_left = stands(app, harness)
    assert (top_left.x, top_left.y) == (view.x, view.y)
    harness.mouse_move(x - 497, y - 499)
    moved = stands(app, harness)
    assert (moved.x, moved.y) == (view.x + 3, view.y + 1)
    harness.mouse_up(x - 497, y - 499)


def test_a_drag_the_edge_swallows_whole_is_still_a_drag_and_not_a_pat():
    """Whether the pointer moved is decided by the pointer, not by whether the area let the pet follow it."""
    app, harness, _ = shell()
    rect = stands(app, harness)  # at the right edge already, so a move to the right goes nowhere
    x, y = rect.x + 3, rect.y + 1
    assert harness.mouse_down(x, y)
    harness.mouse_move(x + 6, y)
    assert stands(app, harness) == rect
    harness.mouse_up(x + 6, y)

    assert app.pet.mood == IDLE, "nothing patted it"


def test_a_press_that_never_leaves_its_cell_is_still_a_pat():
    app, harness, _ = shell()
    rect = stands(app, harness)
    x, y = rect.x + 3, rect.y + 1
    harness.mouse_down(x, y)
    harness.mouse_move(x, y)
    harness.mouse_up(x, y)
    assert app.pet.mood == GLAD


# -- remembering where it was left ------------------------------------------------------------------------------


def test_where_the_pet_was_left_is_written_to_the_config_file_when_the_drag_ends(config_file):  # noqa: F811
    app, harness, _ = shell()
    rect = stands(app, harness)
    assert harness.mouse_down(rect.x + 2, rect.y + 1)
    harness.mouse_move(rect.x - 28, rect.y + 5)
    assert "pet_position" not in config_file.read_text(encoding="utf-8"), "nothing is written while it is held"
    harness.mouse_up(rect.x - 28, rect.y + 5)

    saved = tomllib.loads(config_file.read_text(encoding="utf-8"))["ui"]["pet_position"]
    assert saved == [round(app.pet.fx, 3), round(app.pet.fy, 3)]
    assert app.agent.runtime.config.pet_position == tuple(saved)
    assert config_file.read_text(encoding="utf-8").count("[[models]]") == 1, "and the rest of the file is as it was"


def test_a_pat_writes_nothing(config_file):  # noqa: F811
    app, harness, _ = shell()
    rect = stands(app, harness)
    harness.mouse_down(rect.x + 2, rect.y + 1)
    harness.mouse_up(rect.x + 2, rect.y + 1)
    assert "pet_position" not in config_file.read_text(encoding="utf-8")


def test_the_pet_starts_where_it_was_left_and_that_place_is_a_share_of_the_room_so_it_survives_a_resize():
    app = build_app()
    app.agent.runtime.config = replace(app.agent.runtime.config, pet_position=(0.25, 0.75))
    app = type(app)(app.agent)
    harness = _harness(app)
    harness.resize(100, 30)
    harness.render()
    small = app.pet.rect
    harness.resize(140, 44)
    harness.render()

    assert (app.pet.fx, app.pet.fy) == (0.25, 0.75)
    view = app.view.rect
    assert abs((app.pet.rect.x - view.x) - round(0.25 * (view.width - app.pet.rect.width - MARGIN))) <= 1
    assert abs((small.x - 0) - round(0.25 * (100 - small.width - MARGIN))) <= 1, "and before the resize too"


def test_a_reader_with_no_config_file_loses_nothing_but_the_memory():
    """The environment can be the whole configuration; a drag then has nowhere to be written, and says nothing."""
    app, harness, _ = shell()
    rect = stands(app, harness)
    harness.mouse_down(rect.x + 2, rect.y + 1)
    harness.mouse_move(rect.x - 10, rect.y)
    harness.mouse_up(rect.x - 10, rect.y)
    assert not any(getattr(entry, "level", None) == "error" for entry in app.transcript.entries)


def test_the_config_reads_the_position_and_refuses_what_is_not_two_shares(tmp_path):
    from test_pets import config_in

    assert config_in(tmp_path, "").pet_position is None
    assert config_in(tmp_path, "[ui]\npet_position = [0.25, 1]\n").pet_position == (0.25, 1.0)
    for bad in ("[0.5]", "[1.5, 0.5]", "[0.5, -0.1]", '["a", "b"]', "0.5", "[true, 0.5]"):
        with pytest.raises(ValueError, match="pet_position"):
            config_in(tmp_path, f"[ui]\npet_position = {bad}\n")


def test_the_edit_changes_one_line_and_nothing_else(tmp_path):
    where = tmp_path / "config.toml"
    original = '[[models]]\nmodel = "m"\ntoken = "t"\n\n[ui]\npet = "dog"  # mine\n'

    edited_text = set_pet_position(original, 0.123456, 0.9, where=where)

    assert edited_text == original.replace("[ui]\n", "[ui]\npet_position = [0.123, 0.9]\n")
    assert set_pet_position(edited_text, 1.0, 0.0, where=where).count("pet_position") == 1
    assert tomllib.loads(set_pet_position("", 7.0, -3.0, where=where))["ui"]["pet_position"] == [1.0, 0.0]


def test_a_pat_pleases_the_pet_and_the_clock_ends_it():
    app, harness, clock = shell()
    rect = stands(app, harness)
    token = app.pet._token

    harness.mouse_down(rect.x + 3, rect.y + 1)
    harness.mouse_up(rect.x + 3, rect.y + 1)

    assert app.pet.mood == GLAD and token in app.app.scheduler.animations
    harness.render()
    assert shows(app, rect, GLAD, 0)
    clock.now += FRAME_SECONDS
    harness.render()
    assert shows(app, rect, GLAD, 1) and not shows(app, rect, GLAD, 0), "the second frame of the mood"
    clock.now += GLAD_SECONDS
    harness.render()
    assert app.pet.mood == IDLE and token not in app.app.scheduler.animations
    assert shows(app, rect, IDLE)


def test_the_wheel_over_the_pet_scrolls_the_conversation_as_it_would_anywhere_else():
    app, harness, _ = shell()
    app.transcript.append_answer("\n\n".join(f"paragraph {n}" for n in range(200)))
    harness.render()
    rect = stands(app, harness)
    assert not app.view.scrolled_up

    harness.scroll(rect.x + 2, rect.y + 1, up=True)

    assert app.view.scrolled_up


# -- the moods --------------------------------------------------------------------------------------------------


def test_the_pet_wakes_while_a_request_runs_and_stays_still_with_reduced_motion():
    app, harness, clock = shell()
    assert app.pet.mood == IDLE
    app._busy = True
    harness.render()
    assert app.pet.mood == WORKING
    rect = stands(app, harness)
    first = painted(app, rect)
    mood, step = app.pet._drawn
    assert mood == WORKING and shows(app, rect, WORKING, step)
    clock.now += 0.5
    assert app.pet.on_tick(), "the next frame is a different picture, and the loop is told so"
    harness.render()
    second = painted(app, rect)
    assert shows(app, rect, WORKING, step + 1) and first != second

    app.app.reduced_motion = True
    clock.now += 0.5
    harness.render()
    assert shows(app, rect, WORKING, 0), "with reduced motion the pet keeps the first frame of the mood"


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
