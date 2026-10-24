"""The named parts of the header and the status line: which exist, how a row is laid out, and how a part is hidden."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.events import AgentEvent, AgentEventType

from test_boot import HEIGHT, WIDTH, _cells, _rows
from test_zettcode_app import (
    _harness,
    _type_command,
    build_app,
    walk,
)
from zettcode._compat import tomllib
from zettcode.app.ui import labels
from zettcode.app.ui.boot import boot_tree
from zettcode.app.ui.widgets.statusline_page import (
    CHROME,
    LIST_ROWS,
    PARTS,
    ROW_OF,
    StatuslinePage,
    statusline_rows,
)
from zettcode.config import ZettCodeConfig, load_config
from zettcode.config_edit import ConfigEditError, set_statusline
from zettcode.engine.extensions.usage import USAGE_EVENT_NAME, UsageSnapshot
from zettcode.statusline import NAMES, Row, unknown
from zettcode.tui import TuiApp

MODEL = '[[models]]\nmodel = "m"\ntoken = "t"\n'

#: What the panel's preview names as the workspace, which is a path of its own and not the test's.
SAMPLE_WORKSPACE = next(part.text for part in PARTS if part.name == "workspace")


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    return path


def hidden_in(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("statusline", {})


def _page(app) -> StatuslinePage:
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, StatuslinePage))


async def open_panel(app=None, size: tuple[int, int] | None = None):
    app = app or build_app()
    harness = _harness(app)
    if size:
        harness.resize(*size)
    harness.render()
    await _type_command(app, harness, "/statusline")
    return app, harness


async def _measured(app, **counters):
    """Give the session a measured request, so the token figures and the context share have something to show."""
    snapshot = UsageSnapshot(
        input_tokens=22_000, output_tokens=600, cache_read_tokens=17_000, seconds=6.0, requests=2, context_tokens=64_000
    )
    await app.projector.on_custom_event(
        AgentEvent(
            type=AgentEventType.CUSTOM, session_id="session-0001", name=USAGE_EVENT_NAME, payload=snapshot.to_payload()
        )
    )


def notices(app) -> list[str]:
    return [entry.text for entry in app.transcript.entries if entry.kind == "notice"]


# -- the parts ------------------------------------------------------------------------------------------------


def test_every_part_has_a_distinct_name_and_a_description():
    assert len(set(NAMES)) == len(NAMES)
    assert tuple(part.name for part in PARTS) == NAMES, "the rows add exactly the parts the config may name, in order"
    for part in PARTS:
        assert part.name == part.name.lower() and " " not in part.name
        assert len(part.summary) > 12, f"{part.name} says nothing about what it shows"
    assert ROW_OF["ctx"] == "Status line" and ROW_OF["model"] == "Header"
    assert unknown(["ctx", "nope", "app"]) == ["nope"]


def test_a_part_that_is_a_valid_toml_key_without_quotes():
    for name in NAMES:
        assert tomllib.loads(f"[statusline]\n{name} = false\n") == {"statusline": {name: False}}


def test_the_rows_read_as_they_always_did():
    assert (
        labels.header_left(Path("~/api"), "Fix", "fix").text()
        == f"  \u25c8 zettcode  Fix \u00b7 @fix \u00b7 {Path('~/api')}"
    )
    assert labels.header_right("m", "high").text() == "m \u00b7 high  "
    row = labels.status_left(
        "ready",
        permission="safe",
        self_compact=True,
        tokens="\u219112 \u21931",
        cache="5% cached",
        speed="9 tok/s",
        ctx="ctx 3%",
    )
    assert row.text() == (
        "  \u25cf ready \u00b7 safe \u00b7 self-compact  \u219112 \u21931 \u00b7 5% cached \u00b7 9 tok/s \u00b7 ctx 3%"
    )
    assert labels.status_right().text() == f"  {labels.KEY_HINTS}  "


def test_a_row_is_appended_to_part_by_part():
    row = Row(lead="> ", trail=" <")
    row.add("a", "first", "A").gap().add("b", "second", "B").add("c", "third", "C")
    assert row.text() == "> A  B \u00b7 C <"
    assert [(part.name, part.summary) for part in row.parts()] == [("a", "first"), ("b", "second"), ("c", "third")]


def test_a_hidden_part_and_a_part_with_nothing_to_say_take_no_room():
    row = (
        Row(lead="  ")
        .add("app", "x", "A")
        .gap()
        .add("session", "x", "S")
        .add("handle", "x", "")
        .add("workspace", "x", "W")
    )
    assert row.text() == "  A  S \u00b7 W"
    assert row.text({"workspace"}) == "  A  S"
    assert row.text({"app"}) == "  S \u00b7 W"
    assert row.text({"session", "workspace"}) == "  A"
    assert [part.name for part in row.parts()] == ["app", "session", "handle", "workspace"], (
        "an empty part is still listed"
    )


def test_a_side_with_nothing_left_is_empty_and_not_a_pair_of_spaces():
    assert labels.header_right("m", "e").text({"model", "effort"}) == ""
    assert labels.status_right().text({"keys"}) == ""
    assert Row(lead="  ").text() == ""


def test_a_shown_part_carries_the_glue_in_front_of_it():
    shown = labels.header_right("m", "e").shown()
    assert [(piece.glue, piece.part.name) for piece in shown] == [("", "model"), (" \u00b7 ", "effort")]


# -- the config -----------------------------------------------------------------------------------------------


def test_every_part_but_the_pet_is_shown_until_the_config_says_otherwise(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")
    assert load_config(tmp_path, path=path).statusline_hidden == ("pet",), "the pet is out only when asked for"
    path.write_text(MODEL + "\n[statusline]\npet = true\n", encoding="utf-8")
    assert load_config(tmp_path, path=path).statusline_hidden == ()


def test_the_statusline_table_hides_the_parts_it_sets_to_false(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL + "\n[statusline]\nspeed = false\nctx = false\ncache = true\npet = true\n", encoding="utf-8")
    assert load_config(tmp_path, path=path).statusline_hidden == ("speed", "ctx"), "in the order the rows show them"


def test_a_part_that_does_not_exist_is_a_typo_not_something_to_ignore(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL + "\n[statusline]\ncontext = false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown config keys in the \\[statusline\\] table"):
        load_config(tmp_path, path=path)


def test_a_part_set_to_something_other_than_a_boolean_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL + '\n[statusline]\nctx = "no"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="statusline.ctx"):
        load_config(tmp_path, path=path)


def test_a_configuration_that_hides_a_name_no_part_has_is_refused(tmp_path):
    from zettcode.config import ModelConfig

    with pytest.raises(ValueError, match="names no part"):
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), statusline_hidden=("nope",))


def test_editing_the_table_changes_the_named_parts_and_nothing_else(tmp_path):
    where = tmp_path / "config.toml"
    text = MODEL + '\n[ui]\ntheme = "nord"\n'
    edited = set_statusline(text, {"ctx": False, "speed": False}, where=where)
    assert tomllib.loads(edited) == {**tomllib.loads(text), "statusline": {"ctx": False, "speed": False}}
    shown_again = set_statusline(edited, {"ctx": True}, where=where)
    assert tomllib.loads(shown_again)["statusline"] == {"ctx": True, "speed": False}


def test_a_file_that_spells_the_table_as_an_inline_table_is_refused_not_guessed_at(tmp_path):
    with pytest.raises(ConfigEditError, match="/statusline"):
        set_statusline("statusline = { ctx = true }\n" + MODEL, {"ctx": False}, where=tmp_path / "config.toml")


# -- the rows -------------------------------------------------------------------------------------------------


async def test_a_part_the_config_hides_leaves_the_status_line_and_the_rest_stays(config_file):
    app = build_app()
    app.app.resize(200, 14)  # wide enough that no part is spared for room
    await _measured(app)
    assert "ctx 50.0%" in app._status_left().text and "tok/s" in app._status_left().text

    app.agent.runtime.config = type(app.agent.runtime.config)(
        **{
            **app.agent.runtime.config.__dict__,
            "statusline_hidden": ("ctx", "speed"),
        }
    )
    status = app._status_left().text

    assert "ctx" not in status and "tok/s" not in status
    assert "\u219122.0k \u2193600 \u00b7 77.3% cached" in status
    assert status.startswith("  \u25cf ")


async def test_a_narrow_status_line_spares_the_counters_before_it_loses_the_context_share(config_file):
    app = build_app()  # 60 columns, with the keys on the right winning what they need
    await _measured(app)

    narrow = app._status_left().text
    assert "ctx 50.0%" in narrow and "tok/s" not in narrow, "the speed goes first"
    assert narrow.rstrip().endswith("ctx 50.0%"), "and the share is not the end that is cut"

    app.app.resize(36, 14)
    tight = app._status_left().text
    assert "ctx 50.0%" in tight and "cached" not in tight and "\u2191" not in tight

    app.app.resize(200, 14)
    wide = app._status_left().text
    assert all(part in wide for part in ("\u219122.0k", "77.3% cached", "100 tok/s", "ctx 50.0%"))


async def test_hiding_the_tokens_leaves_the_cache_share_joined_to_nothing_dangling(config_file):
    app = build_app()
    app.app.resize(200, 14)
    await _measured(app)
    app.agent.runtime.config = type(app.agent.runtime.config)(
        **{
            **app.agent.runtime.config.__dict__,
            "statusline_hidden": ("tokens",),
        }
    )
    status = app._status_left().text
    assert "\u2191" not in status
    assert "77.3% cached \u00b7 100 tok/s \u00b7 ctx 50.0%" in status
    assert "\u00b7  " not in status and not status.rstrip().endswith("\u00b7")


def test_the_header_loses_the_parts_it_is_told_to(config_file):
    app = build_app()
    base = app._header_left().text
    workspace = str(app.agent.workspace)
    assert "New session" in base and workspace[-12:] in base
    app.agent.runtime.config = type(app.agent.runtime.config)(
        **{
            **app.agent.runtime.config.__dict__,
            "statusline_hidden": ("workspace", "session"),
        }
    )
    left = app._header_left().text
    assert left.strip() == "\u25c8 zettcode"
    assert app._header_right().text.strip().endswith("medium")


def test_hiding_the_model_leaves_the_effort_and_hiding_both_leaves_an_empty_side(config_file):
    app = build_app()
    config = app.agent.runtime.config
    app.agent.runtime.config = type(config)(**{**config.__dict__, "statusline_hidden": ("model",)})
    assert app._header_right().text == "medium  "
    app.agent.runtime.config = type(config)(**{**config.__dict__, "statusline_hidden": ("model", "effort")})
    assert app._header_right().text == ""
    app.agent.runtime.config = type(config)(**{**config.__dict__, "statusline_hidden": ("keys",)})
    assert app._status_right().text == ""


# -- the frame painted before the application exists -----------------------------------------------------------


def test_the_hidden_parts_are_read_from_the_file_alone(tmp_path):
    path = tmp_path / "config.toml"
    assert labels.hidden_parts(path) == (), "a missing file hides nothing"
    path.write_text(MODEL + "\n[statusline]\nkeys = false\nworkspace = false\nctx = true\nbogus = false\n", "utf-8")
    assert labels.hidden_parts(path) == ("workspace", "keys")
    path.write_text("not [ toml", "utf-8")
    assert labels.hidden_parts(path) == ()
    path.write_text("statusline = 3\n", "utf-8")
    assert labels.hidden_parts(path) == ()


def test_the_boot_frame_draws_the_rows_with_the_parts_the_reader_hid(tmp_path):
    hidden = ("workspace", "keys")
    rows = _rows(TuiApp(boot_tree(tmp_path.resolve(), model="m", hidden=hidden), width=WIDTH, height=HEIGHT))
    assert str(tmp_path.resolve())[-8:] not in rows[0]
    assert "New session" in rows[0]
    assert "exit" not in rows[-1] and "ready" in rows[-1]


def test_every_cell_the_boot_frame_draws_survives_the_swap_with_parts_hidden(tmp_path, monkeypatch):

    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nenabled = false\n[mcp]\nenabled = false\n'
        "[statusline]\nworkspace = false\nmode = false\nkeys = false\n",
        encoding="utf-8",
    )
    shell = _shell_with(tmp_path, monkeypatch, path)
    early = _cells(
        TuiApp(boot_tree(tmp_path.resolve(), model="m", hidden=labels.hidden_parts(path)), width=WIDTH, height=HEIGHT)
    )
    settled = _cells(shell)
    for index, row in enumerate(early):
        for column, cell in enumerate(row):
            if cell.character.strip():
                assert cell == settled[index][column], f"cell {column},{index} does not survive the swap"


def _shell_with(tmp_path, monkeypatch, path):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    from zettcode.app.agent.agent import ZettCodeAgent
    from zettcode.app.ui import ZettCodeApp
    from zettcode.cli import resolve_config

    app = ZettCodeApp(ZettCodeAgent.preview(resolve_config(["-w", str(tmp_path)])), auto_theme=False)
    return app.app


# -- the panel ------------------------------------------------------------------------------------------------


async def test_the_panel_lists_every_part_with_its_description_and_a_switch_each(config_file):
    app, harness = await open_panel(size=(120, 40))
    text = harness.render().text

    assert app.app.screens.top.name == "page"
    assert app.composer.text == "", "no menu: the panel is the choice"
    for part in PARTS:
        assert part.name in text, part.name
        assert part.summary[:30] in text, part.name
    assert text.count("\u2501" * 9 + "\u25cf shown") == len(PARTS), "a lit line to the knob on every switch"
    assert f"{len(PARTS)} of {len(PARTS)} shown" in text
    assert "Header" in text and "Status line" in text
    assert "esc cancel" in text


async def test_the_panel_starts_where_the_config_is(config_file):
    app = build_app()
    app.agent.runtime.config = type(app.agent.runtime.config)(
        **{
            **app.agent.runtime.config.__dict__,
            "statusline_hidden": ("ctx",),
        }
    )
    app, harness = await open_panel(app)
    page = _page(app)
    assert page.shown["ctx"] is False and sum(page.shown.values()) == len(PARTS) - 1
    assert not page.changed


async def test_up_and_down_choose_a_part_and_left_and_right_hide_and_show_it(config_file):
    app, harness = await open_panel()
    page = _page(app)
    assert PARTS[page.mark].name == "app"

    harness.press("down")
    harness.press("down")
    assert PARTS[page.mark].name == "handle"
    harness.press("left")
    assert page.shown["handle"] is False and page.shown["session"] is True
    harness.press("left")
    assert page.shown["handle"] is False, "hiding what is hidden changes nothing"
    harness.press("right")
    assert page.shown["handle"] is True
    harness.press("up")
    harness.press("up")
    assert PARTS[page.mark].name == "app", "up from the third goes to the first"
    harness.press("up")
    assert PARTS[page.mark].name == PARTS[-1].name, "and up from the first goes round to the last"
    harness.press("down")
    assert PARTS[page.mark].name == "app", "and down from the last, to the first"
    for _ in range(len(PARTS)):
        harness.press("down")
    assert PARTS[page.mark].name == "app", "a whole turn of the list comes back to where it began"


async def test_space_flips_the_part_the_marker_is_on(config_file):
    app, harness = await open_panel()
    page = _page(app)
    harness.press("down")
    harness.write(" ")
    assert page.shown["session"] is False
    harness.write(" ")
    assert page.shown["session"] is True


async def test_moving_a_switch_changes_nothing_until_enter(config_file):
    app, harness = await open_panel()
    harness.press("left")

    assert "(not applied)" in harness.render().text
    assert app.agent.statusline_hidden == frozenset()
    assert hidden_in(config_file) == {}
    assert not notices(app)


async def test_the_preview_follows_the_switches_before_anything_is_applied(config_file):
    app, harness = await open_panel(size=(120, 40))
    assert SAMPLE_WORKSPACE in harness.render().text
    for _ in range(3):
        harness.press("down")
    harness.press("left")  # workspace
    text = harness.render().text
    assert SAMPLE_WORKSPACE not in text
    assert "Fix the parser" in text
    assert SAMPLE_WORKSPACE not in app._header_left().text, "and the real row is untouched"


async def test_enter_writes_the_hidden_parts_and_the_rows_follow(config_file):
    app, harness = await open_panel()
    harness.press("down")
    harness.press("left")  # session
    for _ in range(11):
        harness.press("down")
    harness.press("left")  # ctx

    harness.press("enter")

    assert hidden_in(config_file) == {"session": False, "ctx": False}
    assert app.agent.statusline_hidden == {"session", "ctx"}
    assert app.app.screens.top.name != "page"
    assert notices(app) == [f"Status line: 2 of {len(NAMES)} parts hidden (session, ctx)"]
    assert "New session" not in app._header_left().text


async def test_showing_a_part_again_writes_true_and_says_everything_is_shown(config_file):
    config_file.write_text(MODEL + "\n[statusline]\nctx = false\n", encoding="utf-8")
    app = build_app()
    app.agent.runtime.config = type(app.agent.runtime.config)(
        **{
            **app.agent.runtime.config.__dict__,
            "statusline_hidden": ("ctx",),
        }
    )
    app, harness = await open_panel(app)
    for _ in range(12):
        harness.press("down")
    harness.press("right")
    harness.press("enter")

    assert hidden_in(config_file) == {"ctx": True}
    assert notices(app) == ["Status line: every part is shown"]
    assert app.agent.statusline_hidden == frozenset()


async def test_enter_with_nothing_moved_writes_nothing(config_file):
    app, harness = await open_panel()
    before = config_file.read_text(encoding="utf-8")
    harness.press("enter")
    assert config_file.read_text(encoding="utf-8") == before


async def test_escape_applies_nothing(config_file):
    app, harness = await open_panel()
    harness.press("left")
    harness.press("escape")

    assert app.app.screens.top.name != "page"
    assert hidden_in(config_file) == {}
    assert app.agent.statusline_hidden == frozenset()
    assert not notices(app)


async def test_a_config_that_cannot_be_written_is_reported_and_the_rows_stay(config_file):
    app, harness = await open_panel()
    harness.press("left")
    config_file.unlink()

    harness.press("enter")

    assert app.agent.statusline_hidden == frozenset()
    errors = [entry.text for entry in app.transcript.entries if getattr(entry, "level", None) == "error"]
    assert errors, "the failure is said, not swallowed"


async def test_the_switch_is_a_short_rail_with_a_round_knob_that_slides_instead_of_jumping(config_file):
    """A five-column rail gives the knob four places; the ten-column one must show it in most of its nine."""
    from zettcode.app.ui.widgets.statusline_page import SWITCH_WIDTH

    class Clock:
        now = 1_000.0

        def __call__(self):
            return self.now

    clock = Clock()
    app, harness = await open_panel(None)
    app.app.clock = clock
    page = _page(app)
    harness.render()
    harness.press("left")  # the first part is shown, so this slides it to hidden
    row = page.rect.y + 7
    start = page._switch_column()
    knobs = []
    for step in range(0, 29):
        clock.now = 1_000.0 + step * 0.01  # a hundred frames a second across the 0.28 s slide
        harness.render()
        cells = app.app.render().cells[row][start : start + SWITCH_WIDTH]
        text = "".join(cell.character for cell in cells)
        assert text.count("\u25cf") == 1, text
        knobs.append(text.index("\u25cf"))
    assert knobs == sorted(knobs, reverse=True), "it moves one way and never back"
    assert len(set(knobs)) == SWITCH_WIDTH, f"the knob skipped columns: {sorted(set(knobs))}"
    assert knobs[0] == SWITCH_WIDTH - 1 and knobs[-1] == 0


async def test_the_switch_is_a_thin_line_with_a_round_knob_and_not_a_bar(config_file):
    from zettcode.app.ui.widgets.statusline_page import SWITCH_WIDTH
    from zettcode.tui import Canvas

    app, harness = await open_panel(None)
    page = _page(app)
    harness.render()
    rows = []
    for position in (0.0, 0.5, 1.0):
        canvas = Canvas(40, 1)
        page._draw_switch(canvas, 0, 2, position, "#000000")
        rows.append("".join(cell.character for cell in canvas.cells[0][2 : 2 + SWITCH_WIDTH]))
    assert rows[0] == "\u25cf" + "\u2500" * (SWITCH_WIDTH - 1), "hidden: the knob at the start of an empty groove"
    assert rows[2] == "\u2501" * (SWITCH_WIDTH - 1) + "\u25cf", "shown: lit all the way to the knob"
    assert "\u2501" in rows[1] and "\u2500" in rows[1] and rows[1].count("\u25cf") == 1
    assert not any(character in "\u2588\u258c" for row in rows for character in row)


async def test_the_switch_travels_with_the_clock_and_lands(config_file):
    class Clock:
        now = 1_000.0

        def __call__(self):
            return self.now

    clock = Clock()
    app, harness = await open_panel(None)
    app.app.clock = clock
    page = _page(app)
    harness.press("left")
    rail = page.switches["app"]
    assert rail.moving and 0.0 < rail.position(clock.now + 0.1) < 1.0
    clock.now += 1.0
    page.on_tick()
    assert not rail.moving and rail.position(clock.now) == 0.0


async def test_the_list_scrolls_to_keep_the_marked_part_and_its_heading_in_view(config_file):
    app, harness = await open_panel()
    page = _page(app)
    view = page._view()
    assert view < LIST_ROWS, "the test screen is shorter than the list"
    text = harness.render().text
    assert "\u25bc" in text and "\u25b2" not in text
    for _ in range(len(PARTS) - 1):
        harness.press("down")
    text = harness.render().text
    assert "keys" in text and "\u25b2" in text and "\u25bc" not in text
    for _ in range(len(PARTS) - 1):
        harness.press("up")
    assert "app" in harness.render().text.split("Header")[1].split("\n")[1]


async def test_a_click_marks_a_part_and_a_click_on_its_switch_flips_it(config_file):
    from zettcode.tui import MouseAction, MouseEvent

    app, harness = await open_panel(size=(120, 40))
    harness.render()
    page = _page(app)
    first = page.rect.y + 6 + 2  # the second part, below the heading
    harness.dispatch(MouseEvent(x=page.rect.x + 6, y=first, action=MouseAction.DOWN))
    assert PARTS[page.mark].name == "session" and page.shown["session"] is True
    harness.dispatch(MouseEvent(x=page._switch_column() + 1, y=first, action=MouseAction.DOWN))
    assert page.shown["session"] is False
    heading = MouseEvent(x=page.rect.x + 6, y=page.rect.y + 6, action=MouseAction.DOWN)
    assert not harness.dispatch(heading) or PARTS[page.mark].name == "session"


@pytest.mark.parametrize("width", [20, 32, 44, 60, 80, 120])
async def test_no_row_of_the_panel_runs_past_the_screen(config_file, width):
    app, harness = await open_panel()
    harness.resize(width, 30)
    for line in harness.render().text.split("\n"):
        assert len(line) <= width


def test_the_panel_takes_the_whole_list_when_there_is_room_and_what_it_can_spare_when_not():
    assert statusline_rows(100) == CHROME + LIST_ROWS
    assert statusline_rows(24) == 24 - 8
    assert statusline_rows(5) == CHROME + 4, "never so few that the list is gone"


# -- typed ------------------------------------------------------------------------------------------------------


async def test_typed_hide_and_show_write_the_same_table_the_panel_does(config_file):
    app = build_app()
    harness = _harness(app)
    harness.render()

    await _type_command(app, harness, "/statusline hide ctx speed")
    assert hidden_in(config_file) == {"ctx": False, "speed": False}
    assert app.agent.statusline_hidden == {"ctx", "speed"}

    await _type_command(app, harness, "/statusline show speed")
    assert hidden_in(config_file) == {"ctx": False, "speed": True}

    await _type_command(app, harness, "/statusline show all")
    assert app.agent.statusline_hidden == frozenset()
    assert set(hidden_in(config_file).values()) == {True}


async def test_typed_words_that_are_not_parts_change_nothing_and_say_what_is_accepted(config_file):
    app = build_app()
    harness = _harness(app)
    harness.render()
    await _type_command(app, harness, "/statusline hide ctx nonsense")

    assert hidden_in(config_file) == {}
    said = " ".join(entry.text for entry in app.transcript.entries if hasattr(entry, "text"))
    assert "No such part: nonsense" in said and "workspace" in said

    await _type_command(app, harness, "/statusline sideways")
    said = " ".join(entry.text for entry in app.transcript.entries if hasattr(entry, "text"))
    assert "Usage: /statusline" in said


def test_the_command_is_listed_and_has_no_word_menu_to_make_it_look_unchanged(config_file):
    app = build_app()
    command = next(command for command in app.commands if command.name == "/statusline")
    assert not command.subcommands
