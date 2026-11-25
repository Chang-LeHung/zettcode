"""A subprocess handoff belongs to one tool task, not the Python process."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys

import pytest

from zettcode.tools.shell import run_command, shell_environment, subprocess_environment


def test_nested_environment_overlays_restore_even_on_error(monkeypatch):
    monkeypatch.setenv("ZETTCODE_TEST_ENV", "process")
    assert subprocess_environment() is None
    with shell_environment({"ZETTCODE_TEST_ENV": "outer"}):
        with pytest.raises(RuntimeError), shell_environment({"ZETTCODE_TEST_ENV": None, "OTHER": "inner"}):
            assert "ZETTCODE_TEST_ENV" not in subprocess_environment()
            assert subprocess_environment()["OTHER"] == "inner"
            raise RuntimeError("failed handler")
        assert subprocess_environment()["ZETTCODE_TEST_ENV"] == "outer"
    assert subprocess_environment() is None
    assert os.environ["ZETTCODE_TEST_ENV"] == "process"


async def test_parallel_shells_have_isolated_environments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZETTCODE_TEST_ENV", "process")
    argv = [sys.executable, "-c", "import os; print(os.environ['ZETTCODE_TEST_ENV'])"]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)

    async def run(value):
        with shell_environment({"ZETTCODE_TEST_ENV": value}):
            await asyncio.sleep(0)
            return (await run_command(command, 10)).strip()

    assert await asyncio.gather(run("a"), run("b")) == ["a", "b"]
    assert os.environ["ZETTCODE_TEST_ENV"] == "process"
    assert subprocess_environment() is None


async def test_cancelled_environment_scope_leaves_no_handoff():
    entered = asyncio.Event()

    async def wait():
        with shell_environment({"HANDOFF": "cancelled"}):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(wait())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert subprocess_environment() is None
