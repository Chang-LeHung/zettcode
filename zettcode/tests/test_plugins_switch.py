"""The `/plugins` switch: recorded in ZettCode's own file, honoured at the next start."""

from __future__ import annotations

import json
import sys
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from zettcode.app.plugins import TuiPlugin
from zettcode.app.plugins.builtin_commands import PluginCommand
from zettcode.app.plugins.loader import load_terminal_plugins
from zettcode.config import ModelConfig, ZettCodeConfig


def _config(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        plugins_file=tmp_path / "plugins.json",
        mcp_enabled=False,
        skills_enabled=False,
    )
    for key, value in changes.items():
        object.__setattr__(config, key, value)
    return config


def test_the_switch_file_is_read_as_the_disabled_list(tmp_path: Path):
    from zettcode.config import read_disabled_plugins

    path = tmp_path / "plugins.json"
    path.write_text(json.dumps({"disabled": ["greeter", "  ", 7]}), encoding="utf-8")

    assert read_disabled_plugins(path) == ("greeter",)
    assert read_disabled_plugins(tmp_path / "missing.json") == ()


class Doubled(TuiPlugin):
    """A plugin that claims one name twice: a plain command and a terminal one."""

    name = "doubled"

    def activate(self, ctx) -> None:
        from zettcode.app.commands import CommandResult
        from zettcode.engine.plugins.commands import TextCommandResult

        async def plain(context):
            return TextCommandResult(message="plain")

        async def tui_command(context):
            return CommandResult(message="tui")

        ctx.commands.register("/dup", "plain", plain)
        assert ctx.tui is not None
        ctx.tui.register_command("dup", "tui", tui_command)


class Greeter(TuiPlugin):
    """An installed plugin, which is the kind a switch can turn off."""

    name = "greeter"

    def activate(self, ctx) -> None:
        pass


def test_a_hand_built_config_reads_its_own_switch_file(tmp_path: Path):
    """Every `Client(models=…)` builds a config this way: the file beside it is what the loader must read."""
    config = _config(tmp_path)
    point = EntryPoint(name="greeter", value=f"{__name__}:Greeter", group="zettcode.plugins")
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter"]}), encoding="utf-8")

    bundle = load_terminal_plugins(config, builtins=(), entry_points=(point,))

    assert [plugin.name for plugin in bundle.plugins] == [], "the file the config names, not the default one"


def test_a_plugin_cannot_claim_one_name_in_both_groups(tmp_path: Path):
    """Its own plain command and its own terminal command share one namespace, like every other plugin's."""
    point = EntryPoint(name="doubled", value=f"{__name__}:Doubled", group="zettcode.plugins")
    bundle = load_terminal_plugins(_config(tmp_path), builtins=(), entry_points=(point,))

    assert bundle.failures and "/dup" in bundle.failures[0], bundle.failures


def test_the_switch_reaches_the_config_a_start_reads(tmp_path: Path, monkeypatch):
    from zettcode.config import load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter", "acme"]}), encoding="utf-8")
    monkeypatch.setattr("zettcode.config.DEFAULT_PLUGINS_FILE", tmp_path / "plugins.json")

    config = load_config(tmp_path, path=config_file)

    assert config.disabled_plugins == ("greeter", "acme"), "one list, resolved where the config is read"


class _Bundle:
    """The parts of a loaded bundle `/plugins` reads."""

    def __init__(self, names: list[str], failures: list[str] | None = None) -> None:
        class _Plugin:
            def __init__(self, name: str) -> None:
                self.name = name
                self.origin = name

        self.plugins = [_Plugin(name) for name in names]
        self.failures = failures or ()


class _Host:
    """The shell, as far as a command that only reads the bundle needs it."""

    class _Agent:
        class _Runtime:
            def __init__(self, plugins: _Bundle) -> None:
                self.plugins = plugins

        def __init__(self, plugins: _Bundle) -> None:
            self.runtime = self._Runtime(plugins)

    def __init__(self, plugins: _Bundle) -> None:
        self.agent = self._Agent(plugins)


def _command_context(plugins: _Bundle, argument: str):
    from zettcode.app.commands import CommandContext

    return CommandContext(argument=argument, ui=object(), host=_Host(plugins))  # type: ignore[arg-type]


async def test_the_listing_names_what_loaded_and_what_the_next_start_leaves_out(tmp_path: Path):
    config = _config(tmp_path)
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["acme"]}), encoding="utf-8")
    command = PluginCommand()

    text = command._listing(_command_context(_Bundle(["shell", "greeter"]), ""), config)

    assert "shell" in text and "greeter" in text
    assert "acme" in text, "the switch file is part of what is off"


async def test_disabling_writes_owner_only_and_only_for_a_real_name(tmp_path: Path, monkeypatch):
    import os
    import stat

    config = _config(tmp_path)
    command = PluginCommand()
    installed = EntryPoint(name="greeter", value=f"{__name__}:Greeter", group="zettcode.plugins")
    bundle = _Bundle(["greeter"])
    context = _command_context(bundle, "disable greeter")

    from zettcode.app.plugins import builtin_commands

    monkeypatch.setattr(builtin_commands, "installed_entry_points", lambda: (installed,))
    result = await command.plugins(context, config)

    assert "off" in result.notification
    path = tmp_path / "plugins.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled": ["greeter"]}
    if sys.platform != "win32":
        # A POSIX permission; Windows has no equivalent, and chmod there changes only the read-only flag.
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    with pytest.raises(ValueError, match="No plugin is called"):
        await command.plugins(_command_context(bundle, "disable typo"), config)


async def test_a_builtin_cannot_be_switched_off(tmp_path: Path):
    config = _config(tmp_path)
    command = PluginCommand()

    with pytest.raises(ValueError, match="compiled into the program"):
        await command.plugins(_command_context(_Bundle(["shell"]), "disable shell"), config)
