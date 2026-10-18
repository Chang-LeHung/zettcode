"""Palettes are files with names, plugins offer them, `/theme <name>` picks one, and the menu previews each."""

from __future__ import annotations

import asyncio
import dataclasses
from importlib import resources
from pathlib import Path

import pytest

from test_plugins import FakeEntryPoint, make_config
from test_zettcode_app import _harness, _type_command, build_app, rows_and_commands
from zettcode import cli
from zettcode.config import ZettCodeConfig, load_config
from zettcode.plugins import Plugin, PluginContainer, load_plugins
from zettcode.tui import DARK, LIGHT, Theme, ThemeCatalog, ThemeFileError, bundled_themes
from zettcode.tui.render.color import parse_hex
from zettcode.tui.theme_file import BUNDLED


def luminance(colour: str) -> float:
    red, green, blue = (
        ((c / 255) / 12.92) if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4
        for c in parse_hex(colour)  # type: ignore[union-attr]
    )
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def catalog(directory: Path | None = None) -> ThemeCatalog:
    return ThemeCatalog(bundled_themes(), directory)


def write_theme(directory: Path, name: str, accent: str = "#ff00aa", note: str = "mine") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.toml"
    path.write_text(f'description = "{note}"\nbase = "dark"\n\n[ui]\naccent = "{accent}"\n', encoding="utf-8")
    return path


# -- the ones that ship -----------------------------------------------------------------------------------------


def test_every_palette_that_ships_is_a_file_and_every_file_is_listed():
    folder = resources.files("zettcode.tui") / "themes"
    files = sorted(item.name.removesuffix(".toml") for item in folder.iterdir() if item.name.endswith(".toml"))

    assert files == sorted(BUNDLED)
    assert len(BUNDLED) == len(set(BUNDLED))


@pytest.mark.parametrize("name", BUNDLED)
def test_a_shipped_palette_loads_under_its_name_with_a_page_colour_a_note_and_readable_text(name: str):
    theme = catalog().load(name)

    assert theme.name == name and theme.code.name == name
    assert theme.background is not None, "a palette is judged on its own page, whatever the terminal's is"
    assert contrast(theme.text, theme.background) >= 7.0
    assert contrast(theme.muted, theme.background) >= 4.0
    assert contrast(theme.muted, theme.surface_alt) >= 4.0
    assert catalog().notes()[name], "the menu shows a note beside the name"
    assert len({theme.surface, theme.surface_alt, theme.surface_side, theme.surface_peer}) == 4


def test_the_palettes_that_ship_do_not_repeat_each_other():
    assert len({catalog().load(name) for name in BUNDLED}) == len(BUNDLED)


def test_the_menu_lists_the_two_default_palettes_first_then_the_ones_that_ship():
    assert catalog().names()[:2] == ("dark", "light")
    assert catalog().names()[2:] == BUNDLED
    for name, base in ("dark", DARK), ("light", LIGHT):
        chosen = catalog().load(name)
        assert chosen.background is not None, "chosen by name it paints its own page, like every other palette"
        assert dataclasses.replace(chosen, background=None) == base, "and is otherwise the stock palette"


def test_nothing_is_read_until_a_palette_is_asked_for():
    asked: list[str] = []

    def build() -> Theme:
        asked.append("built")
        return DARK

    known = ThemeCatalog([bundled_themes()[0], dataclasses.replace(bundled_themes()[1], name="lazy", load=build)])
    assert "lazy" in known.names() and asked == []
    known.load("lazy")
    assert asked == ["built"]


def test_a_name_nobody_has_is_refused_with_the_list(tmp_path: Path):
    with pytest.raises(ThemeFileError, match=r"Unknown theme: 'nope'.*nord"):
        catalog(tmp_path).load("nope")
    with pytest.raises(ThemeFileError):
        catalog(tmp_path).load("../etc/passwd")


# -- the reader's own -------------------------------------------------------------------------------------------


