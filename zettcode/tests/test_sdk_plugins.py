"""The plugin list and its switches as the SDK hands them over: what the server's panel reads and writes.

The terminal's `/plugins` is one front end of this; the server's panel is the other. Both go through
:mod:`zettcode.engine.plugins.switches`, so the rules about which names exist, which may be switched off and where the
answer is kept are tested once, here, and the front ends only differ in how they show it.
"""

from __future__ import annotations

import pathlib
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import tomllib

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


async def test_a_client_lists_the_plugins_compiled_into_the_program_that_can_be_switched(tmp_path: Path):
    async with zc.Client(config=config_for(tmp_path)) as client:
        report = client.plugins

    builtins = [entry for entry in report.entries if entry.builtin]
    assert builtins, "the engine's own plugins are compiled into the program"
    assert all(entry.setting for entry in builtins), "a row is listed because it has a setting to write"
    assert {entry.name for entry in builtins} <= set(report.loaded)
    assert "coding" not in [entry.name for entry in builtins], "a tool with no switch is not on the list"
    assert [entry.enabled for entry in builtins if entry.name == "skills"] == [False], "the setting decides it"


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


async def test_a_switch_is_written_to_the_configuration_file_and_read_back(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = config_for(tmp_path)

    async with zc.Client(config=config) as client:
        entry = client.set_plugin_enabled("greeter", False)
        assert entry.enabled is False, "the answer is the list as it now stands"
        assert tomllib.loads(path.read_text(encoding="utf-8"))["plugins"]["disable"] == ["greeter"]

        assert client.set_plugin_enabled("greeter", True).enabled is True
        assert tomllib.loads(path.read_text(encoding="utf-8"))["plugins"]["disable"] == []

    assert [item.name for item in client.plugins.entries if item.name == "greeter"] == ["greeter"], "still loaded here"


async def test_the_switch_changes_the_next_start_and_not_this_one(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = config_for(tmp_path)

    async with zc.Client(config=config) as client:
        client.set_plugin_enabled("greeter", False)
        assert "greeter" in client.plugins.loaded, "this process keeps the plugins it loaded"

    from zettcode.config import load_config

    second_config = load_config(tmp_path, path=path)
    async with zc.Client(config=second_config) as second:
        assert "greeter" not in second.plugins.loaded, "the next start honours the switch"
        assert [entry.enabled for entry in second.plugins.entries if entry.name == "greeter"] == [False]


async def test_a_compiled_in_plugin_is_switched_by_its_configuration_key(tmp_path: Path, monkeypatch):
    _installed(monkeypatch)
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = config_for(tmp_path, skills_enabled=True)

    async with zc.Client(config=config) as client:
        entry = client.set_plugin_enabled("skills", False)
        assert entry.enabled is False, "the answer is the list as it now stands"
        assert "[skills]\nenabled = false" in path.read_text(encoding="utf-8")
        assert client.plugins.entries[0].setting == "skills.enabled"

        assert client.set_plugin_enabled("skills", True).enabled is True
        assert "[skills]\nenabled = true" in path.read_text(encoding="utf-8")

    assert "skills" in client.plugins.loaded, "this process keeps the plugins it loaded"


async def test_a_name_no_plugin_has_is_refused(tmp_path: Path, monkeypatch):
    _installed(monkeypatch)
    config = config_for(tmp_path, plugins_file=tmp_path / "plugins.json")

    async with zc.Client(config=config) as client:
        with pytest.raises(ValueError, match="No plugin is called"):
            client.set_plugin_enabled("greter", False)


async def test_a_plugin_the_configuration_switched_off_can_be_switched_on(tmp_path: Path, monkeypatch):
    _installed(monkeypatch, "greeter")
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = config_for(tmp_path, disabled_plugins=("greeter",))

    async with zc.Client(config=config) as client:
        assert [entry.enabled for entry in client.plugins.entries if entry.name == "greeter"] == [False]
        assert client.set_plugin_enabled("greeter", True).enabled is True

    assert tomllib.loads(path.read_text(encoding="utf-8"))["plugins"]["disable"] == []


def test_the_same_entry_is_described_the_same_way_in_every_layer():
    """Four copies of one value — engine, SDK, HTTP schema, TypeScript — and a field that drifts is a lie somewhere.

    The SDK may not name an engine type in its signature, and the server may not send a Python object, so the value is
    copied; this is the one place that says the copies agree.
    """
    import re

    from zettcode.app.ui.widgets.plugins_page import PluginRow
    from zettcode.engine.plugins.switches import PluginEntry as EngineEntry
    from zettcode.sdk.types import PluginEntry as SdkEntry
    from zettcode.server.schemas import PluginOut

    typescript = (pathlib.Path(__file__).resolve().parents[2] / "clients/typescript/src/types.ts").read_text(
        encoding="utf-8"
    )
    body = re.search(r"export interface PluginEntry \{(.*?)\n\}", typescript, re.S)
    assert body is not None, "clients/typescript/src/types.ts has no PluginEntry"
    scripted = set(re.findall(r"^  ([a-z][A-Za-z0-9]*):", body.group(1), re.M))

    engine = set(EngineEntry.__dataclass_fields__)
    sdk = set(SdkEntry.__dataclass_fields__)
    http = set(PluginOut.model_fields)
    widget = set(PluginRow.__dataclass_fields__)

    assert engine == sdk == http == scripted == widget, (engine, sdk, http, scripted, widget)


async def test_the_configuration_file_written_is_the_programs_not_the_clients(tmp_path: Path, monkeypatch):
    """A client given `config_path=…` reads that file, and a switch still writes the file the program uses.

    That is the program's own rule — the models, the theme and the status line all write `config_path()` — and this is
    where it is written down, so the next one who wonders gets an answer from a test rather than from the code.
    """
    from zettcode.paths import config_path

    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nenabled = true\n', encoding="utf-8")
    program = tmp_path / "program.toml"
    program.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(program))

    async with zc.Client(
        workspace=project,
        config_path=elsewhere,
        store=tmp_path / "sessions",
        plugins_file=tmp_path / "plugins.json",
        # Nothing of this machine: no MCP servers from the home file, no session or instructions outside `tmp_path`.
        mcp_enabled=False,
        mcp_config=tmp_path / "absent-mcp.json",
        agents_md_enabled=False,
        subagent_enabled=False,
        sessions_enabled=False,
        update_enabled=False,
    ) as client:
        assert client.config.skills_enabled is True, "the client read the file it was given"
        client.set_plugin_enabled("skills", False)

    assert config_path() == program
    assert "[skills]\nenabled = false" in program.read_text(encoding="utf-8")
    assert "enabled = true" in elsewhere.read_text(encoding="utf-8"), "the file the client read is left alone"
