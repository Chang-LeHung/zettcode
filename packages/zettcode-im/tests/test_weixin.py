"""The pieces a reader sees: the code in the terminal, the background process, and the commands."""

from __future__ import annotations

import asyncio
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
                # The repository's own lock, which is the one `Worker.running` asks about and works on every platform.
                "import sys, time\n"
                "from pathlib import Path\n"
                "from zettcode.filelock import SingletonLock\n"
                "lock = SingletonLock(Path(sys.argv[1]))\n"
                "assert lock.acquire()\n"
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
    import time

    worker = Worker(tmp_path)
    worker.pid_file.write_text("424242", encoding="utf-8")

    assert worker.pid() is None, "a stale pid file is not a running bridge"

    with Fix(worker.lock):
        for _ in range(100):
            if worker.running():
                break
            time.sleep(0.02)
        assert worker.running() and worker.pid() == 424242


def test_a_process_that_dies_before_it_is_ready_is_reported_with_its_log(tmp_path: Path) -> None:
    worker = Worker(tmp_path)

    with pytest.raises(RuntimeError) as failed:
        worker.start([sys.executable, "-c", "import sys; print('no token'); sys.exit(4)"], timeout=20)

    assert "no token" in str(failed.value), "the log is what the reader is given"
    assert "no token" in worker.tail(), "the log keeps what the process said before it went"


def test_a_second_start_refuses_while_one_is_running(tmp_path: Path) -> None:
    worker = Worker(tmp_path)
    with Fix(worker.lock):
        with pytest.raises(RuntimeError, match="already running"):
            worker.start([sys.executable, "-c", "pass"], timeout=5)


def test_the_commands_parse_the_settings_a_login_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from zettcode.im.weixin.cli import build_parser, main

    parsed = build_parser().parse_args(["login", "--state-dir", str(tmp_path), "--allow", "u1", "--allow", "u2"])
    assert parsed.permission is None, "not given means the stored one, or safe on a first login"
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


def test_stopping_a_running_bridge_signals_it_and_says_so(tmp_path: Path) -> None:
    """The pid is only trusted while the lock is held; the stop is a signal and a wait, not a promise."""
    import time

    worker = Worker(tmp_path)
    with Fix(worker.lock) as held:
        worker.pid_file.write_text(str(held.process.pid), encoding="utf-8")
        for _ in range(100):
            if worker.running():
                break
            time.sleep(0.02)

        said = worker.stop(timeout=10)

    assert said == f"stopped the bridge (pid {held.process.pid})"
    assert not worker.running()


