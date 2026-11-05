"""The plan the shell draws: provided whatever the switch says, and handed to the agent only when the tool is on."""

from __future__ import annotations

from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path

from zett_agent.extensions.todo import TodoWriteExtension

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AgentBuild, load_plugins
from zettcode.engine.plugins import services as names
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, part_group
from zettcode.todos import TodoPlan


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


def loaded(tmp_path: Path, **changes: object):
    """Load this distribution's one plugin alone."""
    config = config_for(tmp_path, **changes)
    point = FakeEntryPoint(TodoPlan.name, TodoPlan)
    plugins = load_plugins(config, builtins=(), entry_points=[point], shared={})

    assert plugins.failures == ()
    return plugins


def test_the_plugin_is_a_part_of_the_agent_found_through_its_entry_point_group():
    found = {point.name: point for point in entry_points(group=AGENT_PART_GROUP)}

    assert found["todos"].value == "zettcode.todos.plugin:TodoPlan"
    assert part_group(found["todos"]) == AGENT_PART_GROUP
    assert TodoPlan.name == "todos"


def test_the_plan_is_reachable_even_when_the_tool_is_off(tmp_path: Path):
    """The shell asks for the plan on every turn: a switch that only turns the tool off must not take it away."""
    plugins = loaded(tmp_path)
    plan = plugins.service(names.TODOS, TodoWriteExtension)

    assert plan not in plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]


def test_the_tool_joins_the_run_when_it_is_on(tmp_path: Path):
    plugins = loaded(tmp_path, todowrite_enabled=True)
    plan = plugins.service(names.TODOS, TodoWriteExtension)

    assert plan in plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
    assert plugins.service(names.TODOS, TodoWriteExtension) is plan, "the shell draws the agent's own plan"


def test_the_switch_writes_the_key_the_configuration_already_has():
    """`/plugins` shows a row only when it has a key to write; this one sits beside the other harness switches."""
    setting = TodoPlan.setting

    assert setting is not None
    assert (setting.field, setting.path) == ("todowrite_enabled", "harness.todowrite")
    assert hasattr(ZettCodeConfig, setting.field)
