"""The pets: what one is, the ones that ship, how plugins offer more, and the `/pet` panel that chooses between them."""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path

import pytest

from test_pet import CAT, Clock, painted, shows, stands
from test_plugins import FakeEntryPoint, make_config
from test_statusline import config_file, hidden_in  # noqa: F401 - the fixture is used by name
from test_zettcode_app import FakeConfig, _harness, _type_command, build_app, rows_and_commands, walk
from zettcode.app.pets import (
    BUNDLED,
    DEFAULT_PET_NAME,
    GLAD,
    IDLE,
    WORKING,
    Pet,
    PetCatalog,
    PetSource,
    bundled_pets,
    edited,
    mirrored,
)
from zettcode.app.ui.widgets.pet_page import (
    BOX_HEIGHT,
    BOX_WIDTH,
    MIN_WIDTH_FOR_BOX,
    SEQUENCE,
    SPRITE_ROWS,
    STEP_SECONDS,
    PetPage,
)
from zettcode.config import load_config
from zettcode.config_edit import ConfigEditError, set_pet
from zettcode.plugins import Plugin, PluginContainer, load_plugins
from zettcode.tui import DARK, LIGHT

CATALOG = PetCatalog(bundled_pets())


# -- what a pet is ----------------------------------------------------------------------------------------------


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


def test_a_frame_drawn_as_its_left_half_is_completed_by_its_reflection():
    assert mirrored(("AB.", ".CD")) == ("AB..BA", ".CDDC.")
    full = ("AB..BA", ".CDDC.")
    assert edited(full, {1: "......"}) == ("AB..BA", "......")
    with pytest.raises(ValueError):
        edited(full, {0: "AB"})
    with pytest.raises(ValueError):
        edited(full, {5: "......"})


def test_the_colours_that_stand_for_a_pet_are_the_ones_it_is_mostly_made_of_and_never_its_outline():
    pet = Pet("p", {"A": "#80c080", "B": "#c08040", "D": "#101010"}, {IDLE: (("AAAB", "AADD", "AAAB", "AADD"),)})
    assert pet.swatch(3) == ("#80c080", "#c08040"), "the near-black says nothing about the pet"
    assert pet.swatch(1) == ("#80c080",)


# -- the ones that ship -----------------------------------------------------------------------------------------


def test_the_pets_that_ship_are_listed_in_order_and_the_default_is_the_cat():
    assert (
        CATALOG.names()
        == BUNDLED
        == (
            "cat",
            "dog",
            "tiger",
            "polarbear",
            "snowbear",
            "penguin",
            "scarfy",
            "kangaroo",
            "seagull",
            "whale",
            "chibi",
            "slime",
            "sprout",
        )
    )
    assert DEFAULT_PET_NAME == "cat"
    assert len(set(BUNDLED)) == len(BUNDLED)


@pytest.mark.parametrize("name", BUNDLED)
def test_a_pet_that_ships_fits_the_stage_and_has_a_sleep_a_work_and_a_pat_and_a_note(name: str):
    pet = CATALOG.load(name)

    assert pet.name == name
    assert pet.width <= BOX_WIDTH and pet.height <= SPRITE_ROWS, "the stage in /pet has room for it"
    assert pet.frames(IDLE) == 1, "asleep is a still picture: it costs no timer while nothing runs"
    assert pet.frames(WORKING) > 1 and pet.frames(GLAD) > 1
    for pose in (IDLE, WORKING, GLAD):
        assert pet.lines(pose, 0) != pet.lines(pose, 1) or pet.frames(pose) == 1
    assert pet.lines(IDLE) != pet.lines(WORKING, 0), "it can be told asleep from awake"
    assert CATALOG.notes()[name], f"{name} has no note for the menu"
    assert 2 <= len(pet.swatch(3)) <= 3, "a chip needs at least two colours to be one"


@pytest.mark.parametrize("name", BUNDLED)
def test_the_cells_of_every_frame_hold_exactly_its_pixels(name: str):
    """Half blocks must give back the drawing: no pixel lost, moved, or recoloured by the encoding."""
    pet = CATALOG.load(name)
    names = {colour: char for char, colour in pet.palette.items()}
    assert len(names) == len(pet.palette), "two pixel names share a colour, so the cells could not tell them apart"
    for pose, frames in pet.poses.items():
        for step, pixels in enumerate(frames):
            upper_rows, lower_rows = [], []
            for line in pet.lines(pose, step):
                upper, lower = "", ""
                for span in line.spans:
                    fg, bg = span.style.foreground, span.style.background
                    for character in span.text:
                        top, bottom = {" ": (None, None), "\u2588": (fg, fg), "\u2584": (None, fg), "\u2580": (fg, bg)}[
                            character
                        ]
                        upper += names.get(top, ".")
                        lower += names.get(bottom, ".")
                upper_rows.append(upper)
                lower_rows.append(lower)
            decoded = tuple(row for pair in zip(upper_rows, lower_rows, strict=True) for row in pair)
            assert decoded == pixels, f"{name} {pose} {step}"


