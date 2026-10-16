"""The locked composer: no arrow, a lock in the middle, and nothing typed except a command."""

from __future__ import annotations

import pytest

from zettcode.app.ui.widgets import Composer
from zettcode.app.ui.widgets.composer import LOCK
from zettcode.tui import PROMPT
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness


def _composer(**options) -> tuple[Composer, Harness, list[str]]:
    submitted: list[str] = []
    composer = Composer(
        prompt=f"{PROMPT} ",
        placeholder="Ask ZettCode to do anything",
        on_submit=lambda text: submitted.append(text) or True,
        surface=True,
        **options,
    )
    harness = Harness(composer, width=40, height=5)
    harness.render()
    return composer, harness, submitted


def _rows(harness: Harness) -> list[str]:
    return harness.render().text.splitlines()


# -- what it looks like --------------------------------------------------------------------------------------------


def test_an_unlocked_composer_has_its_arrow_and_its_hint():
    _, harness, _ = _composer()

    text = harness.render().text

    assert f"{PROMPT} Ask ZettCode to do anything" in text and LOCK not in text


def test_a_locked_composer_has_no_arrow_and_no_hint_and_a_lock():
    composer, harness, _ = _composer()

    composer.locked = True
    text = harness.render().text

    assert PROMPT not in text and "Ask ZettCode" not in text
    assert LOCK in text


def test_the_lock_is_in_the_middle_of_the_row_and_of_the_composer():
    composer, harness, _ = _composer()
    composer.locked = True

    rows = _rows(harness)
    row = next(index for index, text in enumerate(rows) if LOCK in text)

    assert row == 2, "the middle of the three rows of a one-line composer with its band above and below"
    column = rows[row].index(LOCK)
    assert abs((column + display_width(LOCK) / 2) - 40 / 2) <= 1, "and across the width"


@pytest.mark.parametrize("width", [3, 4, 5, 10, 41, 80])
def test_the_lock_stays_inside_the_composer_at_any_width(width):
    composer = Composer(prompt=f"{PROMPT} ", placeholder="hint", surface=True)
    harness = Harness(composer, width=width, height=3)
    composer.locked = True

    rows = _rows(harness)

    assert all(display_width(row) <= width for row in rows)
    assert any(LOCK in row for row in rows)


def test_a_composer_one_row_high_without_a_band_puts_the_lock_on_that_row():
    composer = Composer(prompt=f"{PROMPT} ", placeholder="hint")
    harness = Harness(composer, width=20, height=1)
    composer.locked = True

    assert LOCK in _rows(harness)[0] and PROMPT not in _rows(harness)[0]


def test_the_lock_has_no_cursor_beside_it():
    composer, harness, _ = _composer()
    assert composer.cursor() is not None
    composer.locked = True
    harness.render()

    assert composer.cursor() is None


def test_unlocking_brings_the_arrow_the_hint_and_the_cursor_back():
    composer, harness, _ = _composer()
    composer.locked = True
    harness.render()

    composer.locked = False
    text = harness.render().text

    assert f"{PROMPT} Ask ZettCode" in text and LOCK not in text and composer.cursor() is not None


def test_a_command_being_typed_has_the_lock_where_its_arrow_was():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.write("/res")
    text = harness.render().text

    assert f"{LOCK} /res" in text and PROMPT not in text
    assert composer.cursor() is not None


# -- what it takes -------------------------------------------------------------------------------------------------


def test_text_that_is_not_a_command_is_not_taken():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.write("hello")

    assert composer.text == ""


def test_a_slash_opens_a_command_and_the_rest_of_it_is_taken():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.write("/resume abc")

    assert composer.text == "/resume abc"


def test_a_space_before_the_slash_is_not_taken_so_the_command_is_what_ends_up_in_the_draft():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.write(" /new")

    assert composer.text == "/new"


def test_a_command_runs_on_enter():
    composer, harness, submitted = _composer()
    composer.locked = True

    harness.write("/new")
    harness.press("enter")

    assert submitted == ["/new"]


def test_a_paste_that_is_not_a_command_is_not_taken_and_one_that_is_is():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.paste("some text the reader copied")
    assert composer.text == ""
    harness.paste("/help")
    assert composer.text == "/help"


def test_a_picture_is_not_taken():
    composer, _, _ = _composer()
    composer.locked = True

    assert composer.attach_image(b"png", "image/png") == "" and composer.images == {} and composer.text == ""


def test_a_picture_is_taken_again_once_unlocked():
    composer, _, _ = _composer()
    composer.locked = True
    composer.attach_image(b"png", "image/png")
    composer.locked = False

    assert composer.attach_image(b"png", "image/png") == "[image #1]"


def test_the_arrow_keys_and_the_editing_keys_still_work_in_a_command():
    composer, harness, _ = _composer()
    composer.locked = True
    harness.write("/resume")

    harness.press("left")
    harness.press("backspace")

    assert composer.text == "/resue"


def test_a_draft_left_over_from_the_session_that_was_left_can_be_deleted_but_not_added_to():
    composer, harness, _ = _composer()
    composer.set_text("half a thought")
    composer.locked = True
    harness.render()

    harness.write("!")
    assert composer.text == "half a thought", "nothing may be added to it"
    harness.press("backspace")
    assert composer.text == "half a though"
    for _ in range(20):
        harness.press("backspace")

    assert composer.text == ""


def test_recalling_an_earlier_message_with_the_arrow_keys_is_refused_when_it_is_not_a_command():
    composer, harness, _ = _composer()
    composer.locked = True
    composer.commit("an earlier message")
    composer.commit("/help")

    harness.press("up")
    assert composer.text == "/help"
    harness.press("up")

    assert composer.text == "/help", "the earlier message is not a command and is not recalled"


def test_ctrl_z_cannot_bring_back_text_that_was_refused():
    composer, harness, _ = _composer()
    composer.locked = True

    harness.write("nope")
    harness.press("ctrl_z")

    assert composer.text == ""


def test_the_keys_the_composer_does_not_use_still_reach_the_application():
    composer, harness, _ = _composer()
    composer.locked = True

    assert harness.press("page_up") is False and harness.press("ctrl_c") is False
    assert composer.text == ""


def test_enter_on_the_lock_asks_to_try_again_and_is_not_a_submission():
    composer, harness, submitted = _composer()
    asked: list[bool] = []
    composer.on_locked_enter = lambda: asked.append(True)
    composer.locked = True

    harness.press("enter")

    assert asked == [True] and submitted == []


def test_enter_on_a_blank_draft_asks_too_but_enter_on_a_command_runs_it():
    composer, harness, submitted = _composer()
    asked: list[bool] = []
    composer.on_locked_enter = lambda: asked.append(True)
    composer.locked = True
    composer.set_text("   ")

    harness.press("enter")
    composer.set_text("/help")
    harness.press("enter")

    assert asked == [True] and submitted == ["/help"]


def test_a_locked_composer_with_nobody_to_ask_is_still_safe():
    composer, harness, _ = _composer()
    composer.locked = True

    assert harness.press("enter") is True


def test_enter_does_nothing_special_once_unlocked():
    composer, harness, submitted = _composer()
    composer.on_locked_enter = lambda: submitted.append("asked")
    composer.set_text("hello")

    harness.press("enter")

    assert submitted == ["hello"]
