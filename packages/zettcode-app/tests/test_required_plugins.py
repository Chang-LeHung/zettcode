"""The parts of the program cannot be turned off: not by `[plugins] disable`, not by a switch, not by a panel.

A plugin the program lists is the program. It loads before any distribution is looked at, and nothing unloads it;
only the ones that declare a configuration key (`skills.enabled`, `mcp.enabled`, …) are optional features, and what
turns those off is that key. Everything else — the row drawing, the commands that act on the shell, the palettes — has no
switch because there is nothing to switch to: a transcript with no presenters draws nothing.

Moving a part into a distribution of its own (`zettcode-presenters`) must not change that, so the rule is held against
the real list rather than against a stand-in, and a part added to the list later is covered without anyone remembering
to add it here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from zettcode.app.plugins import BUILTIN_PLUGINS, load_terminal_plugins
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import catalog, set_many
from zettcode.plugin_api import Plugin


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


#: The parts with no configuration key: what the program cannot do without. `presenters` is among them.
REQUIRED = tuple(_origin(plugin) for plugin in BUILTIN_PLUGINS if plugin.setting is None)


def test_the_list_of_required_parts_includes_the_ones_this_rule_was_written_for():
    assert {"presenters", "themes", "pets"} <= set(REQUIRED)


def test_a_disable_line_that_names_a_part_of_the_program_does_nothing(tmp_path: Path):
    plugins = load_terminal_plugins(_config(tmp_path, disabled_plugins=REQUIRED), entry_points=[])

    assert set(REQUIRED) <= set(plugins.builtins)
    assert plugins.presenters, "the transcript still has the rows the program draws"
    # The agent's own plugins fail here for want of the services a runtime hands over; the required parts do not.
    assert {origin for origin, _why in plugins.failed}.isdisjoint(REQUIRED)


def test_the_disable_file_does_not_reach_a_part_of_the_program_either(tmp_path: Path):
    (tmp_path / "plugins.json").write_text('{"disabled": ["presenters"]}', encoding="utf-8")

    plugins = load_terminal_plugins(_config(tmp_path), entry_points=[])

    assert "presenters" in plugins.builtins and plugins.presenters


def test_the_reader_is_told_in_the_log_when_a_disable_line_names_a_part(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="zettcode.plugins"):
        load_terminal_plugins(_config(tmp_path, disabled_plugins=("presenters",)), entry_points=[])

    assert [record.message for record in caplog.records] == ["plugins.required"]
    assert caplog.records[0].plugin == "presenters"


def test_a_name_that_is_not_a_part_of_the_program_is_not_warned_about(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="zettcode.plugins"):
        load_terminal_plugins(_config(tmp_path, disabled_plugins=("a-distribution",)), entry_points=[])

    assert caplog.records == []


@pytest.mark.parametrize("name", REQUIRED)
def test_no_switch_writes_a_required_part_off(tmp_path: Path, name: str):
    config = _config(tmp_path)
    bundle = load_terminal_plugins(config, entry_points=[])

    written, keys, problems = set_many(config, {name: False}, bundle=bundle, entry_points=[])

    assert (written, keys) == ({}, [])
    assert len(problems) == 1 and "cannot be switched" in problems[0], problems
    assert not (tmp_path / "plugins.json").exists(), "nothing was written anywhere"


def test_the_plugins_page_does_not_offer_a_switch_for_a_required_part(tmp_path: Path):
    config = _config(tmp_path)
    bundle = load_terminal_plugins(config, entry_points=[])

    listed = {entry.origin for entry in catalog(config, bundle, entry_points=[])}

    assert listed.isdisjoint(REQUIRED), "a row with no switch would only invite the press"
    assert listed, "the optional parts, which do have one, are still there"