@pytest.mark.parametrize("name", BUNDLED)
def test_every_pixel_a_pet_draws_has_a_colour_in_its_palette(name: str):
    pet = CATALOG.load(name)
    used = {char for frames in pet.poses.values() for frame in frames for row in frame for char in row} - {"."}
    assert used <= set(pet.palette), f"{name} uses {sorted(used - set(pet.palette))}"


def test_every_module_beside_the_others_is_listed_and_every_listed_name_has_a_module():
    folder = Path(importlib.import_module("zettcode.app.pets").__file__).parent
    modules = {path.stem for path in folder.glob("*.py")} - {"__init__", "model", "palette"}
    assert modules == set(BUNDLED)


# -- the catalog ------------------------------------------------------------------------------------------------


def test_a_name_nobody_offers_is_answered_with_the_list():
    with pytest.raises(ValueError, match="Unknown pet: 'nope'. Available: cat, dog"):
        CATALOG.load("nope")


def test_a_source_whose_name_is_taken_or_is_not_one_word_is_left_out_and_the_first_wins():
    first = PetSource("a", lambda: CAT)
    other = PetSource("a", lambda: CATALOG.load("dog"))
    spaced = PetSource("two words", lambda: CAT)
    catalog = PetCatalog([first, other, spaced])

    assert catalog.names() == ("a",)
    assert catalog.load("a") is CAT


def test_a_pet_that_cannot_be_built_is_reported_by_name_when_picked_and_has_no_note():
    def broken() -> Pet:
        raise RuntimeError("no paint today")

    def undescribed() -> str:
        raise RuntimeError("nor words")

    catalog = PetCatalog([PetSource("oops", broken, undescribed), PetSource("fine", lambda: CAT, "ok")])

    with pytest.raises(ValueError, match="Pet 'oops' could not be built: no paint today"):
        catalog.load("oops")
    assert catalog.notes() == {"fine": "ok"}


def test_listing_the_pets_builds_none_of_them():
    built: list[str] = []

    def source(name: str) -> PetSource:
        return PetSource(name, lambda: built.append(name) or CAT, lambda: f"{name} note")

    catalog = PetCatalog([source("a"), source("b")])
    catalog.names()

    assert built == []
    catalog.load("b")
    assert built == ["b"]


# -- plugins ----------------------------------------------------------------------------------------------------


class Dragon(Plugin):
    name = "dragon-pack"

    def __init__(self) -> None:
        self.built = 0

    def activate(self, container: PluginContainer) -> None:
        container.register_pet("dragon", CATALOG.load("tiger"), description="breathes quietly")
        container.register_pet("lazy-dragon", self.build, description=lambda: "built late")

    def build(self) -> Pet:
        self.built += 1
        return CATALOG.load("dog")


def test_the_built_in_plugin_offers_the_pets_that_ship_first_through_the_same_call_a_plugin_uses(tmp_path: Path):
    plugins = load_plugins(make_config(tmp_path))

    assert [source.name for source in plugins.pets] == list(BUNDLED)
    assert "pets" in [plugin.name for plugin in plugins.plugins]


def test_a_plugin_offers_pets_by_name_after_the_ones_that_ship(tmp_path: Path):
    plugin = Dragon()
    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("d", lambda: plugin)])

    names = [source.name for source in plugins.pets]
    assert names == [*BUNDLED, "dragon", "lazy-dragon"]
    assert plugin.built == 0, "offering a pet builds nothing"
    found = PetCatalog(plugins.pets)
    assert found.load("dragon").name == "tiger" and found.notes()["dragon"] == "breathes quietly"
    assert found.load("lazy-dragon").name == "dog" and plugin.built == 1
    assert found.notes()["lazy-dragon"] == "built late"


def test_a_plugin_cannot_take_a_name_an_earlier_plugin_has(tmp_path: Path):
    class Greedy(Plugin):
        name = "greedy"

        def activate(self, container: PluginContainer) -> None:
            container.register_pet("cat", CAT)

    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("g", Greedy)])

    assert any("g: pet cat is already registered" in failure for failure in plugins.failures)
    assert [source.name for source in plugins.pets] == list(BUNDLED)


