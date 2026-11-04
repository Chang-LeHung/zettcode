"""The commands of the program's own plugins stand ahead of an installed plugin's, whatever order they load in."""

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


def test_a_part_that_loads_after_an_installed_plugin_still_counts_as_the_programs_own(tmp_path: Path):
    plugins = load_terminal_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[
            FakeEntryPoint("installed", Installed),
            FakeEntryPoint("part", Part, "zettcode.terminal"),
        ],
    )

    assert [plugin.name for plugin in plugins.plugins] == ["installed", "part"]
    assert [command.name for command in plugins.builtin_commands] == ["/part"]
    assert [command.name for command in plugins.installed_commands] == ["/inst"]
    assert [command.name for command in plugins.commands] == ["/part", "/inst"]
