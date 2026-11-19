"""A plugin's commands are registered in the order its plugin loads, and `deps` decides that order."""

from __future__ import annotations

from pathlib import Path

from test_plugins import FakeEntryPoint, make_config

from zettcode.app.plugins import PluginContext, TuiPlugin, load_terminal_plugins
from zettcode.plugin_api.commands import CommandResult


async def _nothing(context) -> CommandResult:
    return CommandResult()


class Installed(TuiPlugin):
    name = "installed"

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_command("inst", "an installed plugin's", _nothing)


class Part(TuiPlugin):
    """A part of the program that needs a plugin a reader installed, so the loader activates it second."""

    name = "part"
    deps = ("installed",)

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_command("part", "the program's own", _nothing)


def test_a_plugins_commands_follow_the_dependency_order_the_plugins_load_in(tmp_path: Path):
    plugins = load_terminal_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("part", Part), FakeEntryPoint("installed", Installed)],
    )

    assert [plugin.name for plugin in plugins.plugins] == ["installed", "part"], "`part` needs `installed`"
    assert [command.name for command in plugins.commands] == ["/inst", "/part"]