def test_a_file_in_the_directory_is_a_palette_with_the_files_name(tmp_path: Path):
    write_theme(tmp_path, "mine", accent="#ff00aa", note="pink on dark")
    found = catalog(tmp_path)

    assert found.names()[-1] == "mine"
    assert found.load("mine").accent == "#ff00aa" and found.load("mine").name == "mine"
    assert found.notes()["mine"] == "pink on dark"
    assert "mine" not in catalog(tmp_path / "missing").names(), "a directory that is not there is an empty one"


def test_a_file_of_the_same_name_replaces_the_one_that_ships_and_is_listed_once(tmp_path: Path):
    write_theme(tmp_path, "nord", accent="#123456")

    assert catalog(tmp_path).load("nord").accent == "#123456"
    assert catalog(tmp_path).names().count("nord") == 1
    assert catalog().load("nord").accent != "#123456", "the shipped one is untouched"


def test_dark_and_light_cannot_be_taken_over_by_a_file(tmp_path: Path):
    write_theme(tmp_path, "dark", accent="#123456")

    assert catalog(tmp_path).load("dark").accent == DARK.accent
    assert catalog(tmp_path).names().count("dark") == 1


def test_a_file_whose_name_is_not_one_word_is_left_out(tmp_path: Path):
    write_theme(tmp_path, "two words")
    write_theme(tmp_path, "-leading")
    write_theme(tmp_path, "fine_one")

    assert [name for name in catalog(tmp_path).names() if name not in BUNDLED + ("dark", "light")] == ["fine_one"]


def test_a_broken_file_is_listed_and_its_error_is_the_error_of_whoever_picks_it(tmp_path: Path):
    (tmp_path / "broken.toml").write_text("[ui\naccent = ", encoding="utf-8")
    write_theme(tmp_path, "fine")
    found = catalog(tmp_path)

    assert "broken" in found.names()
    assert "broken" not in found.notes() and "fine" in found.notes()
    with pytest.raises(ThemeFileError, match="Invalid theme file"):
        found.load("broken")


# -- plugins ----------------------------------------------------------------------------------------------------


class Sunset(Plugin):
    name = "sunset-pack"

    def __init__(self) -> None:
        self.built = 0

    def activate(self, container: PluginContainer) -> None:
        container.register_theme("sunset", dataclasses.replace(DARK, accent="#ff8800"), description="warm")
        container.register_theme("lazy-sunset", self.build, description=lambda: "built late")

    def build(self) -> Theme:
        self.built += 1
        return dataclasses.replace(LIGHT, accent="#cc5500")


def test_a_plugin_offers_palettes_by_name_after_the_ones_that_ship(tmp_path: Path):
    plugin = Sunset()
    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("sunset", lambda: plugin)])

    names = [source.name for source in plugins.themes]
    assert names[: len(BUNDLED)] == list(BUNDLED), "the built-in plugin's come first"
    assert names[len(BUNDLED) :] == ["sunset", "lazy-sunset"]
    assert plugin.built == 0, "offering a palette builds nothing"
    found = ThemeCatalog(plugins.themes, tmp_path)
    assert found.load("sunset").accent == "#ff8800" and found.load("sunset").name == "sunset"
    assert found.load("lazy-sunset").accent == "#cc5500" and plugin.built == 1
    assert found.notes()["sunset"] == "warm" and found.notes()["lazy-sunset"] == "built late"


def test_a_plugin_can_offer_a_theme_file(tmp_path: Path):
    path = write_theme(tmp_path, "packaged", accent="#00ff88", note="from a file in the package")

    class FromFile(Plugin):
        name = "from-file"

        def activate(self, container: PluginContainer) -> None:
            container.register_theme("packaged", path)

    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("f", FromFile)])
    found = ThemeCatalog(plugins.themes)

    assert found.load("packaged").accent == "#00ff88"
    assert found.notes()["packaged"] == "from a file in the package"


