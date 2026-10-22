"""The shell tool and the preview it builds: what comes back, when it is cut, and what stays on disk."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from zettcode.app.agent.tools.output import (
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    OMISSION,
    Preview,
    stream_preview,
    utf8_prefix,
)
from zettcode.app.agent.tools.shell import (
    DEFAULT_TIMEOUT_SECONDS,
    OUTPUT_ROOT,
    CommandFailed,
    run_command,
    shell_tool,
)

posix = pytest.mark.skipif(sys.platform == "win32", reason="drives the tool with POSIX shell commands")


@pytest.fixture
def here(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- the preview ----------------------------------------------------------------------------------------------


def test_a_short_stream_is_returned_whole(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("hello\nworld\n")

    assert stream_preview(path) == Preview("hello\nworld\n", False)


def test_a_long_stream_keeps_its_start_and_its_end_and_marks_the_middle(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("".join(f"line {n}\n" for n in range(1, 20_001)))

    preview = stream_preview(path)

    assert preview.truncated and OMISSION in preview.text
    assert preview.text.startswith("line 1\n") and preview.text.endswith("line 20000\n")
    assert len(preview.text.encode()) <= MAX_OUTPUT_BYTES
    assert len(preview.text.splitlines()) <= MAX_OUTPUT_LINES
    assert path.read_text().count("\n") == 20_000, "the file itself is never changed"


def test_a_stream_of_few_but_huge_lines_is_cut_by_bytes(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("x" * (MAX_OUTPUT_BYTES * 3))

    preview = stream_preview(path)

    assert preview.truncated and len(preview.text.encode()) <= MAX_OUTPUT_BYTES


def test_a_character_cut_in_half_at_a_window_edge_is_dropped_not_garbled(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("\u00e9" * (MAX_OUTPUT_BYTES * 2), encoding="utf-8")

    preview = stream_preview(path)

    assert "\ufffd" not in preview.text and preview.truncated


def test_a_prefix_never_ends_inside_a_character():
    assert utf8_prefix("a\u00e9b", 2) == "a"
    assert utf8_prefix("a\u00e9b", 3) == "a\u00e9"
    assert utf8_prefix("abc", 0) == ""


# -- running a command -------------------------------------------------------------------------------------------


@posix
async def test_a_command_returns_what_it_printed_and_leaves_nothing_behind(here: Path):
    assert (await run_command("echo hi", 10)).strip() == "hi"
    assert not any((here / OUTPUT_ROOT).iterdir()), "a short output keeps no files"


@posix
async def test_a_command_starts_in_the_working_directory(here: Path):
    assert (await run_command("pwd", 10)).strip() == str(here.resolve())


@posix
async def test_stderr_is_labelled_and_comes_after_stdout(here: Path):
    result = await run_command("echo out; echo err >&2", 10)

    assert result == "out\n\n[stderr]\nerr\n"


@posix
async def test_a_failing_command_is_an_error_that_carries_its_output(here: Path):
    with pytest.raises(CommandFailed) as raised:
        await run_command("echo partial; exit 3", 10)

    assert str(raised.value) == "Command exited with code 3\npartial\n"
    assert isinstance(raised.value, RuntimeError)


@posix
async def test_a_command_that_runs_out_of_time_is_stopped_with_everything_it_started(here: Path):
    marker = here / "survived"

    with pytest.raises(CommandFailed, match=r"timed out after 1 second\n"):
        await run_command(f"(sleep 1.5; touch {marker}) & echo begun; wait", 1)

    await asyncio.sleep(1.7)
    assert not marker.exists(), "the child of the command was killed with it"


@posix
async def test_a_cancelled_command_is_stopped_too(here: Path):
    marker = here / "survived"
    task = asyncio.ensure_future(run_command(f"sleep 1; touch {marker}", 30))
    await asyncio.sleep(0.3)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(1.2)
    assert not marker.exists()


@posix
async def test_a_command_that_reads_input_gets_none_instead_of_waiting_for_it(here: Path):
    assert (await run_command("cat; echo done", 5)).strip() == "done"


@posix
async def test_a_long_output_is_previewed_and_the_whole_of_it_is_kept_and_named(here: Path):
    result = await run_command("yes line | head -n 20000", 30)

    assert OMISSION.strip() in result
    note = result.rsplit("\n", 1)[1]
    assert note.startswith("... [output truncated; full streams kept at ") and note.endswith("]")
    first = note.split("kept at ")[1].split(" and ")[0]
    assert first.startswith(f"{OUTPUT_ROOT}/shell-") and first.endswith("/stdout.txt")
    assert (here / first).read_text().count("line\n") == 20_000


@posix
async def test_a_blank_command_is_refused(here: Path):
    with pytest.raises(ValueError, match="blank"):
        await run_command("  ", 5)


# -- the tool ----------------------------------------------------------------------------------------------------


def test_the_extension_that_moves_the_kept_output_names_the_folder_the_tool_makes():
    from zettcode.app.agent.extensions import tool_output

    assert tool_output.OUTPUT_ROOT == OUTPUT_ROOT


def test_the_extension_that_moves_the_kept_output_is_loaded_without_the_schema_library():
    """It is imported at start-up, so it must not be the thing that pulls the tools (and pydantic) in."""
    import subprocess

    code = (
        "import sys; import zettcode.app.agent.extensions.tool_output, zettcode.app.agent.permission; "
        "print(any(name.startswith('zettcode.app.agent.tools.') and name != 'zettcode.app.agent.tools.boundary' "
        "for name in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout

    assert out.strip() == "False"


def test_the_tool_is_typed_the_way_the_model_is_told():
    tool = shell_tool()

    assert tool.name == "bash"
    assert tool.parameters["required"] == ["command"]
    assert tool.parameters["properties"]["timeout_seconds"]["default"] == DEFAULT_TIMEOUT_SECONDS
    assert tool.parameters["properties"]["command"]["minLength"] == 1


@posix
async def test_the_tool_takes_its_arguments_by_name_and_validates_them(here: Path):
    from pydantic import ValidationError

    tool = shell_tool()

    assert (await tool.handler(command="echo hi")).strip() == "hi"
    with pytest.raises(ValidationError):
        await tool.handler(command="echo hi", timeout_seconds=301)
    with pytest.raises(ValidationError):
        await tool.handler(command="")
