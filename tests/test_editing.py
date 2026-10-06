"""The text area's editing keys: one case per binding it registers."""

from __future__ import annotations

from zettcode.tui import TextArea
from zettcode.tui.testing import Harness


def _area(text: str = "hello world", *, position: int | None = None) -> tuple[TextArea, Harness]:
    """Mount an editor over a known draft and return it with its harness."""
    area = TextArea()
    harness = Harness(area, width=40, height=6)
    area.set_text(text)
    if position is not None:
        area.position = position
    return area, harness


def test_the_motion_keys_move_the_cursor_and_clamp_at_the_ends():
    area, harness = _area()

    def at(key: str, start: int, *, alt: bool = False) -> int:
        area.position = start
        harness.press(key, alt=alt)
        return area.position

    assert at("left", 0) == 0
    assert at("left", 11) == 10
    assert at("right", 11) == 11
    assert at("right", 0) == 1
    assert at("home", 6) == 0
    assert at("ctrl_a", 6) == 0
    assert at("end", 0) == 11
    assert at("ctrl_e", 0) == 11
    assert at("ctrl_home", 6) == 0
    assert at("ctrl_end", 0) == 11
    assert at("ctrl_left", 11) == 6
    assert at("alt_left", 11) == 6
    assert at("ctrl_right", 0) == 5
    assert at("alt_right", 0) == 5
    assert at("b", 11, alt=True) == 6
    assert at("f", 0, alt=True) == 5


def test_vertical_motion_keeps_the_column_and_stops_at_the_edges():
    area, harness = _area("one\ntwo\nthree", position=1)

    harness.press("down")
    assert area.position == 5
    harness.press("up")
    assert area.position == 1
    harness.press("up")
    assert area.position == 1


def test_the_editing_keys_delete_insert_and_yank():
    area, harness = _area("hello world", position=5)

    harness.press("delete")
    assert area.text == "helloworld"
    harness.press("ctrl_d")
    assert area.text == "helloorld"
    harness.press("ctrl_w")
    assert area.text == "orld"
    harness.press("ctrl_y")
    assert area.text == "helloorld"
    harness.press("ctrl_u")
    assert area.text == "orld"
    harness.press("ctrl_k")
    assert area.text == ""
    harness.write("abc")
    harness.press("ctrl_z")
    assert area.text == "ab"


def test_the_alt_bindings_move_and_kill_by_word():
    area, harness = _area("one two three", position=13)

    harness.press("b", alt=True)
    assert area.position == 8
    harness.press("f", alt=True)
    assert area.position == 13
    harness.press("b", alt=True)
    harness.press("d", alt=True)
    assert area.text == "one two "
    harness.press("<", alt=True)
    assert area.position == 0
    harness.press(">", alt=True)
    assert area.position == 8


def test_newline_keys_insert_a_row_and_enter_submits():
    submitted: list[str] = []
    area = TextArea(on_submit=lambda value: submitted.append(value) or True)
    harness = Harness(area, width=40, height=6)
    area.set_text("first")

    harness.press("alt_enter")
    assert area.text == "first\n"
    harness.press("shift_enter")
    assert area.text == "first\n\n"
    harness.write("second")
    harness.press("enter")

    assert submitted == ["first\n\nsecond"]
    assert area.text == ""


def test_a_refused_submit_keeps_the_draft_and_a_blank_one_does_nothing():
    area = TextArea(on_submit=lambda value: False)
    harness = Harness(area, width=40, height=6)
    area.set_text("keep me")

    harness.press("enter")

    assert area.text == "keep me"
    area.set_text("   ")
    assert area.value == "   "


def test_history_walks_back_to_the_live_draft():
    area = TextArea()
    harness = Harness(area, width=40, height=6)
    for value in ("first", "second"):
        area.set_text(value)
        harness.press("enter")
    area.set_text("draft")

    harness.press("up")
    assert area.text == "second"
    harness.press("up")
    assert area.text == "first"
    harness.press("up")
    assert area.text == "first"
    harness.press("down")
    assert area.text == "second"
    harness.press("down")
    assert area.text == "draft"
    harness.press("ctrl_p")
    assert area.text == "second"
    harness.press("ctrl_n")
    assert area.text == "draft"
    harness.press("up")
    harness.press("ctrl_g")
    assert area.text == "second"


def test_reverse_search_jumps_to_a_matching_submission():
    area = TextArea()
    harness = Harness(area, width=40, height=6)
    for value in ("alpha", "beta", "gamma"):
        area.set_text(value)
        harness.press("enter")
    area.set_text("et")

    harness.press("ctrl_r")

    assert area.text == "beta"


def test_a_click_focuses_the_editor_and_a_paste_lands_at_the_cursor():
    area, harness = _area("", position=0)

    harness.mouse_down(1, 1)
    assert harness.focused_widget() is area

    harness.write("hi")
    harness.paste(" there")
    assert area.text == "hi there"


def test_an_unknown_key_is_ignored():
    area, harness = _area("keep")

    assert harness.press("f13") is False
    assert area.text == "keep"
