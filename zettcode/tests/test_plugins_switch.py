"""`/plugins`: every switch is written to the configuration file, and the next start reads it there."""

from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import tomllib

from zettcode.config import ModelConfig, ZettCodeConfig, read_disabled_plugins
from zettcode.engine.plugins import switches
from zettcode.engine.plugins.plugin import PluginSetting

MODEL = '[[models]]\nmodel = "m"\ntoken = "t"\n'


class _Plugin:
    def __init__(self, name: str, *, origin: str = "", setting: PluginSetting | None = None) -> None:
        self.name = name
        self.origin = origin or name
        self.setting = setting


class _Bundle:
    """The parts of a loaded bundle the catalog and the switch rules read."""

    def __init__(
        self,
        plugins: list[_Plugin] | None = None,
        *,
        builtins: tuple[str, ...] = (),
        failed: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.plugins = plugins or []
        self.builtins = builtins
        self.failed = failed
        self.failures = tuple(f"{origin}: {why}" for origin, why in failed)


@pytest.fixture
def config(tmp_path: Path, monkeypatch) -> tuple[ZettCodeConfig, Path]:
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        plugins_file=tmp_path / "plugins.json",
        plugins_dir=tmp_path / "plugins",
        mcp_enabled=False,
        skills_enabled=False,
    )
    return config, path


def disabled_in(path: Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return list(data.get("plugins", {}).get("disable", []))


def test_an_installed_plugin_is_switched_in_the_configuration_file(config):
    settings, path = config

    switches.set_installed(settings, "greeter", enabled=False)
    assert disabled_in(path) == ["greeter"]

    switches.set_installed(settings, "greeter", enabled=True)
    assert disabled_in(path) == []


def test_a_name_the_configuration_disabled_is_switchable_again(config):
    settings, path = config
    path.write_text(MODEL + '[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    object.__setattr__(settings, "disabled_plugins", ("greeter",))
    point = EntryPoint(name="greeter", value="nowhere:Greeter", group="zettcode.plugins")
    bundle = _Bundle()

    row = next(entry for entry in switches.catalog(settings, bundle, entry_points=(point,)) if entry.name == "greeter")
    assert row.enabled is False and row.switchable

    written, keys, problems = switches.set_many(settings, {"greeter": True}, bundle=bundle, entry_points=(point,))

    assert (written, keys, problems) == ({"greeter": True}, [], [])
    assert disabled_in(path) == []


def test_a_builtin_setting_is_written_to_its_configuration_key(config):
    settings, path = config
    bundle = _Bundle([_Plugin("mcp", setting=PluginSetting("mcp_enabled", "mcp"))], builtins=("mcp",))

    written, keys, problems = switches.set_many(settings, {"mcp": False}, bundle=bundle, entry_points=())

    assert problems == [] and written == {"mcp": False}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["mcp"]["enabled"] is False


def test_a_file_plugin_is_one_row_and_its_switch_is_written(config):
    settings, path = config
    folder = settings.plugins_dir
    folder.mkdir()
    (folder / "hello.py").write_text("class Hello:\n    pass\n", encoding="utf-8")
    bundle = _Bundle()

    rows = [row for row in switches.catalog(settings, bundle, entry_points=()) if row.origin == "hello"]
    assert len(rows) == 1 and rows[0].enabled is True and rows[0].switchable

    switches.set_many(settings, {"hello": False}, bundle=bundle, entry_points=())
    assert disabled_in(path) == ["hello"]


def test_a_file_switched_off_stays_on_the_page(config):
    settings, path = config
    folder = settings.plugins_dir
    folder.mkdir()
    (folder / "hello.py").write_text("class Hello:\n    pass\n", encoding="utf-8")
    path.write_text(MODEL + '[plugins]\ndisable = ["hello"]\n', encoding="utf-8")
    object.__setattr__(settings, "disabled_plugins", ("hello",))

    row = next(entry for entry in switches.catalog(settings, _Bundle(), entry_points=()) if entry.origin == "hello")

    assert row.enabled is False and row.switchable


def test_a_file_that_loads_one_class_and_fails_another_is_one_row(config):
    settings, _path = config
    plugin = _Plugin("good", origin="pair")
    bundle = _Bundle([plugin], failed=(("pair", "Bad: no"), ("pair", "Other: no")))

    row = next(entry for entry in switches.catalog(settings, bundle, entry_points=()) if entry.origin == "pair")

    assert "Bad" in row.failure and "Other" in row.failure and row.switchable


def test_a_file_that_fails_every_class_is_one_row(config):
    settings, _path = config
    bundle = _Bundle(failed=(("pair", "Bad: no"), ("pair", "Other: no")))

    rows = [row for row in switches.catalog(settings, bundle, entry_points=()) if row.origin == "pair"]

    assert len(rows) == 1 and "Bad" in rows[0].failure and "Other" in rows[0].failure


def test_a_global_off_leaves_the_row_without_a_switch(config):
    settings, _path = config
    object.__setattr__(settings, "plugins_enabled", False)
    point = EntryPoint(name="greeter", value="nowhere:Greeter", group="zettcode.plugins")

    row = next(
        entry for entry in switches.catalog(settings, _Bundle(), entry_points=(point,)) if entry.name == "greeter"
    )

    assert row.enabled is False and row.switchable is False


def test_forget_installed_removes_a_name_and_says_whether_it_did(config):
    settings, path = config
    switches.set_installed(settings, "greeter", enabled=False)

    assert switches.forget_installed(settings, "greeter") is True
    assert disabled_in(path) == []
    assert switches.forget_installed(settings, "greeter") is False


def test_a_legacy_switch_file_name_is_dropped_when_the_switch_is_written(config):
    settings, path = config
    settings.plugins_file.write_text(json.dumps({"disabled": ["greeter"]}), encoding="utf-8")

    switches.set_installed(settings, "greeter", enabled=True)

    assert disabled_in(path) == []
    assert read_disabled_plugins(settings.plugins_file) == ()


def test_the_harness_and_self_compaction_are_plugin_switches(config):
    from zettcode.engine.plugins.builtin_agent import AGENT_PLUGINS

    settings = {plugin.name: plugin.setting.path for plugin in AGENT_PLUGINS if plugin.setting is not None}

    assert settings["harness"] == "harness.jit"
    assert settings["self-compaction"] == "compaction.self"


def test_a_switch_that_changes_nothing_writes_nothing(config):
    settings, path = config
    path.unlink()

    switches.set_installed(settings, "greeter", enabled=True)

    assert not path.exists(), "enabling a name that is not off must not create a configuration file"


def test_forget_of_a_name_that_was_not_there_writes_nothing(config):
    settings, path = config
    path.unlink()

    assert switches.forget_installed(settings, "greeter") is False
    assert not path.exists()


def test_a_disable_array_written_across_lines_is_refused_whole(config):
    settings, path = config
    text = MODEL + '[plugins]\ndisable = [\n  "a",\n]\n'
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="not valid TOML"):
        switches.set_installed(settings, "b", enabled=False)

    assert path.read_text(encoding="utf-8") == text, "nothing is half-written"
