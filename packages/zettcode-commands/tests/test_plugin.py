"""The commands plugin registers every command group, in the order /help lists them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from zettcode.app.plugins.loader import terminal_context
from zettcode.commands.plugin import CommandsPlugin
from zettcode.config import ModelConfig, ZettCodeConfig


def _config(tmp_path: Path) -> ZettCodeConfig:
    return replace(ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)))


def test_the_commands_are_registered_in_the_order_help_lists_them(tmp_path: Path):
    ctx = terminal_context(_config(tmp_path))

    CommandsPlugin().activate(ctx)

    names = [command.name for command in ctx.tui.registered_commands]
    assert names[:2] == ["/help", "/plugins"]
    assert names[-2:] == ["/usage", "/hub"]
    assert {"/resume", "/model", "/btw", "/bash", "/clear", "/quit", "/hub"} <= set(names)
    assert [plain.name for plain in ctx.commands.commands] == ["/code-review"]


def test_without_a_screen_it_registers_nothing_and_does_not_fail(tmp_path: Path):
    from zettcode.engine.plugins.context import PluginContext

    ctx = PluginContext(_config(tmp_path), {})

    CommandsPlugin().activate(ctx)

    assert ctx.tui is None and ctx.commands.commands == ()
