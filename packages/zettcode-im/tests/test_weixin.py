"""The pieces a reader sees: the code in the terminal, the background process, and the commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zettcode.im.weixin import qr
from zettcode.im.weixin.worker import Worker


class Fix:
    """A child process holding one lock file, so "running" means what it means in the real program.

    The lock is per process: taken here in the test's own process it would not be seen, because the same process
    may take it twice. A child is what a reader has.
    """

    def __init__(self, path: Path) -> None:
        import subprocess

        self.process = subprocess.Popen(  # noqa: S603 - the test's own holder
            [
                sys.executable,
                "-c",
                "import fcntl, sys, time\n"
                "handle = open(sys.argv[1], 'a+b')\n"
                "fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "print('held', flush=True)\n"
                "time.sleep(30)\n",
                str(path),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.process.stdout is not None
        assert self.process.stdout.readline().strip() == "held"

    def __enter__(self) -> Fix:
        return self

    def __exit__(self, *_: object) -> None:
        self.process.kill()
        self.process.wait()


def test_the_code_draws_two_module_rows_in_one_line_of_text() -> None:
    drawn = qr.render("https://example.com/login?code=abc")
    lines = drawn.splitlines()

    assert len(lines) > 5
    assert {len(line) for line in lines} == {len(lines[0])}, "every line is as wide as the code"
    assert set("".join(lines)) <= set(" \u2580\u2584\u2588"), "only the half blocks, so the code stays square"
    assert "\u2588" in drawn and "\u2580" in drawn and "\u2584" in drawn


def test_the_code_has_a_blank_line_around_it_and_refuses_to_draw_nothing() -> None:
    assert qr.show("x").startswith("\n") and qr.show("x").endswith("\n")
    with pytest.raises(ValueError):
        qr.render("  ")


def test_a_worker_that_is_not_there_says_so_and_has_no_pid(tmp_path: Path) -> None:
    worker = Worker(tmp_path)

    assert not worker.running() and worker.pid() is None
    assert worker.stop() == "no bridge is running"
    assert worker.tail() == ""


def test_the_pid_is_read_only_while_the_lock_says_the_process_is_there(tmp_path: Path) -> None:
    """The lock is held by another process, which is what "running" means; a pid file alone proves nothing."""
    import subprocess
    import time

    worker = Worker(tmp_path)
    worker.pid_file.write_text("424242", encoding="utf-8")

    assert worker.pid() is None, "a stale pid file is not a running bridge"

    holder = subprocess.Popen(  # noqa: S603 - this test's own holder, with the file it is given
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time\n"
            "handle = open(sys.argv[1], 'a+b')\n"
            "fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "print('held', flush=True)\n"
            "time.sleep(30)\n",
            str(worker.lock),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        for _ in range(100):
            if worker.running():
                break
            time.sleep(0.02)
        assert worker.running() and worker.pid() == 424242
    finally:
        holder.kill()
        holder.wait()


def test_a_process_that_dies_before_it_is_ready_is_reported_with_its_log(tmp_path: Path) -> None:
    worker = Worker(tmp_path)

    with pytest.raises(RuntimeError) as failed:
        worker.start([sys.executable, "-c", "import sys; print('no token'); sys.exit(4)"], timeout=20)

    assert "4" in str(failed.value) or "no token" in str(failed.value)
    assert "no token" in worker.tail(), "the log keeps what the process said before it went"


def test_a_second_start_refuses_while_one_is_running(tmp_path: Path) -> None:
    worker = Worker(tmp_path)
    with Fix(worker.lock):
        with pytest.raises(RuntimeError, match="already running"):
            worker.start([sys.executable, "-c", "pass"], timeout=5)


def test_the_commands_parse_the_settings_a_login_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from zettcode.im.weixin.cli import build_parser, main

    parsed = build_parser().parse_args(["login", "--state-dir", str(tmp_path), "--allow", "u1", "--allow", "u2"])
    assert parsed.permission == "safe", "a program that asks nobody does not hand out a full shell"
    assert parsed.allow == ["u1", "u2"]
    assert build_parser().parse_args([]).command is None, "no command is the login"

    assert main(["status", "--state-dir", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    assert "not running" in said and "nobody yet" in said and "not logged in" in said

    assert main(["logs", "--state-dir", str(tmp_path)]) == 0
    assert "nothing has been written" in capsys.readouterr().out


def test_status_says_what_the_state_holds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from zettcode.im.state import BridgeState
    from zettcode.im.weixin.cli import main

    state = BridgeState.load(tmp_path / "state.json")
    state.credentials = {"bot_token": "t"}
    state.workspace = "/w"
    state.session_id = "01a1"
    state.allow_all = True
    state.save()

    assert main(["status", "--state-dir", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    assert "logged in" in said and "/w" in said and "01a1" in said and "everyone" in said
