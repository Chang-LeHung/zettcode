"""The plugin list and its switches as the SDK hands them over: what the server's panel reads and writes.

The terminal's `/plugins` is one front end of this; the server's panel is the other. Both go through
:mod:`zettcode.engine.plugins.switches`, so the rules about which names exist, which may be switched off and where the
answer is kept are tested once, here, and the front ends only differ in how they show it.
"""

from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import config_for
from zettcode.engine.plugins import Plugin


class Greeter(Plugin):
    """An installed plugin, loaded from an entry point a test injects."""

    name = "greeter"

    def activate(self, ctx) -> None:
        pass


class Broken(Plugin):
    """An installed plugin that raises in `activate`, so the catalog has a failure to show."""

    name = "broken"

    def activate(self, ctx) -> None:
        raise RuntimeError("no such module")


def _points(*names: str) -> tuple[EntryPoint, ...]:
    values = {"greeter": f"{__name__}:Greeter", "broken": f"{__name__}:Broken"}
    return tuple(EntryPoint(name=name, value=values[name], group="zettcode.plugins") for name in names)


def _installed(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make the loader discover these entry points, as if they were installed."""
    from zettcode.engine.plugins import loader, switches

    points = _points(*names)
    monkeypatch.setattr(loader, "installed_entry_points", lambda: points)
    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: points)


async def test_a_client_lists_the_plugins_compiled_into_the_program(tmp_path: Path):
    async with zc.Client(config=config_for(tmp_path)) as client:
        report = client.plugins

    builtins = [entry for entry in report.entries if entry.builtin]
    assert builtins, "the engine's own plugins are compiled into the program"
    assert {entry.name for entry in builtins} <= set(report.loaded)
    assert all(entry.enabled for entry in builtins), "a builtin always loads"


async def test_an_installed_plugin_is_listed_with_the_name_a_switch_is_written_with(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")

    async with zc.Client(config=config_for(tmp_path)) as client:
        entries = client.plugins.entries

    greeter = next(entry for entry in entries if entry.name == "greeter")
    assert (greeter.origin, greeter.builtin, greeter.enabled, greeter.failure) == ("greeter", False, True, "")


async def test_a_plugin_that_cannot_load_is_listed_with_why(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "broken")

    async with zc.Client(config=config_for(tmp_path)) as client:
        report = client.plugins

    failed = next(entry for entry in report.entries if entry.name == "broken")
    assert "no such module" in failed.failure
    assert report.failures == ("broken: no such module",)


async def test_a_switch_is_written_to_the_file_and_read_back(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    config = config_for(tmp_path, plugins_file=tmp_path / "plugins.json")

    async with zc.Client(config=config) as client:
        entry = client.set_plugin_enabled("greeter", False)
        assert entry.enabled is False, "the answer is the list as it now stands"
        written = json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8"))
        assert written == {"disabled": ["greeter"]}

        assert client.set_plugin_enabled("greeter", True).enabled is True
        assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": []}

    assert [item.name for item in client.plugins.entries if item.name == "greeter"] == ["greeter"], "still loaded here"


async def test_the_switch_changes_the_next_start_and_not_this_one(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    config = config_for(tmp_path, plugins_file=tmp_path / "plugins.json")

    async with zc.Client(config=config) as client:
        client.set_plugin_enabled("greeter", False)
        assert "greeter" in client.plugins.loaded, "this process keeps the plugins it loaded"

    async with zc.Client(config=config) as second:
        assert "greeter" not in second.plugins.loaded, "the next start honours the switch"
        assert [entry.enabled for entry in second.plugins.entries if entry.name == "greeter"] == [False]


async def test_a_builtin_cannot_be_switched_off(tmp_path: Path, monkeypatch):
    _installed(monkeypatch)
    config = config_for(tmp_path, plugins_file=tmp_path / "plugins.json")

    async with zc.Client(config=config) as client:
        builtin = next(entry for entry in client.plugins.entries if entry.builtin)
        with pytest.raises(ValueError, match="compiled into the program"):
            client.set_plugin_enabled(builtin.origin, False)

    assert not (tmp_path / "plugins.json").exists(), "nothing was written"


async def test_a_name_no_plugin_has_is_refused(tmp_path: Path, monkeypatch):
    _installed(monkeypatch)
    config = config_for(tmp_path, plugins_file=tmp_path / "plugins.json")

    async with zc.Client(config=config) as client:
        with pytest.raises(ValueError, match="No plugin is called"):
            client.set_plugin_enabled("greter", False)


async def test_a_plugin_the_configuration_switched_off_cannot_be_switched_on(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    config = config_for(
        tmp_path,
        plugins_file=tmp_path / "plugins.json",
        disabled_plugins=("greeter",),
    )

    async with zc.Client(config=config) as client:
        assert [entry.enabled for entry in client.plugins.entries if entry.name == "greeter"] == [False]
        with pytest.raises(ValueError, match="configuration file"):
            client.set_plugin_enabled("greeter", True)
