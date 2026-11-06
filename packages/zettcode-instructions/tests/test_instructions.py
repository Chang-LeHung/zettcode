"""The project instructions part: the workspace's ``AGENTS.md`` files and the switch that turns them off."""

from __future__ import annotations

from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path

from zett_agent.extensions.agents_md import AgentsMdExtension

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AgentBuild, load_plugins
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, PLUGIN_ENTRY_POINT_GROUP, part_group
from zettcode.instructions import ProjectInstructions


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


def built(tmp_path: Path, **changes: object) -> list[AgentsMdExtension]:
    """Load this distribution's one plugin alone, and build what it hands a built agent."""
    config = config_for(tmp_path, **changes)
    point = FakeEntryPoint(ProjectInstructions.name, ProjectInstructions)
    plugins = load_plugins(config, builtins=(), entry_points=[point], shared={})

    assert plugins.failures == ()
    return list(plugins.agent_extensions(AgentBuild(model=object())))  # type: ignore[arg-type]


def test_the_plugin_is_a_part_of_the_agent_found_through_its_entry_point_group():
    found = {point.name: point for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)}

    assert found["project-instructions"].value == "zettcode.instructions.plugin:ProjectInstructions"
    assert part_group(found["project-instructions"]) == AGENT_PART_GROUP
    assert ProjectInstructions.name == "project-instructions"


def test_the_instructions_are_read_from_the_workspace_when_the_setting_is_on(tmp_path: Path):
    (extension,) = built(tmp_path)

    assert (extension.name, extension.directory) == ("AgentsMdExtension", tmp_path)
    assert extension.priority == 10, "the instructions lead every other extension"


def test_turning_the_setting_off_leaves_the_agent_without_them(tmp_path: Path):
    assert built(tmp_path, agents_md_enabled=False) == []


def test_the_switch_writes_the_key_the_configuration_already_has():
    """`/plugins` shows a row only when it has a key to write, and this one is the field the runtime reads."""
    setting = ProjectInstructions.setting

    assert setting is not None
    assert (setting.field, setting.path) == ("agents_md_enabled", "agents_md.enabled")
    assert hasattr(ZettCodeConfig, setting.field)
