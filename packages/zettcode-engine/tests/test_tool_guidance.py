"""Where a tool's guidance goes: into the tool's own description, with its return type, for every agent we build."""

from __future__ import annotations

from types import SimpleNamespace

from zett_agent.extensions.tool_guidelines import ToolGuidancePlacement, ToolGuidelinesExtension
from zett_agent.tools.base import render_tool_description

from zettcode.engine.extensions.guidance import tool_guidance
from zettcode.engine.extensions.subagents import build_subagents
from zettcode.engine.tools import files


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
