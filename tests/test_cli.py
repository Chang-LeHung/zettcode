"""The command line picks the workspace and the session to resume; settings come from the config file."""

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zettcode import cli
from zettcode.cli import (
    Options,
    async_main,
    parse_args,
    resolve_config,
    resume_command,
    session_exists,
    workspace_from_args,
)


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ZETTCODE_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def test_help_never_imports_the_process_naming_helper(monkeypatch):
    def refuse_naming():
        raise AssertionError("--help must exit before importing a native helper")

    monkeypatch.setattr(sys, "argv", ["zettcode", "--help"])
    monkeypatch.setattr(cli, "_name_process", refuse_naming)
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0


def test_startup_names_the_process_before_entering_the_application(monkeypatch):
    calls = []

    async def run_app(options, **kwargs):
        calls.append("run")

    monkeypatch.setattr(cli, "parse_args", lambda: Options(workspace=Path.cwd()))
    monkeypatch.setattr(cli, "_name_process", lambda: calls.append("name"))
    monkeypatch.setattr(cli, "launch", run_app)
    cli.main()
    assert calls == ["name", "run"]


def test_process_naming_uses_zettcode_instead_of_the_interpreter(monkeypatch):
    names = []
    monkeypatch.setattr(cli.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "setproctitle", SimpleNamespace(setproctitle=names.append))
    cli._name_process()
    assert names == ["zettcode"]


@pytest.mark.skipif(os.name != "posix", reason="Windows cannot rename a foreground executable")
def test_process_naming_changes_the_real_title_without_changing_python_arguments():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from zettcode.cli import _name_process; from setproctitle import getproctitle; "
            "arguments = sys.argv[:]; _name_process(); "
            "assert sys.argv == arguments; print(getproctitle())",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "zettcode"


@pytest.mark.parametrize("error", [ImportError("missing"), OSError("unavailable"), RuntimeError("unsupported")])
def test_process_naming_failure_does_not_block_startup(monkeypatch, error):
    def fail(name):
        raise error

    monkeypatch.setattr(cli.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "setproctitle", SimpleNamespace(setproctitle=fail))
    cli._name_process()


def test_a_missing_process_naming_helper_does_not_block_startup(monkeypatch):
    monkeypatch.setattr(cli.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "setproctitle", None)
    cli._name_process()


def test_windows_does_not_try_to_rename_the_executable(monkeypatch):
    def refuse(name):
        raise AssertionError("Windows uses the terminal title, not POSIX process naming")

    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "setproctitle", SimpleNamespace(setproctitle=refuse))
    cli._name_process()


def test_workspace_defaults_to_the_current_directory(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    assert workspace_from_args([]) == Path.cwd()


def test_workspace_comes_from_the_flag(tmp_path: Path):
    assert workspace_from_args(["-w", str(tmp_path)]) == tmp_path
    assert workspace_from_args(["--workspace", str(tmp_path)]) == tmp_path


def test_the_dry_run_flag_asks_for_startup_only(tmp_path: Path):
    assert parse_args(["-w", str(tmp_path)]).dry_run is False
    assert parse_args(["-w", str(tmp_path), "--dry-run"]).dry_run is True


def test_the_resume_flag_picks_the_session(tmp_path: Path):
    """`-r` and `--resume` are the same flag, and a run without one starts fresh."""
    assert parse_args(["-w", str(tmp_path)]) == Options(workspace=tmp_path)
    assert parse_args(["-w", str(tmp_path), "-r", "abc"]) == Options(workspace=tmp_path, resume="abc")
    assert parse_args(["--resume", "abc", "--workspace", str(tmp_path)]) == Options(workspace=tmp_path, resume="abc")


def test_the_resume_command_survives_a_workspace_with_spaces(tmp_path: Path):
    """The line the shell prints on exit has to paste into a shell as it stands."""
    workspace = tmp_path / "my workspace"

    parts = shlex.split(resume_command("01a10b75", workspace))

    assert parts == ["zettcode", "--resume", "01a10b75", "--workspace", str(workspace)]


def test_session_exists_finds_a_stored_session(tmp_path: Path, monkeypatch):
    from datetime import datetime, timezone

    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import UserMessage

    from zettcode.app.agent.storage import SessionStore

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])
    moment = datetime.now(timezone.utc)
    timing = MessageTiming(started_at=moment, completed_at=moment, duration_ns=1)
    store = SessionStore(config.store, config.workspace)
    asyncio.run(store.append("stored", "r", UserMessage(content="hi"), timing=timing))

    assert session_exists(config, "stored") is True
    assert session_exists(config, "missing") is False


