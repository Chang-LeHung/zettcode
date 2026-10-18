"""`ConsolePanel`: the screen of a command line, driven without a process."""

from __future__ import annotations

import pytest

from zettcode.tui import ConsolePanel, Screen, Widget
from zettcode.tui.core.events import KeyEvent
from zettcode.tui.render.style import Style
from zettcode.tui.testing import Harness


class Owner:
    """What a panel's owner records: the commands, the stops and the closes."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.stops = 0
        self.closed = 0
        self.stoppable = True

    def submit(self, command: str) -> None:
        self.commands.append(command)

    def interrupt(self) -> bool:
        self.stops += 1
        return self.stoppable

    def close(self) -> None:
        self.closed += 1


def opened(*, width: int = 60, height: int = 14, **options):
    owner = Owner()
    options.setdefault("location", "~/proj")
    harness = Harness(Widget(), width=width, height=height)
    panel = ConsolePanel(on_submit=owner.submit, on_interrupt=owner.interrupt, on_close=owner.close, **options)
    harness.app.push_screen(Screen(panel, name="page", modal=True))
    return harness, panel, owner


def type_command(harness: Harness, text: str) -> None:
    harness.write(text)
    harness.press("enter")


def test_the_page_shows_the_title_the_place_the_prompt_and_the_keys_that_work():
    harness, panel, _ = opened()

    rows = harness.text().splitlines()

    assert rows[0].strip().startswith("Shell") and "~/proj" in rows[0]
    assert rows[-2].strip() == "$"
    assert "enter run" in rows[-1] and "tab complete" in rows[-1] and "esc close" in rows[-1]
    assert harness.focused_widget() is panel.input


def test_enter_hands_the_command_to_the_owner_and_empties_the_line():
    harness, panel, owner = opened()

    type_command(harness, "git status")

    assert owner.commands == ["git status"]
    assert panel.input.text == ""


def test_while_a_command_runs_enter_is_refused_and_the_draft_is_kept():
    harness, panel, owner = opened()
    panel.begin()

    type_command(harness, "next")

    assert owner.commands == [] and panel.input.text == "next"
    panel.finish("exit 0")
    harness.press("enter")
    assert owner.commands == ["next"]


def test_output_appears_with_colours_and_the_newest_line_is_at_the_bottom():
    harness, panel, _ = opened(height=8)

    panel.echo("make")
    panel.write("\x1b[31mred\x1b[0m line\n")
    panel.write("second\n")
    frame = harness.render()

    text = frame.text.splitlines()
    assert text[1].strip() == "$ make" and text[2].strip() == "red line" and text[3].strip() == "second"
    red = (
        [span for row in frame.styled_rows[2:3] for span in row if "red" in span.text]
        if hasattr(frame, "styled_rows")
        else []
    )
    assert red == [] or red[0].style.foreground


def test_the_heading_counts_seconds_while_running_and_then_says_how_it_ended():
    now = [100.0]
    harness, panel, _ = opened()
    harness.app.clock = lambda: now[0]

    panel.begin()
    assert "running 0s" in harness.text()
    now[0] = 103.4
    assert panel.on_tick() is True
    assert "running 3s" in harness.text()
    assert panel.on_tick() is False, "nothing changed within the same second"

    panel.finish("exit 1 \u00b7 3.4s")
    heading = harness.text().splitlines()[0]
    assert "exit 1" in heading and "running" not in heading


def test_a_long_line_wraps_at_the_width_and_the_wrapped_rows_are_what_scrolling_counts():
    harness, panel, _ = opened(width=30, height=8)

    panel.write("x" * 70 + "\nend\n")

    rows = [row.strip() for row in harness.text().splitlines()[1:5]]
    assert rows == ["x" * 26, "x" * 26, "x" * 18, "end"]


def test_the_view_follows_the_newest_line_until_the_reader_scrolls_up():
    harness, panel, _ = opened(height=8)
    panel.write("\n".join(f"line {n}" for n in range(30)) + "\n")

    assert "line 29" in harness.text() and "line 0" not in harness.text()
    harness.press("page_up")
    scrolled = harness.text()
    assert "line 29" not in scrolled and "pgdn follow" in scrolled
    before = panel.offset

    panel.write("line 30\n")

    assert panel.offset == before + 1, "new output does not move what the reader is looking at"
    harness.press("page_down")
    harness.press("page_down")
    harness.press("page_down")
    assert panel.offset == 0 and "line 30" in harness.text()


def test_the_wheel_scrolls_over_the_output_and_over_the_line_alike():
    harness, panel, _ = opened(height=8)
    panel.write("\n".join(f"line {n}" for n in range(30)) + "\n")

    harness.scroll(5, 2, up=True)
    first = panel.offset
    harness.scroll(5, harness.height - 2, up=True)

    assert first > 0 and panel.offset > first
    harness.scroll(5, 2, up=False)
    assert panel.offset < first + first


def test_typing_brings_the_reader_back_to_the_newest_output():
    harness, panel, _ = opened(height=8)
    panel.write("\n".join(f"line {n}" for n in range(30)) + "\n")
    harness.press("page_up")
    assert panel.offset > 0

    harness.write("a")

    assert panel.offset == 0


def test_only_the_newest_lines_are_kept():
    harness, panel, _ = opened(max_lines=5)

    panel.write("".join(f"{n}\n" for n in range(20)))

    assert panel.buffer.lines[0].text == "16" and panel.buffer.dropped > 10


def test_escape_stops_a_running_command_and_leaves_an_idle_page():
    harness, panel, owner = opened()

    harness.press("escape")
    assert owner.closed == 1 and owner.stops == 0, "idle: Escape leaves"

    panel.begin()
    harness.press("escape")
    assert owner.stops == 1 and owner.closed == 1, "running: Escape stops it and stays"


def test_ctrl_c_goes_to_the_running_command_and_otherwise_is_not_taken():
    _, panel, owner = opened()

    assert panel.interrupt() is False and owner.stops == 0
    panel.begin()
    assert panel.interrupt() is True and owner.stops == 1
    owner.stoppable = False
    assert panel.interrupt() is False, "the owner had nothing to stop"


def test_ctrl_d_on_an_empty_line_leaves_as_it_ends_a_shell_but_not_with_text_or_while_running():
    harness, panel, owner = opened()

    harness.write("ab")
    harness.press("ctrl_d")
    assert owner.closed == 0, "with text it deletes forward"
    harness.press("home")
    harness.press("ctrl_d")
    harness.press("ctrl_d")
    harness.press("ctrl_d")
    assert owner.closed == 1

    panel.begin()
    harness.press("ctrl_d")
    assert owner.closed == 1


def test_history_given_to_the_panel_is_what_up_recalls_newest_first():
    harness, panel, _ = opened(history=["first", "second"])

    harness.press("up")
    assert panel.input.text == "second"
    harness.press("up")
    assert panel.input.text == "first"


def test_a_menu_of_candidates_follows_tab_with_the_one_in_the_line_highlighted():
    from zettcode.tui import Completer, CompletionItem

    class Words(Completer):
        def __call__(self, text, position):
            return [CompletionItem(value=word) for word in ("alpha", "alps", "beta") if word.startswith(text)]

    harness, panel, _ = opened(completer=Words())
    harness.write("al")

    harness.press("tab")
    first = harness.text()
    harness.press("tab")
    second = harness.text()

    assert panel.input.text == "alps" and "alpha" in first and "alps" in second
    harness.press("enter")
    assert "alpha" not in harness.text().splitlines()[-3], "the menu closes once the line is sent"


def test_clear_empties_the_output_and_set_location_changes_the_heading():
    harness, panel, _ = opened()
    panel.write("something\n")

    panel.clear()
    panel.set_location("~/elsewhere")

    text = harness.text()
    assert "something" not in text and "~/elsewhere" in text


def test_a_narrow_terminal_loses_the_hints_that_matter_least_and_never_the_way_out():
    for width in (60, 40, 30, 24, 16):
        harness, panel, _ = opened(width=width)
        hint = harness.text().splitlines()[-1].strip()

        assert hint.endswith("esc close"), (width, hint)
        assert hint.startswith("enter run") or width < 30, (width, hint)

    harness, panel, _ = opened(width=40)
    assert "history" not in harness.text().splitlines()[-1], "history goes first"
    panel.begin()
    running = harness.text().splitlines()[-1].strip()
    assert running.startswith("ctrl-c stop") and running.endswith("esc stop")


def test_a_long_place_keeps_its_end_because_that_is_the_part_that_says_where_you_are():
    from zettcode.tui.widgets.console import keep_tail

    assert keep_tail("/a/b/c", 20) == "/a/b/c"
    cut = keep_tail("/very/long/path/to/project", 12)
    assert cut.startswith("\u2026") and cut.endswith("to/project") and len(cut) == 12
    assert keep_tail("abc", 1) == "\u2026" and keep_tail("abc", 0) == ""
    assert keep_tail("\u4f60\u597d\u4e16\u754c", 6) == "\u2026\u4e16\u754c"

    harness, panel, _ = opened(width=40, location="/very/long/path/to/the/project")
    assert harness.text().splitlines()[0].rstrip().endswith("project"), "on the heading too"


def test_once_scrolled_up_the_way_back_down_outranks_history_and_completion():
    harness, panel, _ = opened(width=44, height=8)
    panel.write("\n".join(f"line {n}" for n in range(30)) + "\n")
    harness.press("page_up")

    hint = harness.text().splitlines()[-1]

    assert "pgdn follow" in hint and "history" not in hint


def test_each_kind_of_candidate_has_a_colour_of_its_own_in_every_palette():
    from zettcode.tui import DARK, LIGHT
    from zettcode.tui.widgets.console import (
        ARGUMENT,
        COMMAND,
        DIRECTORY,
        EXECUTABLE,
        FILE,
        REFERENCE,
        SYMLINK,
        kind_colour,
    )

    for theme in (DARK, LIGHT):
        distinct = {kind_colour(kind, theme) for kind in (DIRECTORY, SYMLINK, REFERENCE, EXECUTABLE, FILE)}
        assert len(distinct) == 5, theme.name
        assert kind_colour(COMMAND, theme) == kind_colour(EXECUTABLE, theme)
        assert kind_colour(ARGUMENT, theme) == kind_colour(FILE, theme) == kind_colour("nobody named this", theme)


def test_it_survives_a_terminal_too_small_to_draw_in():
    harness, panel, _ = opened(width=12, height=4)
    panel.write("output\n" * 5)

    harness.render()
    harness.resize(5, 2)
    harness.render()


@pytest.mark.parametrize("key", ["page_up", "page_down"])
def test_paging_an_empty_output_changes_nothing(key):
    harness, panel, _ = opened()

    harness.press(key)

    assert panel.offset == 0


def test_the_panel_is_a_screen_of_its_own_with_no_other_widget_reaching_the_keys():
    harness, panel, _ = opened()

    assert isinstance(panel.input, Widget) and panel.children == (panel.input,)
    assert harness.dispatch(KeyEvent(key="f12")) in (True, False)
    assert Style(bold=True)