@pytest.mark.parametrize("name", ["", "two words", "a/b", " "])
def test_a_name_that_could_not_be_typed_after_pet_is_refused_when_registered(tmp_path: Path, name: str):
    container = PluginContainer(make_config(tmp_path))
    with pytest.raises(ValueError):
        container.register_pet(name, CAT)


def test_a_pet_registered_twice_by_one_plugin_or_not_a_pet_at_all_is_refused(tmp_path: Path):
    container = PluginContainer(make_config(tmp_path))
    container.register_pet("once", CAT)
    with pytest.raises(ValueError, match="already registered"):
        container.register_pet("once", CAT)
    with pytest.raises(ValueError, match="must be a zettcode.app.pets.Pet"):
        container.register_pet("twice", "a string")  # type: ignore[arg-type]


# -- the configuration ------------------------------------------------------------------------------------------


def config_in(tmp_path: Path, text: str):
    path = tmp_path / "config.toml"
    path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n{text}', encoding="utf-8")
    return load_config(tmp_path, path=path)


def test_the_config_names_the_pet_to_start_with(tmp_path: Path):
    assert config_in(tmp_path, "").pet is None
    assert config_in(tmp_path, '[ui]\npet = "whale"\n').pet == "whale"
    with pytest.raises(ValueError, match="ui.pet"):
        config_in(tmp_path, '[ui]\npet = "two words"\n')
    with pytest.raises(ValueError, match="ui.pet"):
        config_in(tmp_path, "[ui]\npet = 3\n")


def test_choosing_a_pet_changes_one_line_of_the_file_and_nothing_else(tmp_path: Path):
    where = tmp_path / "config.toml"
    original = '[[models]]\nmodel = "m"\ntoken = "t"\n\n[ui]\ntheme = "nord"  # mine\n'

    edited_text = set_pet(original, "dog", where=where)

    assert edited_text == original.replace("[ui]\n", '[ui]\npet = "dog"\n')
    assert set_pet(edited_text, "whale", where=where).count("pet =") == 1
    with pytest.raises(ConfigEditError):
        set_pet("ui = {}\n", "dog", where=where)


# -- in the shell -----------------------------------------------------------------------------------------------


def shell(*extra: PetSource, width: int = 120, height: int = 40):
    plugins = rows_and_commands()
    plugins = dataclasses.replace(plugins, pets=(*plugins.pets, *extra))
    app = build_app(plugins=plugins)
    harness = _harness(app)
    clock = Clock()
    app.app.clock = clock
    harness.resize(width, height)
    harness.render()
    return app, harness, clock


def page_of(app) -> PetPage:
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, PetPage))


def notices_of(app) -> list[str]:
    return [entry.text for entry in app.transcript.entries if entry.kind == "notice"]


def errors_of(app) -> list[str]:
    return [entry.text for entry in app.transcript.entries if getattr(entry, "level", None) == "error"]


def test_the_shell_starts_with_the_cat_and_with_the_pet_the_config_names():
    assert build_app().pet.pet.name == "cat"
    app = build_app()
    app.agent.runtime.config = FakeConfig(pet="whale")
    assert type(app)(app.agent).pet.pet.name == "whale"


def test_a_pet_that_nobody_offers_is_said_in_the_conversation_and_the_cat_stands_in():
    app = build_app()
    app.agent.runtime.config = FakeConfig(pet="unicorn")
    other = type(app)(app.agent)

    assert other.pet.pet.name == "cat"
    assert any("Unknown pet: 'unicorn'" in entry.text for entry in other.transcript.entries)


async def test_the_pet_command_names_the_pet_straight_away_and_remembers_it(config_file):  # noqa: F811
    app, harness, _ = shell()

    await _type_command(app, harness, "/pet whale")

    assert app.pet.pet.name == "whale"
    assert hidden_in(config_file) == {}
    assert 'pet = "whale"' in config_file.read_text(encoding="utf-8")
    assert app.agent.runtime.config.pet == "whale"
    assert shows(app, stands(app, harness), IDLE, pet=CATALOG.load("whale"))


async def test_an_unknown_name_is_reported_with_the_list_and_changes_nothing(config_file):  # noqa: F811
    app, harness, _ = shell()
    before = config_file.read_text(encoding="utf-8")

    await _type_command(app, harness, "/pet nope")

    assert app.pet.pet.name == "cat" and config_file.read_text(encoding="utf-8") == before
    assert any("Unknown pet: 'nope'" in entry.text for entry in app.transcript.entries)


