"""Which tools the engine offers, and the schemas the model is given for them.

The tools themselves are the leaf distribution: their own behaviour is `packages/zettcode-tools/tests/test_file_tools.py`.
Here are the bundle composition, the two readers a side question may use, and the limits a schema carries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.tools.base import AgentTool

from zettcode.engine.dialogue.side import READ_ONLY_TOOLS
from zettcode.engine.extensions.files import CodingBundle, FileTools, file_tools
from zettcode.tools.files import edit, glob, grep, read, read_file, write_file

# -- what is offered ---------------------------------------------------------------------------------------------


def test_the_bundle_offers_read_write_edit_and_the_shell_and_no_search_tool():
    """The main agent has a shell, so it searches with `rg`, `grep` and `find`, not with tools of its own."""
    names = [tool.name for tool in CodingBundle().tools]

    assert names == ["read", "write_file", "edit", "bash"]
    assert not {"glob", "grep", "view_image", "delete_file", "read_file"} & set(names)


def test_a_subagent_has_no_shell_so_it_keeps_the_search_tools():
    assert [tool.name for tool in FileTools(read_only=True).tools] == ["read", "glob", "grep"]
    assert [tool.name for tool in FileTools(read_only=False).tools] == ["read", "glob", "grep", "write_file", "edit"]
    assert [tool.name for tool in file_tools(read_only=True)] == ["read", "glob", "grep"]
    assert [tool.name for tool in file_tools(read_only=True, search=False)] == ["read"]
    assert [tool.name for tool in FileTools(read_only=False, search=False).tools] == ["read", "write_file", "edit"]


def test_every_tool_is_one_of_ours_and_is_typed_as_one():
    tools = (read, read_file, glob, grep, write_file, edit, *CodingBundle().tools)

    assert all(isinstance(tool, AgentTool) for tool in tools)
    assert {tool.handler.__module__ for tool in tools[:6]} == {"zettcode.tools.files"}, "defined here"
    assert CodingBundle().tools[-1].handler.__module__ == "zettcode.tools.shell"


def test_every_bundled_tool_says_what_it_returns():
    """The model gets a sentence about the result, not only its JSON shape, because ``returns=True`` is on."""
    for tool in (read, read_file, glob, grep, write_file, edit, *CodingBundle().tools):
        assert tool.returns_description, tool.name


def test_reading_is_one_tool_and_it_does_not_send_the_model_to_one_that_is_gone():
    assert not any("view_image" in rule for rule in read.guidelines)
    assert any("image" in rule for rule in read.guidelines), "it still says it reads pictures"
    assert read.name == "read" and read_file.name == "read_file"


def test_no_guideline_the_main_agent_reads_names_a_tool_it_does_not_have():
    """It has `read` or `read_file`, never both, and no `glob`, `grep`, `view_image` or `delete_file`."""
    rules = [rule for tool in CodingBundle().tools for rule in tool.guidelines]

    assert not any(name in rule for rule in rules for name in ("view_image", "delete_file", "glob"))
    assert not any("with read_file" in rule or "grep tool" in rule or "grep, and" in rule for rule in rules)
    shell = CodingBundle().tools[-1]
    assert any("rg or grep" in rule for rule in shell.guidelines), "it is told how to search"


def test_a_side_question_may_read_with_either_reader():
    assert {"read", "read_file", "glob", "grep"} <= READ_ONLY_TOOLS
    assert "view_image" not in READ_ONLY_TOOLS and "write_file" not in READ_ONLY_TOOLS


@pytest.mark.parametrize("name", ["read", "write_file", "edit", "bash"])
def test_every_tool_the_bundle_offers_has_a_schema_free_of_references(name: str):
    """Some endpoints reject a schema that points at another part of itself; the schema is written out longhand."""
    tool = next(tool for tool in CodingBundle().tools if tool.name == name)

    assert '"$ref"' not in json.dumps(tool.parameters) and '"$defs"' not in json.dumps(tool.parameters)


def test_the_search_tools_a_subagent_has_keep_their_schemas_free_of_references_too():
    for tool in (glob, grep):
        assert '"$ref"' not in json.dumps(tool.parameters) and '"$defs"' not in json.dumps(tool.parameters)


def test_the_limits_in_a_schema_are_the_ones_the_tools_enforce():
    props = read.parameters["properties"]

    assert props["limit"]["maximum"] == 2000 and props["offset"]["minimum"] == 1
    assert "start_column" not in props, "a read has one range, not a range and a column"
    assert grep.parameters["properties"]["max_results"]["maximum"] == 5000
    shell = CodingBundle().tools[-1].parameters["properties"]
    assert (
        shell["timeout_seconds"]["maximum"] == 600 and shell["timeout_seconds"]["default"] == 60 and "work_dir" in shell
    )


async def test_a_file_is_removed_by_the_shell_like_any_command_and_the_prompt_says_so(tmp_path: Path):
    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine import core as runtime_module

    prompt = runtime_module.build_system_prompt(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    )
    flat = " ".join(prompt.split())

    assert "There is no delete tool: remove a file with rm in the shell" in flat
    assert "delete_file" not in flat and "view_image" not in flat