def test_a_plugin_cannot_take_a_name_the_program_or_an_earlier_plugin_has(tmp_path: Path):
    class Greedy(Plugin):
        name = "greedy"

        def activate(self, container: PluginContainer) -> None:
            container.register_theme("nord", DARK)

    class Second(Plugin):
        name = "second"

        def activate(self, container: PluginContainer) -> None:
            container.register_theme("sunset", DARK)

    plugins = load_plugins(
        make_config(tmp_path),
        entry_points=[FakeEntryPoint("a", Sunset), FakeEntryPoint("b", Second), FakeEntryPoint("c", Greedy)],
    )

    assert any("c: theme nord is already registered" in failure for failure in plugins.failures)
    assert any("b: theme sunset is already registered" in failure for failure in plugins.failures)
    assert [source.name for source in plugins.themes if source.name == "sunset"] == ["sunset"]


@pytest.mark.parametrize("name", ["dark", "light", "two words", "", "a/b"])
def test_a_name_that_could_not_be_typed_after_theme_is_refused_when_registered(tmp_path: Path, name: str):
    container = PluginContainer(make_config(tmp_path))

    with pytest.raises(ValueError):
        container.register_theme(name, DARK)


def test_a_palette_registered_twice_by_one_plugin_is_refused(tmp_path: Path):
    container = PluginContainer(make_config(tmp_path))
    container.register_theme("once", DARK)

    with pytest.raises(ValueError, match="already registered"):
        container.register_theme("once", LIGHT)


def test_a_plugin_whose_palette_cannot_be_built_is_reported_by_name_when_picked(tmp_path: Path):
    def broken() -> Theme:
        raise RuntimeError("no colours today")

    found = ThemeCatalog([dataclasses.replace(bundled_themes()[0], name="oops", load=broken)])

    assert "oops" in found.names()
    with pytest.raises(ThemeFileError, match="'oops' could not be built: no colours today"):
        found.load("oops")


# -- the start --------------------------------------------------------------------------------------------------


def config_in(tmp_path: Path, text: str) -> ZettCodeConfig:
    path = tmp_path / "config.toml"
    path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n{text}', encoding="utf-8")
    return load_config(tmp_path, path=path)


class Agent:
    """The two things the start asks an agent: its config, and its palettes."""

    def __init__(self, config: ZettCodeConfig, plugins=()) -> None:
        self.runtime = type(
            "R", (), {"config": config, "session_locks": type("L", (), {"release": lambda self: None})()}
        )()
        self.themes = ThemeCatalog([*bundled_themes(), *plugins], config.themes_dir)


def test_the_config_names_the_palette_to_start_in(tmp_path: Path):
    assert config_in(tmp_path, "").theme is None
    assert config_in(tmp_path, '[ui]\ntheme = "nord"\n').theme == "nord"
    with pytest.raises(ValueError, match="ui.theme"):
        config_in(tmp_path, '[ui]\ntheme = "two words"\n')
    with pytest.raises(ValueError, match="Unknown"):
        config_in(tmp_path, '[ui]\nthemee = "nord"\n')


def test_a_named_palette_is_a_choice_so_the_terminals_light_or_dark_does_not_override_it(tmp_path: Path):
    config = dataclasses.replace(config_in(tmp_path, ""), theme="nord", themes_dir=tmp_path / "themes")

    assert cli.chosen_theme(Agent(config)) == catalog().load("nord")
    assert cli.chosen_theme(Agent(dataclasses.replace(config, theme=None))) is None


def test_a_palette_a_plugin_offers_can_be_the_one_to_start_in(tmp_path: Path):
    plugin = Sunset()
    config = dataclasses.replace(config_in(tmp_path, ""), theme="sunset", themes_dir=tmp_path / "themes")
    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("s", lambda: plugin)])

    chosen = cli.chosen_theme(Agent(config, plugins.themes))

    assert chosen is not None and chosen.accent == "#ff8800"