async def test_a_pet_a_plugin_offered_can_be_picked_by_name(config_file):  # noqa: F811
    plugins = load_plugins(make_config(config_file.parent), entry_points=[FakeEntryPoint("d", Dragon)])
    app, harness, _ = shell(*plugins.pets[len(BUNDLED) :])

    await _type_command(app, harness, "/pet dragon")

    assert app.pet.pet.name == "tiger"


async def test_a_file_that_cannot_take_the_line_does_not_undo_the_switch(config_file):  # noqa: F811
    config_file.write_text("ui = {}\n" + config_file.read_text(encoding="utf-8"), encoding="utf-8")
    app, harness, _ = shell()

    await _type_command(app, harness, "/pet dog")

    assert app.pet.pet.name == "dog", "the pet is there"
    assert any("will not be remembered" in text for text in errors_of(app))


async def test_a_pet_that_is_switched_off_is_still_chosen_and_the_reader_is_told_why_nothing_shows(config_file):  # noqa: F811
    app, harness, _ = shell()
    app.agent.runtime.config = dataclasses.replace(app.agent.runtime.config, statusline_hidden=("pet",))

    await _type_command(app, harness, "/pet dog")

    assert app.pet.pet.name == "dog"
    assert "the pet is hidden: /statusline show pet" in harness.render().text


# -- the panel --------------------------------------------------------------------------------------------------


async def open_panel(**kwargs):
    app, harness, clock = shell(**kwargs)
    await _type_command(app, harness, "/pet")
    harness.render()
    return app, harness, clock


async def test_the_panel_lists_every_pet_with_its_note_and_marks_the_one_that_is_out(config_file):  # noqa: F811
    app, harness, _ = await open_panel()

    text = harness.render().text
    for name in BUNDLED:
        assert name in text
    for note in CATALOG.notes().values():
        assert note[:30] in text
    assert "13 pets" in text and "\u25b8" in text
    page = page_of(app)
    assert page.marked == "cat" and page.current == "cat"
    assert "cat \u25cf" in text, "the dot says which one is out now"


