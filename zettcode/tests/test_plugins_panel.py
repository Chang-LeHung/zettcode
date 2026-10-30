"""The page ``/plugins`` opens: the plugins a reader can switch, the program's own first.

The rows come from the engine's catalog and the writing is the command's; what is tested here is the page — how it
groups, what it draws, and what a key or a click does to it.
"""

from __future__ import annotations

from zettcode.app.ui.widgets.plugins_page import BUILTIN, INSTALLED, OFF_IN_CONFIG, PluginRow, PluginsPage
from zettcode.tui import MouseAction, MouseEvent
from zettcode.tui.testing import Harness, render_block

#: What a small installation looks like: two the program carries (each with its own setting), a compiled-in one that
#: failed, and four installed beside it — one failed (the switch file can still leave it out) and one held by the
#: configuration file (no switch).
ROWS = (
    PluginRow("skills", "skills", builtin=True, setting="skills.enabled"),
    PluginRow("mcp", "mcp", builtin=True, setting="mcp.enabled"),
    PluginRow(
        "coding",
        "coding",
        builtin=True,
        failure="no plugin provides the model",
        switchable=False,
        why="it could not load, so there is no switch to move",
    ),
    PluginRow("monitor", "zettcode-monitor"),
    PluginRow("acme", "zettcode-acme", enabled=False),
    PluginRow("search", "zettcode-search", failure="missing binary", why=""),
    PluginRow(
        "quiet",
        "zettcode-quiet",
        enabled=False,
        switchable=False,
        why="switched off in the configuration file",
    ),
)

#: The one row of the fixture the configuration file holds: the page draws it, without a switch.
FIXED = "zettcode-quiet"

#: The two rows without a switch, and what each one is: a failed compiled-in plugin, and one the file holds.
NO_SWITCH = ("coding", "quiet")


class Applied:
    """What the page handed over, and whether it was let go of instead."""

    def __init__(self) -> None:
        self.changes: dict[str, bool] | None = None
        self.cancelled = 0

    def apply(self, changes: dict[str, bool]) -> None:
        self.changes = changes

    def cancel(self) -> None:
        self.cancelled += 1


def _page(rows=ROWS) -> tuple[PluginsPage, Applied]:
    applied = Applied()
    page = PluginsPage(rows, on_apply=applied.apply, on_cancel=applied.cancel)
    return page, applied


def _harness(page: PluginsPage, size: tuple[int, int] = (84, 18)) -> Harness:
    harness = Harness(root=page, width=size[0], height=size[1], clock=lambda: 1_000.0)
    harness.render()
    return harness


def _text(page: PluginsPage) -> str:
    return render_block(page, width=84, height=18).split("-- styles --")[0]


def test_the_page_lists_the_programs_own_plugins_apart_from_the_installed_ones():
    page, _ = _page()

    text = _text(page)

    assert f"  {BUILTIN} " in text and f"  {INSTALLED} " in text
    assert text.index(BUILTIN) < text.index("skills") < text.index(INSTALLED) < text.index("monitor")
    assert "skills.enabled" in text, "a switch of the program's own says which setting it writes"
    assert "4 of 5 on" in text, "the count is of the switches the page can move"
    assert "could not load: missing binary" in text, "an installed plugin that failed says why"
    assert "could not load: no plugin provi" in text, "and so does a compiled-in one, as far as the column holds"
    assert OFF_IN_CONFIG in text, "a switch the configuration file owns says so"
    assert "esc cancel" in text


def test_a_failed_plugin_keeps_its_switch_only_when_it_is_installed():
    """The switch file is what leaves an installed plugin out, so its row still has one; a compiled-in one has not."""
    page, _ = _page()
    harness = _harness(page)

    assert page.shown == {
        "skills": True,
        "mcp": True,
        "zettcode-monitor": True,
        "zettcode-acme": False,
        "zettcode-search": True,
    }, "the failed installed plugin is still switchable"

    search = next(index for index, row in enumerate(page.rows) if row.name == "search")
    page.mark = search
    harness.press("left")
    assert page.shown["zettcode-search"] is False, "its switch moves"

    coding = next(index for index, row in enumerate(page.rows) if row.name == "coding")
    page.mark = coding
    assert "could not load: no plugin provides the model" in _text(page), "the whole reason is on the line below"
    harness.press("left")
    assert page.note == "it could not load, so there is no switch to move"


