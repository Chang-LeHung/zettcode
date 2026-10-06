"""Project instructions: the workspace's AGENTS.md files reach the model.

The discovery and rendering live in ``zett-agent``'s ``AgentsMdExtension``; what
these tests pin is this application's half — that the extension is composed by
default, pointed at the workspace rather than the process directory, placed
behind the system prompt, and re-read on every request.
"""

from __future__ import annotations

from pathlib import Path

from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.extensions.agents_md import AgentsMdExtension
from zett_agent.messages import SystemMessage

from zettcode.app.agent import runtime as runtime_module
from zettcode.config import ModelConfig, ZettCodeConfig

INSTRUCTIONS = "# Development Rules\n\nRun `make check` before handing work over.\n"


def _config(tmp_path: Path, **changes) -> ZettCodeConfig:
    """Return a minimal config for a workspace, with AGENTS.md handling by default."""
    return ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        **changes,
    )


def _context() -> AgentRunContext:
    """Return a run context whose only message is the application's prompt."""
    state = AgentState()
    state._messages.append(SystemMessage(content="You are ZettCode."))
    return AgentRunContext(AgentRunConfig(session_id="s1"), state, {})


def test_the_workspace_instructions_are_composed_by_default(tmp_path):
    (extension, *rest) = runtime_module.integration_extensions(_config(tmp_path))

    assert isinstance(extension, AgentsMdExtension)
    assert extension.directory == tmp_path
    # A workspace without the file contributes nothing to the request.
    assert extension.instructions() == ""
    assert not any(isinstance(item, AgentsMdExtension) for item in rest)


def test_turning_the_instructions_off_leaves_them_out(tmp_path):
    extensions = runtime_module.integration_extensions(_config(tmp_path, agents_md_enabled=False))

    assert not any(isinstance(extension, AgentsMdExtension) for extension in extensions)


async def test_the_workspace_instructions_land_behind_the_system_prompt(tmp_path):
    """Project rules are inserted after the prompt and keep leading later guidance."""
    (tmp_path / "AGENTS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (extension, *_) = runtime_module.integration_extensions(_config(tmp_path))
    context = _context()

    await extension.on_state(context)
    context.add_message(SystemMessage(content="Tool guidance."))

    contents = [str(message.content) for message in context.state.messages]
    assert contents[0] == "You are ZettCode."
    assert str(tmp_path) in contents[1]
    assert "Run `make check` before handing work over." in contents[1]
    assert contents[2] == "Tool guidance."


async def test_an_edited_instruction_file_applies_to_the_next_request(tmp_path):
    """The file is re-read per request, so a mid-session edit is not stale."""
    path = tmp_path / "AGENTS.md"
    path.write_text(INSTRUCTIONS, encoding="utf-8")
    (extension, *_) = runtime_module.integration_extensions(_config(tmp_path))

    before = _context()
    await extension.on_state(before)
    path.write_text("# Development Rules\n\nPrefer the smallest change.\n", encoding="utf-8")
    after = _context()
    await extension.on_state(after)

    assert "make check" in before.state.messages[1].content
    assert "Prefer the smallest change." in after.state.messages[1].content
    assert "make check" not in after.state.messages[1].content


async def test_an_instruction_file_at_the_workspace_root_leads_a_nested_one(tmp_path):
    """Outermost first keeps the most specific rules closest to the dialogue."""
    nested = tmp_path / "pkg"
    nested.mkdir()
    (tmp_path / "AGENTS.md").write_text("Root rules.\n", encoding="utf-8")
    (nested / "AGENTS.md").write_text("Nested rules.\n", encoding="utf-8")
    (extension, *_) = runtime_module.integration_extensions(_config(nested))
    context = _context()

    await extension.on_state(context)

    content = context.state.messages[1].content
    assert content.index("Root rules.") < content.index("Nested rules.")