def test_the_module_runs_itself_the_way_the_background_process_starts_it(tmp_path: Path) -> None:
    """The worker starts `python -m zettcode.im.weixin.cli run`, not the console script: the module must act.

    Without the `__main__` guard the child imports the module, does nothing and exits 0 — the log holds one line
    and the bridge that was just announced as running never existed.
    """
    import subprocess

    finished = subprocess.run(  # noqa: S603 - this program's own module
        [sys.executable, "-m", "zettcode.im.weixin.cli", "status", "--state-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert finished.returncode == 0, finished.stderr
    assert "bridge:    not running" in finished.stdout, finished.stdout + finished.stderr


class ScanWorker:
    """What a login does to the background process, in order."""

    calls: list[str] = []
    running_now = False

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.log = directory / "worker.log"

    def running(self) -> bool:
        return self.running_now

    def stop(self, **_kwargs) -> str:
        ScanWorker.calls.append("stop")
        ScanWorker.running_now = False
        return "stopped the bridge (pid 1)"

    def start(self, argv, **_kwargs) -> int:
        ScanWorker.calls.append("start")
        ScanWorker.running_now = True
        return 2


class ScanClient:
    """A WeChat client whose login answers the way the test needs, without a phone."""

    def __init__(self, statuses: list) -> None:
        self.statuses = statuses
        self.closed = False

    async def login(self):
        from agim.models import LoginHandshake

        return LoginHandshake(qr_content="https://example.com/qr")

    async def is_login(self, handshake, *, verify_code=None):
        from agim.models import LoginCredentials, LoginState

        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if status.value == "connected":
            return LoginState(
                status=status,
                message="connected",
                credentials=LoginCredentials(config={"base_url": "https://example.com"}, secrets={"bot_token": "t"}),
            )
        return LoginState(status=status, message="no")

    async def aclose(self) -> None:
        self.closed = True


def test_a_scan_that_does_not_finish_leaves_the_running_bridge_alone(tmp_path: Path, monkeypatch) -> None:
    """The bridge a reader already has must outlive a scan they walked away from."""
    from agim.models import LoginStatus

    from zettcode.im.weixin import cli

    ScanWorker.calls = []
    ScanWorker.running_now = True
    monkeypatch.setattr(cli, "Worker", ScanWorker)
    monkeypatch.setattr("agim.wechat.client.WeChatClient", lambda *a, **k: ScanClient([LoginStatus.EXPIRED]))

    status = asyncio.run(cli._login(cli.build_parser().parse_args(["login", "--state-dir", str(tmp_path)]), tmp_path))

    assert status == 2
    assert ScanWorker.calls == [], "nothing was stopped and nothing was started"
    assert ScanWorker.running_now, "the bridge that was there is still there"


def test_a_scan_that_finishes_replaces_the_running_bridge(tmp_path: Path, monkeypatch) -> None:
    from agim.models import LoginStatus

    from zettcode.im.state import BridgeState
    from zettcode.im.weixin import cli

    ScanWorker.calls = []
    ScanWorker.running_now = True
    monkeypatch.setattr(cli, "Worker", ScanWorker)
    monkeypatch.setattr("agim.wechat.client.WeChatClient", lambda *a, **k: ScanClient([LoginStatus.CONNECTED]))

    status = asyncio.run(
        cli._login(
            cli.build_parser().parse_args(["login", "--state-dir", str(tmp_path), "--allow", "u1"]),
            tmp_path,
        )
    )

    assert status == 0
    assert ScanWorker.calls == ["stop", "start"], "the old process is stopped, then a new one starts"
    saved = BridgeState.load(tmp_path / "state.json")
    assert saved.token() == "t" and saved.allow == ["u1"]


def test_a_second_scan_keeps_the_settings_the_first_one_set(tmp_path: Path, monkeypatch) -> None:
    """Re-scanning renews the connection; it does not silently empty the allow-list somebody set."""
    from agim.models import LoginStatus

    from zettcode.im.state import BridgeState
    from zettcode.im.weixin import cli

    stored = BridgeState.load(tmp_path / "state.json")
    stored.allow = ["u1"]
    stored.workspace = "/w"
    stored.permission = "deny"
    stored.save()
    ScanWorker.calls = []
    ScanWorker.running_now = False
    monkeypatch.setattr(cli, "Worker", ScanWorker)
    monkeypatch.setattr("agim.wechat.client.WeChatClient", lambda *a, **k: ScanClient([LoginStatus.CONNECTED]))

    assert (
        asyncio.run(cli._login(cli.build_parser().parse_args(["login", "--state-dir", str(tmp_path)]), tmp_path)) == 0
    )

    after = BridgeState.load(tmp_path / "state.json")
    assert after.allow == ["u1"], "the allow-list survived the scan"
    assert after.workspace == "/w" and after.permission == "deny"
    assert after.token() == "t", "and the new login replaced the token"


def test_set_writes_the_settings_and_restarts_what_holds_the_old_ones(tmp_path: Path, monkeypatch, capsys) -> None:
    """A running daemon was started at the old level, and the process read the file once: both are remade."""
    from zettcode.im.state import BridgeState
    from zettcode.im.weixin import cli

    state = BridgeState.load(tmp_path / "state.json")
    state.credentials = {"secrets": {"bot_token": "t"}}
    state.session_id = "01a1"
    state.save()
    ScanWorker.calls = []
    ScanWorker.running_now = True
    monkeypatch.setattr(cli, "Worker", ScanWorker)
    stopped: list[str] = []

    async def stop_daemon(session_id, *, keep=False):
        stopped.append(session_id)
        return "stopped; its record was kept"

    monkeypatch.setattr("zettcode.sdk.daemons.stop_daemon", stop_daemon)

    status = cli.main(["set", "--state-dir", str(tmp_path), "--permission", "deny", "--allow", "u1"])

    assert status == 0
    saved = BridgeState.load(tmp_path / "state.json")
    assert saved.permission == "deny" and saved.allow == ["u1"]
    assert stopped == ["01a1"], "the daemon is stopped so the next message starts it at the new level"
    assert ScanWorker.calls == ["stop", "start"], "and the background process reads the file again"


def test_start_brings_the_background_process_back_without_a_scan(tmp_path: Path, monkeypatch, capsys) -> None:
    from zettcode.im.state import BridgeState
    from zettcode.im.weixin import cli

    state = BridgeState.load(tmp_path / "state.json")
    state.credentials = {"secrets": {"bot_token": "t"}}
    state.save()
    ScanWorker.calls = []
    ScanWorker.running_now = False
    monkeypatch.setattr(cli, "Worker", ScanWorker)

    assert cli.main(["start", "--state-dir", str(tmp_path)]) == 0
    assert ScanWorker.calls == ["start"]


def test_start_refuses_when_there_is_no_login(tmp_path: Path, monkeypatch, capsys) -> None:
    from zettcode.im.weixin import cli

    ScanWorker.calls = []
    monkeypatch.setattr(cli, "Worker", ScanWorker)

    assert cli.main(["start", "--state-dir", str(tmp_path)]) == 2
    assert ScanWorker.calls == []
    assert "no login" in capsys.readouterr().out
