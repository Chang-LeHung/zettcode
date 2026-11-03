"""Recognising and ending a process: what is ours, what is not, and what is left alone."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from zettcode import processes
from zettcode.broker import process

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="ps and POSIX signals")


@pytest.fixture
def runs():
    """Start processes whose command line is chosen, and end them afterwards."""
    started: list[subprocess.Popen] = []

    def start(*arguments: str) -> subprocess.Popen:
        child = subprocess.Popen([sys.executable, *arguments], stdout=subprocess.PIPE, text=True)
        started.append(child)
        return child

    yield start
    for child in started:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_the_command_line_of_a_running_process_is_read_and_a_gone_one_has_none(runs):
    child = runs("-c", "import time; time.sleep(30)")

    text = processes.command_line(child.pid)
    assert text is not None and "time.sleep(30)" in text

    child.kill()
    child.wait()
    assert processes.command_line(child.pid) is None


@pytest.mark.parametrize("pid", [0, -1, os.getpid()])
def test_this_process_and_nonsense_are_never_looked_up(pid):
    assert processes.command_line(pid) is None


def test_a_process_is_recognised_by_the_module_it_runs_as(runs, tmp_path: Path):
    (tmp_path / "toymod.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, "-m", "toymod"], cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)}
    )
    try:
        deadline = time.monotonic() + 5
        while processes.command_line(child.pid) is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert processes.runs_module(child.pid, "toymod") is True
        assert processes.runs_module(child.pid, "toy") is False, "a module that merely starts the same way is not it"
        assert processes.runs_module(child.pid, "toymod.sub") is False
        assert processes.runs_module(child.pid, "other") is False
    finally:
        child.kill()
        child.wait()


def test_a_module_name_is_matched_whole_not_as_the_start_of_another(runs, tmp_path: Path):
    (tmp_path / "toymodule.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, "-m", "toymodule"], cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)}
    )
    try:
        assert processes.runs_module(child.pid, "toymod") is False
        assert processes.runs_module(child.pid, "toymodule") is True
    finally:
        child.kill()
        child.wait()


def test_a_program_that_only_mentions_the_module_in_an_argument_is_not_that_module(runs):
    """``python -c ... -m toymod`` is a different program with a flag that happens to read the same."""
    child = runs("-c", "import time; time.sleep(30)", "-m", "toymod")

    assert processes.runs_module(child.pid, "toymod") is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/venv/bin/python3 -m zettcode.broker", True),
        ("/venv/bin/python -m zettcode.broker", True),
        ("/usr/bin/python3.14 -m zettcode.broker", True),
        ("/venv/bin/python3 -u -m zettcode.broker", True),
        ("/Users/Foo Bar/proj/.venv/bin/python3 -m zettcode.broker", True),
        ('"C:\\Python314\\python.exe" -m zettcode.broker', True),
        ("C:\\Python314\\python.exe -m zettcode.broker", True),
        ("/venv/bin/python3 -m zettcode.broker --flag", True),
        ("/venv/bin/python3 -m zettcode.brokerage", False),
        ("/venv/bin/python3 -m zettcode", False),
        ("/venv/bin/python3 -m zettcode.broker.sub", False),
        ("/venv/bin/python3 -c import x -m zettcode.broker", False),
        ("/venv/bin/python3 script.py -m zettcode.broker", False),
        ("/venv/bin/python3 -m other -m zettcode.broker", False),
        ("vim -m zettcode.broker", False),
        ("/bin/sh -c python3 -m zettcode.broker", False),
        ("python3", False),
        ("", False),
    ],
)
def test_which_command_lines_are_the_module_and_which_only_resemble_it(text, expected):
    assert processes.is_module_command(text, "zettcode.broker") is expected


def test_a_process_that_is_not_recognised_is_not_touched_even_when_it_holds_the_lock(runs):
    child = runs("-c", "import time; time.sleep(30)")

    gone = process.end(child.pid, "toymod", released=lambda: False, grace=0.1, force=0.1)

    assert gone is False and child.poll() is None


def test_nothing_is_ended_when_the_lock_is_already_free(runs):
    child = runs("-c", "import time; time.sleep(30)")

    assert process.end(child.pid, "toymod", released=lambda: True) is True
    assert child.poll() is None


def test_a_process_that_is_gone_is_just_released(runs):
    child = runs("-c", "pass")
    child.wait()

    assert process.end(child.pid, "toymod", released=lambda: False, grace=0.1, force=0.1) is False


def test_a_recognised_process_is_asked_to_stop_and_the_answer_is_whether_the_lock_was_let_go(runs, tmp_path: Path):
    (tmp_path / "politemod.py").write_text(
        "import signal, sys, time\nsignal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
        "print('up', flush=True)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [sys.executable, "-m", "politemod"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stdout.readline().strip() == "up"
    try:
        gone = process.end(child.pid, "politemod", released=lambda: child.poll() is not None, grace=5.0, force=1.0)

        assert gone is True and child.returncode == 0, "it left by the polite way, not by being killed"
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_a_process_that_will_not_let_go_even_when_killed_is_reported_as_still_there(runs):
    child = runs("-c", "import time; time.sleep(60)")

    assert process.end(child.pid, "toymod", released=lambda: False, grace=0.1, force=0.1) is False


@pytest.mark.skipif(sys.platform == "win32", reason="ps")
def test_a_long_command_line_is_read_whole_not_cut_at_the_width_of_a_terminal(runs):
    """``ps`` cuts what it prints at 80 columns when nothing is a terminal, which would hide ``-m zettcode.broker``
    behind a long interpreter path and make an older broker look like some other program."""
    padding = "x" * 300
    child = runs("-c", f"import time; time.sleep(30)  # {padding}")

    text = processes.command_line(child.pid)

    assert text is not None and text.endswith(padding)