async def test_moving_the_mark_puts_that_pet_over_the_conversation_at_once(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    page = page_of(app)

    harness.press("down")
    assert page.marked == "dog" and app.pet.pet.name == "dog"
    harness.press("end")
    assert page.marked == "sprout" and app.pet.pet.name == "sprout"
    harness.press("home")
    assert app.pet.pet.name == "cat"
    assert hidden_in(config_file) == {} and "pet =" not in config_file.read_text(encoding="utf-8"), "only a preview"


async def test_up_from_the_first_pet_goes_round_to_the_last_and_down_from_the_last_to_the_first(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    page = page_of(app)
    assert page.marked == BUNDLED[0]

    harness.press("up")
    assert page.marked == BUNDLED[-1] and app.pet.pet.name == BUNDLED[-1]
    harness.press("down")
    assert page.marked == BUNDLED[0] and app.pet.pet.name == BUNDLED[0]


async def test_escape_puts_the_old_pet_back_and_writes_nothing(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    before = config_file.read_text(encoding="utf-8")
    harness.press("down")
    harness.press("down")
    assert app.pet.pet.name == "tiger"

    harness.press("escape")

    assert app.pet.pet.name == "cat" and app.app.screens.top.name != "page"
    assert config_file.read_text(encoding="utf-8") == before
    assert app._pet_before is None


async def test_enter_chooses_the_marked_pet_remembers_it_and_says_so(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    for _ in range(BUNDLED.index("whale")):
        harness.press("down")

    harness.press("enter")

    assert app.pet.pet.name == "whale" and app.app.screens.top.name != "page"
    assert 'pet = "whale"' in config_file.read_text(encoding="utf-8")
    assert notices_of(app) == ["pet whale \u2014 remembered for next time"]
    assert app._pet_before is None, "what is chosen is not a preview to be put back"


async def test_the_panel_works_with_the_wheel_and_a_click_chooses_the_pet_already_marked(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    page = page_of(app)
    top = page.rect.y + 3

    harness.scroll(page.rect.x + 10, top, up=False)
    assert page.marked == "dog"
    row = BUNDLED.index("whale")
    harness.click(page.rect.x + 10, top + row)  # a row that is not the marked one: it only marks
    assert page.marked == "whale" and app.app.screens.top.name == "page"
    harness.click(page.rect.x + 10, top + row)  # the same row again chooses it
    assert app.pet.pet.name == "whale"


async def test_the_stage_shows_the_marked_pet_going_through_its_moods_by_the_clock(config_file):  # noqa: F811
    app, harness, clock = await open_panel()
    page = page_of(app)
    seen = []
    for step in range(len(SEQUENCE)):
        clock.now = page._began + step * STEP_SECONDS + 0.01
        harness.render()
        seen.append(page._drawn)
    assert seen == list(range(len(SEQUENCE)))
    assert page._token in app.app.scheduler.animations

    assert page.on_tick() is False, "a tick inside the step it is on draws nothing new"
    clock.now += STEP_SECONDS
    assert page.on_tick() is True

    harness.press("escape")
    assert page._token not in app.app.scheduler.animations, "put away, it costs no frames"


async def test_with_reduced_motion_the_stage_holds_still_at_work(config_file):  # noqa: F811
    app, harness, clock = shell()
    app.app.reduced_motion = True
    await _type_command(app, harness, "/pet")
    page = page_of(app)

    clock.now += 100
    harness.render()

    assert page._drawn == 2 and SEQUENCE[2][0] == WORKING
    assert page._token not in app.app.scheduler.animations


async def test_each_pet_has_its_own_chip_and_its_own_tint_on_the_stage(config_file):  # noqa: F811
    app, harness, _ = await open_panel()
    page = page_of(app)
    canvas = app.app.render()

    def stage_background() -> str:
        x = page.rect.right - 2 - 1
        return canvas.cells[page.rect.y + 3 + 1][x].style.background

    cat_stage = stage_background()
    chips = {
        name: [canvas.cells[page.rect.y + 3 + index][page.rect.x + 4 + slot].style.foreground for slot in range(3)]
        for index, name in enumerate(BUNDLED)
    }
    assert chips["cat"] == list(CATALOG.load("cat").swatch(3)), "the marked row's chip is the pet's own colours"
    assert chips["cat"] != chips["dog"] != chips["tiger"]
    harness.press("down")
    harness.press("down")
    canvas = app.app.render()
    assert stage_background() != cat_stage, "the stage takes the marked pet's colour"


async def test_the_mood_is_told_in_a_colour_of_the_palette_and_follows_both_palettes(config_file):  # noqa: F811
    for theme in (DARK, LIGHT):
        app, harness, clock = await open_panel()
        app.app.theme = theme
        page = page_of(app)
        clock.now = page._began + 2 * STEP_SECONDS + 0.01  # at work
        harness.render()
        canvas = app.app.render()
        rows = canvas.cells[page.rect.y : page.rect.bottom]
        lit = [
            cell.style.foreground
            for row in rows
            for cell in row
            if cell.character == "\u25cf" and cell.style.foreground == theme.accent and cell.style.bold
        ]
        assert lit, f"{theme.name}: the lit dot at work carries the accent"
        clock.now = page._began + 6 * STEP_SECONDS + 0.01  # pleased
        harness.render()
        warm = [
            cell
            for row in app.app.render().cells[page.rect.y : page.rect.bottom]
            for cell in row
            if cell.character == "\u25cf" and cell.style.foreground == theme.warning
        ]
        assert warm, f"{theme.name}: and when pleased, the warm colour"


async def test_a_narrow_screen_has_the_list_and_no_stage_and_a_short_one_scrolls_the_list(config_file):  # noqa: F811
    app, harness, _ = shell(width=MIN_WIDTH_FOR_BOX - 1)
    await _type_command(app, harness, "/pet")
    text = harness.render().text
    assert "cat" in text and "at work" not in text and "asleep" not in text

    app, harness, _ = shell(height=22)
    await _type_command(app, harness, "/pet")
    page = page_of(app)
    assert page._view() < len(BUNDLED) or page.rect.height - 4 < BOX_HEIGHT
    harness.press("end")
    assert page.marked == "sprout" and "sprout" in harness.render().text, "the mark is always in view"


async def test_a_pet_that_cannot_be_built_is_still_listed_and_the_stage_says_so(config_file):  # noqa: F811
    def broken() -> Pet:
        raise RuntimeError("no paint today")

    app, harness, _ = shell(PetSource("oops", broken, "never drawn"))
    await _type_command(app, harness, "/pet")
    harness.press("end")

    text = harness.render().text
    assert "oops" in text and "could not be built" in text
    harness.press("enter")
    assert app.pet.pet.name == "cat", "choosing it is refused and nothing changes"
    assert any("could not be built" in text for text in errors_of(app))


def test_painted_cells_under_the_floating_pet_are_the_previewed_pets_not_the_old_ones():
    app, harness, _ = shell()
    app.preview_pet("dog")
    rect = stands(app, harness)
    assert shows(app, rect, IDLE, pet=CATALOG.load("dog")) and painted(app, rect)
    app.preview_pet(None)
    assert app.pet.pet.name == "cat"