def test_the_theme_file_is_laid_over_the_named_palette(tmp_path: Path):
    adjust = tmp_path / "theme.toml"
    adjust.write_text('[ui]\naccent = "#010203"\n', encoding="utf-8")
    config = dataclasses.replace(config_in(tmp_path, ""), theme="nord", theme_file=adjust)

    chosen = cli.chosen_theme(Agent(config))

    assert chosen is not None and chosen.accent == "#010203"
    assert chosen.background == catalog().load("nord").background, "everything else is still nord's"


def test_a_name_nobody_has_stops_the_start_with_a_message_not_a_traceback(tmp_path: Path):
    config = dataclasses.replace(config_in(tmp_path, ""), theme="nope", themes_dir=tmp_path)

    with pytest.raises(SystemExit, match="Unknown theme: 'nope'"):
        cli.chosen_theme(Agent(config))


# -- in the shell -----------------------------------------------------------------------------------------------


def shell(tmp_path: Path, *extra):
    plugins = rows_and_commands()
    plugins = dataclasses.replace(plugins, themes=(*plugins.themes, *extra))
    app = build_app(plugins=plugins)
    app.agent.runtime.config = dataclasses.replace(app.agent.runtime.config, themes_dir=tmp_path)
    return app, _harness(app)


async def test_the_theme_command_switches_to_a_palette_by_its_name(tmp_path: Path):
    app, harness = shell(tmp_path)

    await _type_command(app, harness, "/theme nord")

    assert app.app.theme == catalog().load("nord")


async def test_the_theme_command_switches_to_a_file_the_reader_added_without_a_restart(tmp_path: Path):
    app, harness = shell(tmp_path)
    write_theme(tmp_path, "mine", accent="#ff00aa")

    await _type_command(app, harness, "/theme mine")

    assert app.app.theme.accent == "#ff00aa"


async def test_the_theme_command_switches_to_a_palette_a_plugin_offered(tmp_path: Path):
    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("s", Sunset)])
    app, harness = shell(tmp_path, *plugins.themes)

    await _type_command(app, harness, "/theme sunset")

    assert app.app.theme.accent == "#ff8800"


async def test_an_unknown_name_is_reported_with_the_list_and_changes_nothing(tmp_path: Path):
    app, harness = shell(tmp_path)
    before = app.app.theme

    await _type_command(app, harness, "/theme nope")

    assert app.app.theme is before
    assert any("Unknown theme: 'nope'" in entry.text for entry in app.transcript.entries)


async def test_the_menu_lists_every_source_with_its_note(tmp_path: Path):
    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("s", Sunset)])
    app, harness = shell(tmp_path, *plugins.themes)
    write_theme(tmp_path, "mine", note="pink on dark")

    await _type_command(app, harness, "/theme")

    items = {item.value: item.description for item in app.completions.items}
    assert "pink on dark" in items["mine"] and "arctic" in items["nord"] and "warm" in items["sunset"]


async def test_walking_the_menu_shows_each_palette_and_escape_puts_the_old_one_back(tmp_path: Path):
    app, harness = shell(tmp_path)
    original = app.app.theme
    await _type_command(app, harness, "/theme")
    assert app.completions.current.value == "dark"
    assert app.app.theme is original, "opening the menu changes nothing"

    harness.press("down")  # light
    assert app.app.theme == catalog().load("light") and app.app.theme.background is not None
    harness.press("down")  # the first that ships
    assert app.app.theme == catalog().load(app.completions.current.value)
    harness.press("down")
    assert app.app.theme == catalog().load(app.completions.current.value)
    harness.press("up")
    harness.press("up")
    harness.press("up")  # back on the one in force
    assert app.app.theme is original, "the word in force is not previewed over a palette the reader adjusted"

    harness.press("down")
    harness.press("down")
    assert app.app.theme is not original
    harness.press("escape")

    assert app.app.theme is original
    assert app._theme_before is None


