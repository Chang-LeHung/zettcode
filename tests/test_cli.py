"""The command line picks the workspace and the session to resume; settings come from the config file."""

import asyncio
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

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
    from datetime import UTC, datetime

    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import UserMessage

    from zettcode.app.agent.storage import SessionStore

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])
    moment = datetime.now(UTC)
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
    from datetime import UTC, datetime

    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import UserMessage

    from zettcode.app.agent.storage import SessionStore

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = resolve_config(["-w", str(tmp_path)])
    moment = datetime.now(UTC)
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
    assert f"zettcode --resume stored --workspace {config.workspace}" in capsys.readouterr().out


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
