"""Where a tool's guidance goes: into the tool's own description, with its return type, for every agent we build."""

from __future__ import annotations

from importlib.metadata import entry_points
from types import SimpleNamespace

from zett_agent.extensions.tool_guidelines import ToolGuidancePlacement, ToolGuidelinesExtension
from zett_agent.tools.base import render_tool_description

from plugin_helpers import runtime_state
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.extensions.guidance import tool_guidance
from zettcode.engine.extensions.subagents import build_subagents
from zettcode.engine.plugins import AgentBuild, load_plugins
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, PLUGIN_ENTRY_POINT_GROUP, part_group
from zettcode.engine.tools import files
from zettcode.guidance import ToolGuidance


def test_the_guidance_extension_puts_snippets_guidelines_and_returns_in_the_description():
    extension = tool_guidance()

    assert isinstance(extension, ToolGuidelinesExtension)
    assert extension.placement is ToolGuidancePlacement.DESCRIPTION
    assert extension.returns is True and extension.snippets and extension.guidelines
    assert not extension.in_system_prompt, "so the system prompt carries no tool sections"


def test_a_tool_description_carries_its_call_shapes_guidelines_and_return_type_as_one_line():
    edit = getattr(files.edit, "tool", files.edit)
    text = render_tool_description(edit, returns=True)

    assert text.startswith(edit.description) and "\n" not in text, "plain prose, no headings or bullets"
    assert 'edit(file_path="notes/plan.md"' in text, "its call shapes"
    assert "One change a call" in text, "its guidelines"
    assert 'returns {"type":"string"}' in text, "and what it returns"


def test_every_child_agent_gets_the_same_guidance():
    definitions = build_subagents(
        model=SimpleNamespace(),  # type: ignore[arg-type]
        persistence=SimpleNamespace(),  # type: ignore[arg-type]
        capabilities=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert [d.name for d in definitions] == ["explore", "reasoning", "coding"]
    for definition in definitions:
        guidance = [e for e in definition.extensions if isinstance(e, ToolGuidelinesExtension)]
        assert len(guidance) == 1, definition.name
        assert guidance[0].placement is ToolGuidancePlacement.DESCRIPTION and guidance[0].returns is True


# -- the plugin that hands it to the agent ------------------------------------------------------------


class FakeEntryPoint:
    """The slice of ``importlib.metadata.EntryPoint`` the loader touches."""

    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self.group = "zettcode.agent"
        self._target = target

    def load(self) -> object:
        return self._target


def test_the_plugin_is_a_part_of_the_agent_found_through_its_entry_point_group():
    """The distribution publishes it, so the runtime discovers it like any other part and no list names it."""
    found = {point.name: point for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)}

    assert found["tool-guidelines"].value == "zettcode.guidance.plugin:ToolGuidance"
    assert part_group(found["tool-guidelines"]) == AGENT_PART_GROUP
    assert ToolGuidance.name == "tool-guidelines"


def test_the_plugin_builds_the_guidance_extension_when_the_agent_is_built(tmp_path):
    """It is a factory, so nothing builds the extension while the first frame is still being drawn."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
    )
    plugins = load_plugins(
        config,
        builtins=(),
        entry_points=[FakeEntryPoint(ToolGuidance.name, ToolGuidance)],
        shared=runtime_state(config),
    )

    assert plugins.failures == ()
    assert plugins.agent_extensions() == (), "registered as a factory, so it is built with the agent and not before"
    built = plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
    assert [extension.name for extension in built] == ["ToolGuidelinesExtension"]
    assert isinstance(built[0], ToolGuidelinesExtension) and built[0].returns is True
