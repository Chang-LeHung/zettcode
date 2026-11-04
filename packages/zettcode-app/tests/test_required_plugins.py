"""The parts of the program cannot be turned off: not by `[plugins] disable`, not by a switch, not by a panel.

Two kinds of part, one rule. The plugins compiled into the program load before any distribution is looked at; the
required plugins (`REQUIRED_PLUGINS`, today the rows and the presenters that draw them) are ordinary distributions
found through an entry point, but the terminal names them, so a `disable` line or `[plugins] enabled = false` does not
reach them, and the program does not start when one is missing — a transcript with no presenters draws nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from zettcode.app.plugins import BUILTIN_PLUGINS, load_terminal_plugins
from zettcode.app.plugins.builtins import BuiltinThemes
from zettcode.app.plugins.loader import REQUIRED_PLUGINS
from zettcode.commands.plugin import CommandsPlugin
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import catalog, set_many
from zettcode.engine.plugins.loader import RequiredPluginError
from zettcode.pets.plugin import PetsPlugin
from zettcode.plugin_api import Plugin
from zettcode.presenters.plugin import PresentersPlugin


class Point:
    """The slice of an entry point the loader touches."""

    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self._target = target

    def load(self) -> object:
        return self._target


#: The required plugins that are found through an entry point.
REQUIRED_POINTS = [Point("commands", CommandsPlugin), Point("presenters", PresentersPlugin)]

#: Every part found through an entry point: the required ones, and the ones a reader may switch off.
POINTS = [*REQUIRED_POINTS, Point("pets", PetsPlugin), Point("themes", BuiltinThemes)]


def _config(tmp_path: Path, **overrides: object) -> ZettCodeConfig:
    return ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        plugins_dir=tmp_path / "plugins",
        plugins_file=tmp_path / "plugins.json",
        **overrides,  # type: ignore[arg-type]
    )


def _origin(plugin: Plugin) -> str:
    return plugin.name or type(plugin).__name__


#: The parts with no configuration key: what the program cannot do without.
PARTS = tuple(_origin(plugin) for plugin in BUILTIN_PLUGINS if plugin.setting is None)
REQUIRED = (*PARTS, *REQUIRED_PLUGINS)


def _load(tmp_path: Path, **overrides: object):
    return load_terminal_plugins(_config(tmp_path, **overrides), entry_points=POINTS, required=REQUIRED_PLUGINS)


def test_the_required_plugins_are_the_rows_and_the_presenters():
    assert set(REQUIRED_PLUGINS) == {"shell", "presenters", "commands"}
    assert {"shell", "turn-line"} <= set(PARTS)


def test_a_disable_line_that_names_a_part_of_the_program_does_nothing(tmp_path: Path):
    plugins = _load(tmp_path, disabled_plugins=REQUIRED)

    assert set(REQUIRED) <= set(plugins.builtins)
    assert plugins.presenters, "the transcript still has the rows the program draws"
    # The agent's own plugins fail here for want of the services a runtime hands over; the required parts do not.
    assert {origin for origin, _why in plugins.failed}.isdisjoint(REQUIRED)


def test_plugins_disabled_as_a_whole_still_loads_what_the_program_requires(tmp_path: Path):
    plugins = _load(tmp_path, plugins_enabled=False)

    assert plugins.presenters
    assert "presenters" in [plugin.name for plugin in plugins.plugins]


def test_the_disable_file_does_not_reach_a_part_of_the_program_either(tmp_path: Path):
    (tmp_path / "plugins.json").write_text('{"disabled": ["presenters"]}', encoding="utf-8")

    plugins = _load(tmp_path)

    assert "presenters" in plugins.builtins and plugins.presenters


def test_the_reader_is_told_in_the_log_when_a_disable_line_names_a_part(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="zettcode.plugins"):
        _load(tmp_path, disabled_plugins=("presenters", "turn-line"))

    assert sorted(record.plugin for record in caplog.records if record.message == "plugins.required") == [
        "presenters",
        "turn-line",
    ]


def test_a_name_that_is_not_a_part_of_the_program_is_not_warned_about(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="zettcode.plugins"):
        _load(tmp_path, disabled_plugins=("a-distribution",))

    assert caplog.records == []


def test_the_program_does_not_start_without_its_presenters(tmp_path: Path):
    with pytest.raises(RequiredPluginError) as raised:
        load_terminal_plugins(_config(tmp_path), entry_points=[], required=REQUIRED_PLUGINS)

    assert raised.value.missing == {"presenters": "not installed", "commands": "not installed"}


@pytest.mark.parametrize("name", REQUIRED)
def test_no_switch_writes_a_required_part_off(tmp_path: Path, name: str):
    config = _config(tmp_path)
    bundle = _load(tmp_path)

    written, keys, problems = set_many(config, {name: False}, bundle=bundle, entry_points=POINTS)

    assert (written, keys) == ({}, [])
    assert len(problems) == 1 and "cannot be switched" in problems[0], problems
    assert not (tmp_path / "plugins.json").exists(), "nothing was written anywhere"


def test_the_plugins_page_does_not_offer_a_switch_for_a_required_part(tmp_path: Path):
    config = _config(tmp_path)
    bundle = _load(tmp_path)

    listed = {entry.origin for entry in catalog(config, bundle, entry_points=POINTS)}

    assert listed.isdisjoint(REQUIRED), "a row with no switch would only invite the press"
    assert {"pets", "themes"} <= listed, "the optional parts, which do have a switch, are still there"


def test_the_pets_and_the_palettes_are_parts_a_reader_may_switch_off(tmp_path: Path):
    """Only what the terminal cannot run without is protected: a pet is not worth a refusal to run."""
    plugins = _load(tmp_path, disabled_plugins=("pets", "themes"))

    assert plugins.pets == () and plugins.themes == ()
    assert plugins.presenters, "while the required parts are still there"
    assert {origin for origin, _why in plugins.failed}.isdisjoint(REQUIRED), "the agent's own plugins lack a runtime"


def test_a_process_with_no_screen_is_not_offered_switches_for_the_parts_it_never_loads(tmp_path: Path):
    from zettcode.engine.plugins import load_plugins

    config = _config(tmp_path)
    headless = load_plugins(config, builtins=(), entry_points=[])
    terminal_points = [Point(name, target) for name, target in (("pets", PetsPlugin), ("themes", BuiltinThemes))]
    for point in terminal_points:
        point.group = "zettcode.terminal"  # type: ignore[attr-defined]

    assert catalog(config, headless, entry_points=terminal_points) == ()
