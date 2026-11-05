"""The ``ask_user`` part: the tool a question is put to the reader with, and the switch that turns it off."""

from __future__ import annotations

from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path

from zett_agent.extensions.ask_user import AskUserExtension

from zettcode.ask_user import AskUser
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AgentBuild, load_plugins
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, part_group


class FakeEntryPoint:
    """The slice of ``importlib.metadata.EntryPoint`` the loader touches."""

    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self.group = AGENT_PART_GROUP
        self._target = target

    def load(self) -> object:
        return self._target


def config_for(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    """Return a minimal validated config for a workspace, optionally changed for one test."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
    )
    return replace(config, **changes) if changes else config


def offered(tmp_path: Path, **changes: object) -> list[str]:
    """Load this distribution's one plugin alone, and name the extensions it hands a built agent."""
    config = config_for(tmp_path, **changes)
    plugins = load_plugins(config, builtins=(), entry_points=[FakeEntryPoint(AskUser.name, AskUser)], shared={})

    assert plugins.failures == ()
    return [extension.name for extension in plugins.agent_extensions(AgentBuild(model=object()))]  # type: ignore[arg-type]


def test_the_plugin_is_a_part_of_the_agent_found_through_its_entry_point_group():
    found = {point.name: point for point in entry_points(group=AGENT_PART_GROUP)}

    assert found["ask-user"].value == "zettcode.ask_user.plugin:AskUser"
    assert part_group(found["ask-user"]) == AGENT_PART_GROUP
    assert AskUser.name == "ask-user"


def test_the_tool_is_offered_to_the_agent_when_the_setting_is_on(tmp_path: Path):
    assert offered(tmp_path) == ["AskUserExtension"]


def test_turning_the_setting_off_leaves_the_agent_without_it(tmp_path: Path):
    assert offered(tmp_path, ask_user_enabled=False) == []


def test_the_switch_writes_the_key_the_configuration_already_has():
    """`/plugins` shows a row only when it has a key to write, and this one is the field the runtime reads."""
    setting = AskUser.setting

    assert setting is not None
    assert (setting.field, setting.path) == ("ask_user_enabled", "ask_user.enabled")
    assert hasattr(ZettCodeConfig, setting.field), "the key a switch writes is the field the runtime reads"


def test_the_extension_is_the_one_the_framework_builds(tmp_path: Path):
    """The factory is the framework's extension, not a copy: what is shared with a child is decided by its type."""
    config = config_for(tmp_path)
    plugins = load_plugins(config, builtins=(), entry_points=[FakeEntryPoint(AskUser.name, AskUser)], shared={})

    (extension,) = plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
    assert isinstance(extension, AskUserExtension)