def test_an_unknown_session_is_refused_before_the_terminal_is_taken(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])

    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(async_main(config, resume="nope"))

    assert "no session nope" in str(exit_info.value.code)


def test_a_resumed_run_reports_the_command_that_reopens_it(tmp_path: Path, monkeypatch, capsys):
    """Leaving the shell prints the way back in, for the session that was open."""
    from datetime import datetime, timezone

    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import UserMessage

    from zettcode.app.agent.storage import SessionStore

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])
    moment = datetime.now(timezone.utc)
    timing = MessageTiming(started_at=moment, completed_at=moment, duration_ns=1)
    asyncio.run(
        SessionStore(config.store, config.workspace).append("stored", "r", UserMessage(content="hi"), timing=timing)
    )

    resumed: list[str] = []

    class FakeApp:
        def __init__(self, agent, **kwargs):
            self.agent = agent

        def restore_session(self, session_id: str) -> None:
            resumed.append(session_id)
            self.agent.use_session(session_id)

        async def run(self) -> None:
            return None

    monkeypatch.setattr("zettcode.app.ZettCodeApp", FakeApp)

    asyncio.run(async_main(config, resume="stored"))

    assert resumed == ["stored"]
    # Quoted the way the shell needs it, which differs with the path's separators.
    assert resume_command("stored", config.workspace) in capsys.readouterr().out


def test_an_empty_session_offers_no_resume_command(tmp_path: Path, monkeypatch, capsys):
    """Nothing was stored, so the id would name a session the store never saw."""
    from zettcode.cli import report_resume

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])
    agent = SimpleNamespace(
        runtime=SimpleNamespace(config=config),
        session_id="never-stored",
        workspace=tmp_path,
    )

    report_resume(agent)

    assert capsys.readouterr().out == ""


def test_a_dry_run_starts_everything_and_exits(tmp_path: Path, monkeypatch, capsys):
    """The flag profiling needs: the whole start, no terminal, no output of its own."""
    from dataclasses import replace

    from zettcode.app.agent.storage import SessionStore

    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[skills]\nenabled = false\n\n[mcp]\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = replace(resolve_config(["-w", str(tmp_path)]), store=tmp_path / "sessions")

    asyncio.run(async_main(config, dry_run=True))

    assert capsys.readouterr().out == ""  # a profiler's output is the only report
    # A dry run only reads: the fresh session id never reaches the store.
    assert asyncio.run(SessionStore(config.store, config.workspace).list_sessions()) == []


def test_resolve_config_reads_the_config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "my-model"\ntoken = "secret"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    config = resolve_config(["-w", str(tmp_path)])

    assert config.models[0].model == "my-model"
    assert config.workspace == tmp_path.resolve()


def test_resolve_config_reports_a_bad_config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("nope = 1\n", encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    with pytest.raises(SystemExit) as exit_info:
        resolve_config(["-w", str(tmp_path)])

    assert "Unknown config keys" in str(exit_info.value.code)


def test_the_help_flag_builds_nothing():
    """`-h` explains the program; it must not load the agent to do it."""
    script = "\n".join(
        [
            "import sys",
            "sys.argv = ['zettcode', '--help']",
            "import zettcode.cli",
            "try:",
            "    zettcode.cli.main()",
            "except SystemExit:",
            "    pass",
            "print('zett_agent' in sys.modules, 'zettcode.app.ui.app' in sys.modules)",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    # The help text shares stdout with the probe, so only its last line is read.
    assert result.stdout.strip().splitlines()[-1] == "False False"