async def test_enter_on_a_previewed_palette_keeps_it(tmp_path: Path):
    app, harness = shell(tmp_path)
    await _type_command(app, harness, "/theme")
    harness.press("down")
    harness.press("down")
    chosen = app.completions.current.value

    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.app.theme == catalog().load(chosen)
    assert app._theme_before is None and app._previewing is None
    assert app.composer.text == ""


async def test_clearing_the_draft_ends_the_preview(tmp_path: Path):
    app, harness = shell(tmp_path)
    original = app.app.theme
    await _type_command(app, harness, "/theme")
    harness.press("down")
    harness.press("down")
    assert app.app.theme is not original

    app.composer.set_text("")
    app._refresh_completions()

    assert app.app.theme is original


async def test_a_palette_that_cannot_be_loaded_is_skipped_by_the_preview_and_reported_when_picked(tmp_path: Path):
    app, harness = shell(tmp_path)
    (tmp_path / "broken.toml").write_text("[ui\n", encoding="utf-8")
    original = app.app.theme

    app.preview_theme("broken")

    assert app.app.theme is original and app._theme_before is None
    with pytest.raises(ValueError, match="Invalid theme file"):
        app.apply_theme("broken")


# -- remembering ------------------------------------------------------------------------------------------------

CONFIG = '# my settings\n[[models]]\nmodel = "m"\ntoken = "t"\n\n[update]\nenabled = false  # quiet\n'


def test_the_choice_is_written_as_one_line_and_nothing_else_moves(tmp_path: Path):
    from zettcode.config_edit import set_theme

    result = set_theme(CONFIG, "nord", where=tmp_path / "config.toml")

    assert result.startswith(CONFIG.rstrip("\n")) and result.rstrip("\n").endswith('[ui]\ntheme = "nord"')
    assert "# my settings" in result and "enabled = false  # quiet" in result


def test_an_existing_choice_is_replaced_in_place_and_a_neighbouring_key_is_kept(tmp_path: Path):
    from zettcode._compat import tomllib
    from zettcode.config_edit import set_theme

    text = CONFIG + '\n[ui]\n# which palette\ntheme = "dracula"  # old\nother = 1\n\n[harness]\nsubagent = false\n'

    once = set_theme(text, "nord", where=tmp_path / "c.toml")
    twice = set_theme(once, "kanagawa", where=tmp_path / "c.toml")

    data = tomllib.loads(twice)
    assert data["ui"] == {"theme": "kanagawa", "other": 1} and data["harness"] == {"subagent": False}
    assert twice.count("theme =") == 1 and "# which palette" in twice


def test_a_ui_table_written_as_an_inline_table_is_refused_not_guessed_at(tmp_path: Path):
    from zettcode.config_edit import ConfigEditError, set_theme

    with pytest.raises(ConfigEditError, match="by hand"):
        set_theme("ui = { theme = 'x' }\n" + CONFIG, "nord", where=tmp_path / "c.toml")


async def test_switching_by_name_is_remembered_for_the_next_start(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    app, harness = shell(tmp_path / "themes")

    await _type_command(app, harness, "/theme nord")

    assert load_config(tmp_path, path=path).theme == "nord"
    assert "[update]" in path.read_text(encoding="utf-8")


async def test_walking_the_menu_remembers_nothing_until_a_palette_is_chosen(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    app, harness = shell(tmp_path / "themes")
    await _type_command(app, harness, "/theme")

    harness.press("down")
    harness.press("down")
    harness.press("escape")

    assert path.read_text(encoding="utf-8") == CONFIG


async def test_a_config_that_cannot_take_the_line_leaves_the_switch_on_and_says_it_will_not_last(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    app, harness = shell(tmp_path / "themes")

    await _type_command(app, harness, "/theme nord")

    assert app.app.theme == catalog().load("nord")
    assert any("will not be remembered" in entry.text for entry in app.transcript.entries)
    assert not (tmp_path / "missing.toml").exists(), "a config file is not made up for a colour"
