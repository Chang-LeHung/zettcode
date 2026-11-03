"""`/bash`: the full-screen command line, opened from the shell and driven by keys."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from test_zettcode_app import _harness, build_app
from zettcode.app.commandline import CommandRunner, ShellLauncher
from zettcode.app.ui.widgets import BashPage


class PythonLauncher(ShellLauncher):
    """Runs the command text as Python, so the test means the same on every platform."""

    name = "python"

    def argv(self, command: str) -> list[str]:
        return [sys.executable, "-c", command]


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch):
    """Run in a directory of the test's own, with a history file of its own and no real shell."""
    monkeypatch.setattr("zettcode.app.plugins.builtin_commands.DEFAULT_COMMAND_HISTORY", tmp_path / "command_history")
    monkeypatch.setattr("zettcode.app.commandline.CommandRunner", lambda cwd: CommandRunner(tmp_path, PythonLauncher()))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


async def until(condition: Callable[[], bool], seconds: float = 20.0) -> None:
    for _ in range(int(seconds / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("waited for something that did not happen")


async def open_page(command: str = "/bash"):
    app = build_app()
    harness = _harness(app)
    harness.write(command)
    harness.press("enter")
    await asyncio.wait_for(app.task, 5.0)
    page = app.app.screens.top.widget
    assert isinstance(page, BashPage), f"the top screen is {type(page).__name__}"
    return app, harness, page


def type_command(harness, text: str) -> None:
    harness.write(text)
    harness.press("enter")


async def test_bash_is_a_command_the_help_and_the_menu_know():
    app = build_app()

    assert "/bash" in {command.name for command in app.commands}
    assert any(command.name == "/bash" and "shell" in command.description for command in app.commands)


async def test_bash_opens_a_full_screen_page_over_the_conversation():
    app, harness, page = await open_page()

    text = harness.render().text

    assert page.rect.width == harness.width and page.rect.height == harness.height
    assert "Shell (python)" in text and "enter run" in text
    assert harness.focused_widget() is page.input


async def test_a_command_given_to_bash_runs_at_once_and_its_output_is_on_the_page():
    app, harness, page = await open_page("/bash print('hello from bash')")

    await until(lambda: not page.running)
    text = harness.render().text

    assert "hello from bash" in text and "exit 0" in text
    assert "$ print(" in text, "the command is echoed above what it printed"


async def test_a_command_typed_on_the_page_runs_and_the_next_one_can_follow():
    app, harness, page = await open_page()

    type_command(harness, "print(1 + 1)")
    await until(lambda: not page.running and "2" in page.buffer.text)
    type_command(harness, "print('second')")
    await until(lambda: not page.running and "second" in page.buffer.text)

    assert "print(1 + 1)" in page.buffer.text and "second" in harness.render().text


async def test_the_output_keeps_its_colours():
    app, harness, page = await open_page()

    type_command(harness, "print('\\x1b[31mred\\x1b[0m plain')")
    await until(lambda: not page.running)
    canvas = app.app.render()
    row = next(y for y, cells in enumerate(canvas.cells) if "red plain" in "".join(cell.character for cell in cells))
    red = canvas.cells[row][2].style.foreground
    plain = canvas.cells[row][6].style.foreground

    assert red == "#d0504e" and plain == app.app.theme.text


async def test_the_prompt_of_a_running_command_is_refused_and_ctrl_c_stops_it_without_closing_the_page():
    app, harness, page = await open_page()
    type_command(harness, "import time; print('rea' + 'dy', flush=True); time.sleep(60)")
    await until(lambda: "ready" in page.buffer.text)
    assert page.running

    harness.press("ctrl_c")
    await until(lambda: not page.running)

    assert app.app.screens.top.widget is page, "Ctrl-C stopped the command and left the page open"
    assert "stopped" in harness.render().text


async def test_ctrl_c_on_an_idle_page_closes_it_like_any_other_page():
    app, harness, page = await open_page()

    harness.press("ctrl_c")

    assert app.app.screens.top.widget is not page


async def test_escape_stops_a_running_command_first_and_closes_the_page_second():
    app, harness, page = await open_page()
    type_command(harness, "import time; print('rea' + 'dy', flush=True); time.sleep(60)")
    await until(lambda: "ready" in page.buffer.text)

    harness.press("escape")
    await until(lambda: not page.running)
    assert app.app.screens.top.widget is page
    harness.press("escape")

    assert app.app.screens.top.widget is not page


async def test_closing_the_page_while_a_command_runs_stops_the_command(tmp_path: Path):
    """The command writes a heartbeat; once the page is closed the heartbeat must stop.

    Not a probe of the process id: on Windows `os.kill(pid, 0)` is a Ctrl-C sent to the console.
    """
    beat = tmp_path / "beat"
    script = tmp_path / "heartbeat.py"
    script.write_text(
        "import pathlib, time\n"
        "print('rea' + 'dy', flush=True)\n"
        f"beat = pathlib.Path({str(beat)!r})\n"
        "while True:\n"
        "    beat.write_text(str(time.time()))\n"
        "    time.sleep(0.1)\n",
        encoding="utf-8",
    )
    app, harness, page = await open_page()
    type_command(harness, f"import runpy; runpy.run_path({str(script)!r})")
    await until(lambda: "ready" in page.buffer.text)
    await until(beat.exists)

    app.close_page()

    for _ in range(60):
        before = beat.read_text()
        await asyncio.sleep(0.5)
        if beat.read_text() == before:
            return
    pytest.fail("the command outlived the page that showed it")


async def test_the_words_clear_and_exit_belong_to_the_page():
    app, harness, page = await open_page("/bash print('noise')")
    await until(lambda: not page.running)

    type_command(harness, "clear")
    assert "noise" not in harness.render().text and page.running is False

    type_command(harness, "exit")
    assert app.app.screens.top.widget is not page


async def test_cd_moves_the_heading_and_the_next_command(tmp_path: Path):
    (tmp_path / "inner").mkdir()
    app, harness, page = await open_page()

    type_command(harness, "cd inner")
    await until(lambda: not page.running and page.location.endswith("inner"))
    type_command(harness, "import os; print(os.path.basename(os.getcwd()))")
    await until(lambda: not page.running and page.buffer.text.rstrip().endswith("inner"))

    assert "inner" in harness.render().text.splitlines()[0]


async def test_tab_completes_a_file_of_the_directory_and_colours_a_directory_apart(tmp_path: Path):
    (tmp_path / "alpha_dir").mkdir()
    (tmp_path / "alpha.txt").write_text("")
    app, harness, page = await open_page()

    harness.write("cat al")
    harness.press("tab")
    canvas = app.app.render()
    row = next(y for y, cells in enumerate(canvas.cells) if "alpha_dir/" in "".join(cell.character for cell in cells))
    text = "".join(cell.character for cell in canvas.cells[row])

    assert page.input.text == "cat alpha_dir/", "directories first"
    assert canvas.cells[row][text.index("alpha.txt")].style.foreground == app.app.theme.subtle
    assert canvas.cells[row][text.index("alpha_dir/") + 1].style.foreground != app.app.theme.subtle


async def test_what_was_typed_is_kept_for_the_next_time(tmp_path: Path):
    app, harness, page = await open_page()
    type_command(harness, "print('remember me')")
    await until(lambda: not page.running)
    harness.press("escape")

    app2, harness2, page2 = await open_page()
    harness2.press("up")

    assert page2.input.text == "print('remember me')"
    assert "remember me" in (tmp_path / "command_history").read_text(encoding="utf-8")


async def test_the_page_opens_beside_a_running_request():
    from zett_agent.events import AgentEvent, AgentEventType

    app = build_app([AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="working")], block=True)
    harness = _harness(app)
    harness.write("do something")
    harness.press("enter")
    await asyncio.sleep(0.1)
    assert app.busy

    harness.write("/bash")
    harness.press("enter")
    await until(lambda: isinstance(app.app.screens.top.widget, BashPage), 5)

    assert app.busy, "the request carries on behind the page"
