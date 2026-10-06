"""The provider registry both the slash commands and the ``@`` resources use."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.app.commands import Command, CommandList, CommandResult
from zettcode.app.registry import Registry
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins import PluginContainer


async def _no_op(argument: str) -> CommandResult:
    """A handler the registry tests never run."""
    return CommandResult()


def _command(name: str, description: str = "") -> Command:
    """Return one command owned by the plugin layer."""
    return Command(name, description, "plugin", _no_op)


def test_a_registry_keeps_the_first_provider_to_claim_a_name():
    first = CommandList((_command("/one", "first"), _command("/two", "first")))
    second = CommandList((_command("/two", "second"), _command("/three", "second")))
    registry = Registry([first, second])

    assert [(command.name, command.description) for command in registry.items()] == [
        ("/one", "first"),
        ("/two", "first"),
        ("/three", "second"),
    ]
    assert registry.find("/three").description == "second"
    assert registry.find("/missing") is None


def test_a_plugin_registers_a_provider_of_commands(tmp_path: Path):
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),))
    container = PluginContainer(config)
    provider = CommandList((_command("/alpha"), _command("/beta")))

    assert container.register_command_provider(provider) is provider
    assert [command.name for command in container.commands] == ["/alpha", "/beta"]

    with pytest.raises(ValueError, match="already registered"):
        container.register_command_provider(CommandList((_command("/beta"),)))
    with pytest.raises(ValueError, match="cannot be empty"):
        container.register_command_provider(CommandList((_command("  "),)))
