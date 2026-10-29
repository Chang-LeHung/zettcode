"""The file tools: written in this repository, so what each one does is pinned here.

One reader for text and pictures, no ``view_image``, no ``delete_file``; a text-only reader for a model that cannot take
a picture; search; and writes that are whole or not at all.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from zett_agent.messages import ImageContent, TextContent
from zett_agent.tools.base import AgentTool

from zettcode.engine.dialogue.side import READ_ONLY_TOOLS
from zettcode.engine.extensions.files import CodingBundle, FileTools, file_tools
from zettcode.engine.tools.files import edit, glob, grep, read, read_file, write_file
from zettcode.engine.tools.output import MAX_OUTPUT_BYTES
from zettcode.engine.tools.workspace import MAX_FILE_BYTES


def _png(path: Path) -> Path:
    """The smallest valid PNG: one white pixel."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    path.write_bytes(data + chunk(b"IEND", b""))
    return path


@pytest.fixture
def here(tmp_path: Path, monkeypatch) -> Path:
    """A working directory with a few files in it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("class Agent:\n    pass\n")
    (tmp_path / "src" / "util.py").write_text("def agent():\n    return 1\n")
    return tmp_path


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
    assert {tool.handler.__module__ for tool in tools[:6]} == {"zettcode.engine.tools.files"}, "defined here"
    assert CodingBundle().tools[-1].handler.__module__ == "zettcode.engine.tools.shell"


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
    assert shell["timeout_seconds"]["maximum"] == 300 and "work_dir" in shell


async def test_a_file_is_removed_by_the_shell_like_any_command_and_the_prompt_says_so(tmp_path: Path):
    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine import core as runtime_module

    prompt = runtime_module.build_system_prompt(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    )
    flat = " ".join(prompt.split())

    assert "There is no delete tool: remove a file with rm in the shell" in flat
    assert "delete_file" not in flat and "view_image" not in flat


# -- read and read_file ------------------------------------------------------------------------------------------


async def test_read_returns_text_as_a_range_and_a_picture_as_an_image(here: Path):
    picture = _png(here / "dot.png")

    text = await read.handler(file_path="a.txt", offset=2, limit=1)
    image = await read.handler(file_path=str(picture))

    assert text.startswith("two\n") and "one" not in text.split("...")[0]
    assert isinstance(image, list) and any(isinstance(part, ImageContent) for part in image)
    assert any(isinstance(part, TextContent) and "image/png" in part.text for part in image)


async def test_a_picture_is_recognised_by_its_bytes_and_not_by_its_name(here: Path):
    _png(here / "notes.txt")

    image = await read.handler(file_path="notes.txt")

    assert isinstance(image, list) and image[1].source.media_type == "image/png"


async def test_the_text_reader_a_text_only_model_gets_never_returns_a_picture(here: Path):
    picture = _png(here / "dot.png")

    assert "one" in await read_file.handler(file_path="a.txt")
    try:
        result = await read_file.handler(file_path=str(picture))
    except Exception:
        return  # refusing a file that is not text is as good as not returning it
    assert not (isinstance(result, list) and any(isinstance(part, ImageContent) for part in result))


async def test_a_range_says_how_to_go_on_when_there_is_more(here: Path):
    (here / "long.txt").write_text("".join(f"line {n}\n" for n in range(1, 11)))

    text = await read_file.handler(file_path="long.txt", offset=3, limit=2)

    assert text == "line 3\nline 4\n\n... [more lines; continue with offset=5]"


async def test_a_line_too_long_to_return_is_cut_and_the_reader_is_sent_to_the_shell(here: Path):
    (here / "wide.txt").write_text("x" * (MAX_OUTPUT_BYTES + 100) + "\nnext\n")

    text = await read_file.handler(file_path="wide.txt")

    assert "line truncated" in text and "read it with the shell" in text
    assert "start_column" not in text, "the reader has no column to resume from"
    assert len(text.encode("utf-8")) <= MAX_OUTPUT_BYTES + 200


async def test_a_long_line_after_a_short_one_is_already_known_to_be_too_long(here: Path):
    """The cut is measured, not assumed: the first answer says the shell is the way, and costs no round trip."""
    (here / "late.txt").write_text("short first line\n" + "x" * (MAX_OUTPUT_BYTES * 4) + "\n")

    text = await read_file.handler(file_path="late.txt")

    assert "line truncated; line 2 is longer than" in text and "read it with the shell" in text
    assert "offset=" not in text, "there is no offset that would fit this line"


async def test_an_ordinary_line_cut_by_a_full_budget_is_reached_again_with_its_offset(here: Path):
    """A thirty-kilobyte line fits a call; the one before it used the budget up, so the next call starts there."""
    (here / "mixed.txt").write_text("".join("a" * 39 + "\n" for _ in range(1000)) + "z" * 30_000 + "\n")

    text = await read_file.handler(file_path="mixed.txt", limit=2000)
    start = int(text.rsplit("offset=", 1)[1].rstrip("]"))
    rest = await read_file.handler(file_path="mixed.txt", offset=start, limit=2000)

    assert "output truncated; continue with offset=1001" in text
    assert rest.startswith("zzz") and "output truncated" not in rest, "one more call carries the whole line"


async def test_a_budget_used_up_by_earlier_lines_says_where_to_go_on_not_that_a_line_is_too_long(here: Path):
    """The line a full budget cuts is an ordinary line: `offset` is the way to the rest of the file."""
    (here / "many.txt").write_text("".join("y" * 38 + "\n" for _ in range(2000)))

    text = await read_file.handler(file_path="many.txt", limit=2000)

    assert "output truncated; continue with offset=" in text
    assert "longer than" not in text and "read it with the shell" not in text
    start = int(text.rsplit("offset=", 1)[1].rstrip("]"))
    assert start > 1 and text.count("\n") < 2000, "several lines came back before the cut"
    assert len(text.encode("utf-8")) <= MAX_OUTPUT_BYTES + 200


async def test_a_missing_file_and_a_binary_file_are_refused_with_the_path_as_given(here: Path):
    (here / "blob.bin").write_bytes(b"\xff\xfe\x00\x81" * 50)

    with pytest.raises(ValueError, match="File does not exist: nope.txt"):
        await read.handler(file_path="nope.txt")
    with pytest.raises(ValueError, match="File is not UTF-8 text: blob.bin"):
        await read.handler(file_path="blob.bin")


async def test_an_absolute_path_is_taken_as_it_is_and_so_is_one_outside_the_directory(here: Path, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "far.txt"
    elsewhere.write_text("faraway\n")

    assert "faraway" in await read.handler(file_path=str(elsewhere))


# -- glob and grep -----------------------------------------------------------------------------------------------


async def test_glob_lists_sorted_paths_in_the_style_of_the_pattern(here: Path):
    assert await glob.handler(pattern="src/*.py") == "src/app.py\nsrc/util.py"
    absolute = await glob.handler(pattern=str(here / "src" / "*.py"))
    assert absolute.splitlines() == [str(here / "src" / "app.py"), str(here / "src" / "util.py")] or all(
        line.endswith(".py") and Path(line).is_absolute() for line in absolute.splitlines()
    )
    assert await glob.handler(pattern="nothing/*") == ""


async def test_glob_stops_at_the_limit_and_says_so(here: Path):
    result = await glob.handler(pattern="src/*.py", max_results=1)

    assert result == "src/app.py\n... [truncated; narrow the pattern or increase max_results]"


async def test_grep_reports_path_line_and_text_and_skips_what_is_not_text(here: Path):
    (here / "src" / "blob.py").write_bytes(b"\xff\xfeAgent\x00")

    result = await grep.handler(pattern="Agent", file_pattern="src/*.py")

    assert result == "src/app.py:1: class Agent:"


async def test_grep_can_ignore_case_and_says_when_the_expression_is_wrong(here: Path):
    both = await grep.handler(pattern="agent", file_pattern="src/*.py", case_sensitive=False)

    assert both.splitlines() == ["src/app.py:1: class Agent:", "src/util.py:1: def agent():"]
    with pytest.raises(ValueError, match="Invalid regular expression"):
        await grep.handler(pattern="(", file_pattern="src/*.py")


async def test_grep_stops_at_the_limit_and_says_so(here: Path):
    result = await grep.handler(pattern="a", file_pattern="src/*.py", max_results=2)

    assert len(result.splitlines()) == 3 and result.endswith("narrow the search or increase max_results]")


async def test_grep_cuts_a_very_long_matching_line_around_the_match(here: Path):
    (here / "wide.txt").write_text("a" * 5000 + "NEEDLE" + "b" * 5000 + "\n")

    result = await grep.handler(pattern="NEEDLE", file_pattern="wide.txt")

    assert "NEEDLE" in result and len(result.encode()) < 2100


async def test_a_file_over_the_size_limit_is_left_out_of_a_search(here: Path):
    (here / "huge.txt").write_text("needle " + "x" * MAX_FILE_BYTES)

    assert await grep.handler(pattern="needle", file_pattern="huge.txt") == ""


# -- write_file and edit -----------------------------------------------------------------------------------------


async def test_write_file_creates_then_replaces_and_says_which(here: Path):
    assert await write_file.handler(file_path="new/dir/n.txt", content="hi\n") == "Created new/dir/n.txt"
    assert (here / "new" / "dir" / "n.txt").read_text() == "hi\n"

    assert await write_file.handler(file_path="new/dir/n.txt", content="bye\n") == "Wrote new/dir/n.txt"
    assert (here / "new" / "dir" / "n.txt").read_text() == "bye\n"


async def test_write_file_can_be_told_not_to_replace_and_never_writes_over_a_directory(here: Path):
    with pytest.raises(ValueError, match="File already exists: a.txt"):
        await write_file.handler(file_path="a.txt", content="x", overwrite=False)
    with pytest.raises(ValueError, match="Path is not a file: src"):
        await write_file.handler(file_path="src", content="x")
    assert (here / "a.txt").read_text() == "one\ntwo\nthree\n"


async def test_a_write_leaves_no_stray_file_and_refuses_what_is_too_big(here: Path):
    with pytest.raises(ValueError, match="byte limit"):
        await write_file.handler(file_path="big.txt", content="x" * (MAX_FILE_BYTES + 1))

    assert not (here / "big.txt").exists()
    assert sorted(path.name for path in here.iterdir()) == ["a.txt", "src"]


async def test_edit_replaces_exact_text_once_and_says_how_many(here: Path):
    result = await edit.handler(file_path="a.txt", old_string="two", new_string="2")

    assert result == "Replaced 1 occurrence in a.txt" and (here / "a.txt").read_text() == "one\n2\nthree\n"


async def test_one_edit_changes_one_place_so_the_next_change_is_another_call(here: Path):
    first = await edit.handler(file_path="a.txt", old_string="one", new_string="1")
    second = await edit.handler(file_path="a.txt", old_string="two", new_string="2")

    assert (first, second) == ("Replaced 1 occurrence in a.txt", "Replaced 1 occurrence in a.txt")
    assert (here / "a.txt").read_text() == "1\n2\nthree\n"


async def test_edit_replace_all_counts_every_match(here: Path):
    (here / "r.txt").write_text("x x x\n")

    result = await edit.handler(file_path="r.txt", old_string="x", new_string="y", replace_all=True)

    assert result == "Replaced 3 occurrences in r.txt" and (here / "r.txt").read_text() == "y y y\n"


async def test_an_edit_with_an_empty_new_string_deletes_the_match(here: Path):
    assert await edit.handler(file_path="a.txt", old_string="two\n", new_string="") == "Replaced 1 occurrence in a.txt"
    assert (here / "a.txt").read_text() == "one\nthree\n"


async def test_edit_says_what_is_wrong_with_old_string(here: Path):
    (here / "dup.txt").write_text("a\na\n")
    (here / "ind.txt").write_text("if x:\n    return 1\n")

    with pytest.raises(ValueError, match=r"not unique; found 2 matches"):
        await edit.handler(file_path="dup.txt", old_string="a", new_string="b")
    with pytest.raises(ValueError, match="differs only in whitespace or indentation"):
        await edit.handler(file_path="ind.txt", old_string="if x:\n  return 1", new_string="x")
    with pytest.raises(ValueError, match="File does not exist: ghost.txt"):
        await edit.handler(file_path="ghost.txt", old_string="a", new_string="b")
    assert (here / "dup.txt").read_text() == "a\na\n", "a failed edit writes nothing"


async def test_edit_refuses_an_edit_with_nothing_to_find_and_a_call_with_a_field_it_does_not_know(here: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await edit.handler(file_path="a.txt", old_string="", new_string="x")
    with pytest.raises(ValidationError):
        await edit.handler(file_path="a.txt", old_string="one", new_string="1", replace=True)
    with pytest.raises(ValidationError):
        await edit.handler(file_path="a.txt", new_string="1")


async def test_a_call_with_an_argument_the_tool_does_not_have_is_refused(here: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await read.handler(file_path="a.txt", mode="rb")
    with pytest.raises(ValidationError):
        await read.handler(file_path="a.txt", limit=5000)