def test_a_plugin_the_program_carries_is_switched_by_its_setting():
    page, applied = _page()
    harness = _harness(page)

    harness.press("left")
    harness.press("enter")

    assert page.note is None, "the switch moves: there is a setting behind it"
    assert applied.changes == {"skills": False}


def test_the_arrows_move_the_marker_and_the_switch_moves_with_left_and_right():
    page, _ = _page()
    harness = _harness(page)

    harness.press("down")
    harness.press("down")
    harness.press("down")
    assert page.rows[page.mark].name == "monitor"

    harness.press("left")
    assert page.shown["zettcode-monitor"] is False
    harness.press("right")
    assert page.shown["zettcode-monitor"] is True
    harness.press(" ")
    assert page.shown["zettcode-monitor"] is False

    text = _text(page)
    assert "(not applied)" in text, "the title says the switches have not been written down"
    assert "monitor: zettcode-monitor is left out of the next start" in text
    # The knob takes a moment to arrive; the word beside it has already changed.
    assert "off" in text


def test_the_marker_rounds_from_the_last_row_to_the_first_and_back():
    page, _ = _page()
    harness = _harness(page)

    harness.press("up")
    assert page.mark == len(ROWS) - 1
    harness.press("down")
    assert page.mark == 0


def test_enter_hands_over_only_what_changed_and_escape_hands_over_nothing():
    page, applied = _page()
    harness = _harness(page)

    harness.press("down")
    harness.press("down")
    harness.press("down")
    harness.press("left")
    harness.press("down")
    harness.press("right")
    harness.press("enter")

    assert applied.changes == {"zettcode-monitor": False, "zettcode-acme": True}

    page, applied = _page()
    _harness(page).press("escape")

    assert applied.cancelled == 1 and applied.changes is None


def test_a_plugin_the_configuration_file_switched_off_cannot_be_switched_on_here():
    page, applied = _page()
    harness = _harness(page)
    for _ in range(len(ROWS) - 1):
        harness.press("down")
    assert page.rows[page.mark].name == "quiet"

    harness.press("right")
    harness.press("enter")

    assert page.note == "switched off in the configuration file", "the catalog's own reason, said again on the row"
    assert applied.changes == {}


def test_a_click_on_a_switch_flips_it_and_a_click_on_the_row_marks_it():
    page, _ = _page()
    _harness(page)
    switch = page._switch_column()

    # The list starts three rows down: line 0 is the "Built in" heading, 1 to 3 its plugins, 4 the other
    # heading, 5 monitor, 6 acme, 7 search, 8 quiet.
    page.handle(MouseEvent(x=switch + 2, y=3 + 5, action=MouseAction.DOWN), None)
    assert page.rows[page.mark].name == "monitor"
    assert page.shown["zettcode-monitor"] is False, "a click on the switch is a press on it"

    page.handle(MouseEvent(x=6, y=3 + 6, action=MouseAction.DOWN), None)
    assert page.rows[page.mark].name == "acme"
    assert page.shown["zettcode-acme"] is False, "a click on the name only moves the marker"

    page.handle(MouseEvent(x=6, y=3 + 6, action=MouseAction.SCROLL_DOWN), None)
    assert page.rows[page.mark].name == "search"


def test_a_list_longer_than_the_screen_scrolls_to_the_marked_row():
    rows = tuple(PluginRow(f"plugin-{index}", f"third-party-{index}") for index in range(30))
    page, _ = _page(rows)
    harness = _harness(page, (84, 14))

    harness.press("end")

    text = _text(page)
    assert page.mark == len(rows) - 1
    assert "third-party-29" in text, "the last row is on screen"
    assert "plugin-0 " not in text, "and the first is not"
    assert "\u25b2" in text, "a mark at the edge says there is more list above"


async def test_the_command_opens_the_page_and_escape_leaves_it_unwritten(tmp_path, monkeypatch):
    """`/plugins` on its own is the page, not a paragraph: Escape closes it and writes nothing."""
    from test_zettcode_app import _harness as app_harness
    from test_zettcode_app import _type_command, build_app, walk

    app = build_app()
    harness = app_harness(app)
    harness.render()

    await _type_command(app, harness, "/plugins")

    page = next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, PluginsPage))
    assert page.rows == (), "the fake shell's bundle carries no plugins, so there is nothing to switch"
    assert app.app.screens.top.name == "page"
    harness.press("escape")
    assert not [entry for entry in app.transcript.entries if entry.kind == "notice"]
