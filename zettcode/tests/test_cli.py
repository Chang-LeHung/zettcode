"""The command line picks the workspace and the session to resume; settings come from the config file."""

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zettcode import cli, paths
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


def test_freezing_the_heap_takes_it_out_of_the_collectors_way(tmp_path: Path):
    """What `freeze_heap()` buys, measured where it is spent: one collection.

    A child holding what a shell holds — the model SDKs and a live heap — times an
    explicit collection, freezes, and times it again. The second is the same
    collection over a heap the collector no longer walks, which is the whole of
    the several hundred milliseconds a quit used to take after its own cleanup
    was done; that end-to-end number belongs in `perf/exit.py`, where it was
    measured, and not in an assertion that a shared machine can decide.

    The same child proves the freeze is not a way of skipping the interpreter's
    shutdown: its `atexit` handler still runs.
    """
    marker = tmp_path / "atexit-ran"
    script = "\n".join(
        [
            "import atexit, gc, sys, time",
            "import openai, anthropic",
            f"atexit.register(lambda: open({str(marker)!r}, 'w').close())",
            "heap = []",
            "for index in range(4000):",
            "    node = {'index': index}",
            "    node['self'] = node",
            "    heap.append(node)",
            "start = time.perf_counter(); gc.collect(); plain = time.perf_counter() - start",
            "from zettcode.cli import freeze_heap",
            "freeze_heap()",
            "start = time.perf_counter(); gc.collect(); frozen = time.perf_counter() - start",
            "print(plain, frozen)",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    plain, frozen = (float(value) for value in result.stdout.split())
    assert marker.exists(), "freezing the heap must not skip the interpreter's own shutdown"
    assert plain > frozen * 2, f"the collection costs {plain * 1000:.0f} ms, {frozen * 1000:.0f} ms frozen"


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


def test_the_resume_subcommand_is_the_resume_option_spelled_as_a_word(tmp_path: Path):
    """`zettcode resume ID` starts a session exactly as `zettcode --resume ID` does; both stay."""
    assert parse_args(["-w", str(tmp_path), "resume", "abc"]) == Options(workspace=tmp_path, resume="abc")
    assert parse_args(["resume", "abc"]).command is None, "it starts a session; it is not a program of its own"
    assert parse_args(["resume", "abc"]) == parse_args(["--resume", "abc"])
    # Both spellings at once are fine when they agree, and a mistake when they do not.
    assert parse_args(["--resume", "abc", "resume", "abc"]).resume == "abc"
    with pytest.raises(SystemExit):
        parse_args(["--resume", "abc", "resume", "def"])
    with pytest.raises(SystemExit):
        parse_args(["resume"])


def test_the_resume_command_survives_a_workspace_with_spaces(tmp_path: Path):
    """The line the shell prints on exit has to paste into a shell as it stands."""
    workspace = tmp_path / "my workspace"

    parts = shlex.split(resume_command("01a10b75", workspace))

    assert parts == ["zettcode", "resume", "01a10b75", "--workspace", str(workspace)]


def test_the_resume_subcommand_takes_the_workspace_after_the_word(tmp_path: Path):
    """The printed line has to parse as it stands, with the directory where it is written."""
    from zettcode.cli import parse_args

    options = parse_args(["resume", "01a10b75", "--workspace", str(tmp_path)])

    assert options.resume == "01a10b75" and options.workspace == tmp_path


def test_the_resume_subcommand_keeps_the_directory_the_global_flag_chose(tmp_path: Path):
    options = parse_args(["-w", str(tmp_path), "resume", "01a10b75"])

    assert options.workspace == tmp_path and options.resume == "01a10b75"


def test_session_exists_finds_a_stored_session(tmp_path: Path, monkeypatch):
    from datetime import datetime, timezone

    from zett_agent.extensions.events import MessageTiming
    from zett_agent.messages import UserMessage

    from zettcode.engine.storage import SessionStore

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


def test_resuming_builds_the_application_where_no_loop_is_running(tmp_path: Path, monkeypatch):
    """`--resume` restores on a worker thread, so nothing there can be scheduled.

    The command line hands `build_application` to `asyncio.to_thread` so the first
    frame is not held up by the config, the runtime, or a store read. A restore
    therefore runs with no running loop, and anything that reached for one there —
    `asyncio.create_task`, say — would raise before the interface exists and leave
    `--resume` broken. Nothing on the path may need a loop at all.
    """
    from zett_agent.messages import UserMessage

    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine.storage import SessionStore

    root = tmp_path / "sessions"
    asyncio.run(SessionStore(root, tmp_path).append("stored", "r", UserMessage(content="hi")))
    monkeypatch.setattr(
        cli,
        "resolve_config",
        lambda: ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=root),
    )

    app = cli.build_application(Options(workspace=tmp_path, resume="stored"))

    assert app.agent.session_id == "stored"
    assert app._measure_task is None, "nothing on this path schedules anything"


def test_resuming_a_long_session_decodes_only_the_window_the_transcript_keeps(tmp_path: Path, monkeypatch):
    """The cap the config sets reaches the walk, and the messages before it stay as stored.

    A resumed session costs what the transcript shows and not what the session holds:
    the lines before the window are neither decoded nor replayed, and the figures the
    status line adds up from them — the tokens every reply used — still count them.
    """
    from zett_agent.messages import AssistantMessage, UserMessage
    from zett_agent.model import ModelUsage

    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine.storage import SessionStore

    root = tmp_path / "sessions"
    store = SessionStore(root, tmp_path)

    async def write() -> None:
        for turn in range(200):
            await store.append("long", f"r{turn}", UserMessage(content=f"question {turn}"))
            await store.append(
                "long",
                f"r{turn}",
                AssistantMessage(content=f"answer {turn}"),
                usage=ModelUsage(input_tokens=1_000, output_tokens=10),
            )

    asyncio.run(write())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "resolve_config",
        lambda: ZettCodeConfig(
            workspace=tmp_path,
            models=(ModelConfig(model="m", token="t"),),
            store=root,
            transcript_max_entries=50,
        ),
    )

    app = cli.build_application(Options(workspace=tmp_path, resume="long"))

    shown = [entry.text for entry in app.transcript.entries if entry.kind == "answer"]
    assert shown[-1] == "answer 199"
    assert 50 <= len(app.transcript.entries) < 400, "the configured cap, not the default one and not the whole session"
    lines = app.agent.runtime.persistence.read("long").branch()
    assert not lines[0].message.decoded and not lines[100].message.decoded
    assert lines[-1].message.decoded
    assert app._usage.input_tokens == 200 * 1_000, "every reply on the branch is in the totals"


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

    from zettcode.engine.storage import SessionStore

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

    from zettcode.engine.storage import SessionStore

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


@pytest.mark.parametrize("flag", ["-v", "-V", "--version"])
def test_every_spelling_of_the_version_flag_prints_one_line_and_exits_cleanly(flag, capsys):
    from zettcode import __version__

    with pytest.raises(SystemExit) as exit_info:
        parse_args([flag])

    out = capsys.readouterr().out
    assert exit_info.value.code in (0, None)
    assert out.count("\n") == 1 and out.startswith(f"zettcode {__version__} (zett-agent ")
    assert "Python " in out


def test_the_version_names_the_agent_library_it_runs_on():
    import importlib.metadata

    assert f"zett-agent {importlib.metadata.version('zett-agent')}" in cli.version_text()


def test_the_version_flag_wins_over_the_other_arguments_and_builds_nothing(tmp_path):
    """`-v` is answered from the argument parser: no agent, no terminal, whatever else was typed."""
    script = "\n".join(
        [
            "import sys",
            f"sys.argv = ['zettcode', '-v', '-w', {str(tmp_path)!r}]",
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
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("zettcode ") and lines[-1] == "False False"


def test_the_help_lists_the_version_flag(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--help"])

    said = capsys.readouterr().out
    assert "-v, -V, --version" in said
    assert "broker" in said and "gateway" in said, "the commands of their own are named in the help"


def test_the_collector_is_told_to_interrupt_the_interface_less_often_and_nothing_else_changes():
    import gc

    gc.set_threshold(2000, 10, 0)  # python's own default, whatever an earlier test left
    before = gc.get_threshold()

    cli.tune_collector()
    after = gc.get_threshold()

    assert after[0] == cli.GC_YOUNG_THRESHOLD > before[0]
    assert after[1:] == before[1:]


def test_starting_the_program_tunes_the_collector_before_anything_else_runs(monkeypatch):

    calls: list[str] = []
    monkeypatch.setattr(cli, "tune_collector", lambda: calls.append("tuned"))
    monkeypatch.setattr(
        cli, "parse_args", lambda: SimpleNamespace(dry_run=False, resume=None, auto=False, command=None)
    )
    monkeypatch.setattr(cli, "_name_process", lambda: calls.append("named"))
    monkeypatch.setattr(cli, "launch", lambda options: calls.append("launched"))
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: calls.append(coroutine))
    monkeypatch.setattr(cli, "freeze_heap", lambda: None)

    cli.main()

    assert calls[:2] == ["tuned", "named"]


# -- a resumed session is measured where it will be drawn ----------------------------


def _long_session(tmp_path: Path, turns: int = 40) -> tuple[Path, Path]:
    """Write a session of ``turns`` turns into a throwaway store and return (store, workspace)."""
    from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

    from zettcode.engine.storage import SessionStore

    root = tmp_path / "sessions"
    store = SessionStore(root, tmp_path)

    async def write() -> None:
        for turn in range(turns):
            await store.append("long", f"r{turn}", UserMessage(content=f"question {turn}"))
            call = ToolCall(f"c{turn}", "read_file", {"path": f"module_{turn}.py"})
            await store.append("long", f"r{turn}", AssistantMessage(tool_calls=(call,)))
            await store.append(
                "long", f"r{turn}", ToolMessage(tool_call_id=call.id, name="read_file", content="x = 1\n" * 12)
            )
            await store.append("long", f"r{turn}", AssistantMessage(content=f"answer {turn} with `code` and **bold**"))

    asyncio.run(write())
    return root, tmp_path


def _resume(tmp_path: Path, monkeypatch, *, terminal, theme_file=None):
    """Build the application the way the command line does, for a terminal that is already up."""
    from zettcode.config import ModelConfig, ZettCodeConfig

    root, workspace = _long_session(tmp_path)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        cli,
        "resolve_config",
        lambda: ZettCodeConfig(
            workspace=workspace, models=(ModelConfig(model="m", token="t"),), store=root, theme_file=theme_file
        ),
    )
    return cli.build_application(Options(workspace=workspace, resume="long"), terminal=terminal)


def _count_rendered(app, monkeypatch) -> list[int]:
    """Spy every presenter's ``lines``, and return the ids of the rows it is asked to render."""
    drawn: list[int] = []
    for presenter in app.transcript.presenters.presenters:
        real = type(presenter).lines

        def spy(self, entry, *args, _real=real):
            drawn.append(entry.id)
            return _real(self, entry, *args)

        monkeypatch.setattr(type(presenter), "lines", spy)
    return drawn


def test_a_resumed_session_is_measured_at_the_terminals_width_and_the_first_frame_reuses_it(tmp_path, monkeypatch):
    """The tree built behind the boot frame has no size yet, but the terminal under it does.

    Measuring at the width of an unplaced view — one column — was the most expensive thing
    the transcript can be asked and was thrown away by the first frame, which measured
    every row again at the real width.
    """
    from zettcode.tui import DARK

    terminal = SimpleNamespace(width=100, theme=DARK)
    app = _resume(tmp_path, monkeypatch, terminal=terminal)
    drawn = _count_rendered(app, monkeypatch)

    app.app.resize(100, 30)
    app.app.mount()
    app.app.render()

    assert len(app.transcript.entries) >= 100
    assert drawn == [], "the first frame found every row already measured"


def test_a_resumed_session_is_measured_in_the_palette_the_terminal_chose(tmp_path, monkeypatch):
    """A light terminal's rows are keyed to the light palette, which is the one they are painted in."""
    from zettcode.tui import LIGHT

    terminal = SimpleNamespace(width=100, theme=LIGHT)
    app = _resume(tmp_path, monkeypatch, terminal=terminal)
    app.app.theme = LIGHT  # what adopting the boot frame's app does once the terminal has answered
    drawn = _count_rendered(app, monkeypatch)

    app.app.resize(100, 30)
    app.app.mount()
    app.app.render()

    assert drawn == []


def test_a_width_other_than_the_terminals_is_a_miss_and_not_a_wrong_row(tmp_path, monkeypatch):
    """The window can be resized between the read and the swap; the rows are then measured again."""
    from zettcode.tui import DARK

    app = _resume(tmp_path, monkeypatch, terminal=SimpleNamespace(width=100, theme=DARK))
    drawn = _count_rendered(app, monkeypatch)

    app.app.resize(70, 30)
    app.app.mount()
    app.app.render()

    assert drawn, "measured at 70, because 100 was what the cache held"
    lines = app.view.transcript_source
    assert all(lines.line(index, 70).width <= 70 for index in range(lines.count(70)))


def test_without_a_terminal_the_session_is_measured_at_the_view_it_has(tmp_path, monkeypatch):
    """The path the tests and the dry run take: no boot frame, so the view's own size is all there is."""
    app = _resume(tmp_path, monkeypatch, terminal=None)

    assert len(app.transcript.entries) >= 100
    assert [entry for entry in app.transcript.entries if entry.block is None] == []


async def test_the_launch_hands_the_build_the_terminal_it_is_painting(tmp_path, monkeypatch):
    """The build measures a resumed session at the boot frame's width, so it has to be given the frame.

    Every test of that measuring builds the application directly; the one place the terminal
    reaches it is the line in `launch` that starts the build, which only a test that runs
    `launch` can see.
    """
    import zettcode.tui as tui_module

    config = tmp_path / "config.toml"
    config.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    given: dict[str, object] = {}

    class QuietRunner:
        def __init__(self, tui, *, terminal=None):
            given["boot"] = tui
            given["after_paint"] = []

        def after_next_paint(self, callback) -> None:
            given["after_paint"].append(callback)

        async def run(self) -> None:
            await asyncio.sleep(0)

    class NoTerminal:
        def __init__(self, **_):
            pass

    async def stop() -> None:
        pass

    started: list[str] = []
    stub = SimpleNamespace(
        adopt=lambda boot: given.setdefault("order", []).append("adopt"),
        start_background=lambda: started.append("started"),
        stop_background=stop,
        agent=None,
    )

    def build(options, *, terminal=None):
        given["terminal"] = terminal
        return stub

    monkeypatch.setattr(tui_module, "TerminalRunner", QuietRunner)
    monkeypatch.setattr(tui_module, "Terminal", NoTerminal)
    monkeypatch.setattr(cli, "build_application", build)
    monkeypatch.setattr(cli, "report_resume", lambda agent: None)

    await cli.launch(Options(workspace=tmp_path, resume="anything"))

    assert given["terminal"] is given["boot"], "the app painting the boot frame is the one the build is told about"


async def test_the_runtime_warms_up_after_the_real_frame_is_painted_not_when_it_is_swapped_in(tmp_path, monkeypatch):
    """The imports share the interpreter's one lock with the drawing, so the frame goes first.

    The swap hands the runner the real tree; the background work is queued behind the frame
    that draws it, and a launch that ends before that frame starts none of it.
    """
    import zettcode.tui as tui_module

    config = tmp_path / "config.toml"
    config.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    queued: list = []
    started: list[str] = []

    class QuietRunner:
        def __init__(self, tui, *, terminal=None):
            pass

        def after_next_paint(self, callback) -> None:
            queued.append(callback)

        async def run(self) -> None:
            await asyncio.sleep(0)

    class NoTerminal:
        def __init__(self, **_):
            pass

    async def stop() -> None:
        pass

    stub = SimpleNamespace(
        adopt=lambda boot: None, start_background=lambda: started.append("started"), stop_background=stop, agent=None
    )
    monkeypatch.setattr(tui_module, "TerminalRunner", QuietRunner)
    monkeypatch.setattr(tui_module, "Terminal", NoTerminal)
    monkeypatch.setattr(cli, "build_application", lambda options, *, terminal=None: stub)
    monkeypatch.setattr(cli, "report_resume", lambda agent: None)

    await cli.launch(Options(workspace=tmp_path))

    assert started == [], "nothing was started when the tree was swapped in"
    assert len(queued) == 1, "it was queued for after the next frame"
    queued[0]()
    assert started == ["started"], "and what was queued is the start of the background work"


# -- starting with the shell permission already at full --------------------------


def test_the_full_flag_has_three_spellings_and_sets_the_starting_level(tmp_path, monkeypatch):
    """`--full` is the name; `--auto` is what it was called, and `--yolo` stays, because nobody types the long one twice."""
    assert cli.parse_args(["--full"]).auto is True
    assert cli.parse_args(["--auto"]).auto is True
    assert cli.parse_args(["--yolo"]).auto is True
    assert cli.parse_args([]).auto is False

    config = tmp_path / "config.toml"
    config.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    monkeypatch.setattr(cli, "resolve_config", lambda: resolve_config(["-w", str(tmp_path)]))
    from zettcode.engine.permission import Permission

    plain = cli.build_application(Options(workspace=tmp_path))
    wild = cli.build_application(Options(workspace=tmp_path, auto=True))

    assert plain.agent.permission is Permission.ASK, "a launch asks unless it is told not to"
    assert wild.agent.permission is Permission.FULL
    announced = [entry for entry in wild.transcript.entries if entry.kind != "welcome"]
    assert announced == [], "nothing is announced: there is no conversation yet"
    assert "full" in wild._status_left().text, "the status line says so instead"


async def test_the_auto_flag_reaches_the_dry_run_path_too(tmp_path, monkeypatch):
    """Both ways in build the same shell, so the flag cannot mean one thing on one path."""
    from zettcode.engine.permission import Permission

    config = tmp_path / "config.toml"
    config.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    import zettcode.app as app_facade

    real = app_facade.ZettCodeApp
    seen: dict[str, object] = {}

    class Recorder(real):  # type: ignore[misc, valid-type]
        def __init__(self, agent, **kwargs):
            super().__init__(agent, **kwargs)
            seen["permission"] = agent.permission

        async def dry_run(self, **kwargs) -> None:
            return None

    monkeypatch.setattr(app_facade, "ZettCodeApp", Recorder)
    settings = resolve_config(["-w", str(tmp_path)])

    await cli.async_main(settings, auto=True, dry_run=True)
    assert seen["permission"] is Permission.FULL

    await cli.async_main(settings, dry_run=True)
    assert seen["permission"] is Permission.ASK


# -- the palette of the first frame ---------------------------------------------------------------


def _write_config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n{extra}', encoding="utf-8")
    return path


def test_the_first_frame_is_painted_in_the_palette_the_config_file_names(tmp_path, monkeypatch):
    """A start that opens in a light palette must not paint a dark frame and swap it a tenth of a second later."""
    monkeypatch.setenv("ZETTCODE_CONFIG", str(_write_config(tmp_path, '\n[ui]\ntheme = "nord"\n')))
    monkeypatch.setattr(paths, "DEFAULT_THEME_FILE", tmp_path / "absent-theme.toml")

    picked = cli.boot_theme()

    assert picked is not None and picked.name == "nord"
    assert picked.background is not None, "and it paints its own page, as the real start will"


def test_the_first_frame_lays_a_theme_file_over_the_named_palette(tmp_path, monkeypatch):
    """The one file over any palette is read on this path too, or the swap would change those colours."""
    monkeypatch.setenv("ZETTCODE_CONFIG", str(_write_config(tmp_path, '\n[ui]\ntheme = "nord"\n')))
    adjust = tmp_path / "theme.toml"
    adjust.write_text('[ui]\naccent = "#010203"\n', encoding="utf-8")
    monkeypatch.setattr(paths, "DEFAULT_THEME_FILE", adjust)

    picked = cli.boot_theme()

    assert picked is not None and picked.accent == "#010203"
    from zettcode.tui import ThemeCatalog, bundled_themes

    nord = ThemeCatalog(bundled_themes()).load("nord")
    assert picked.background == nord.background, "everything else is still nord's"


def test_a_palette_this_early_path_cannot_know_is_left_to_the_application(tmp_path, monkeypatch):
    """A name nobody has (or one only a plugin offers) falls back to the terminal rather than raising here."""
    monkeypatch.setenv("ZETTCODE_CONFIG", str(_write_config(tmp_path, '\n[ui]\ntheme = "not-a-palette"\n')))
    monkeypatch.setattr(paths, "DEFAULT_THEME_FILE", tmp_path / "absent-theme.toml")

    assert cli.boot_theme() is None


def test_a_config_file_this_early_path_cannot_read_is_left_to_the_application(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    broken = _write_config(tmp_path, "\n[ui\n")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(broken))

    assert cli.boot_theme() is None


async def test_the_boot_frame_is_the_chosen_palette_and_the_terminal_cannot_override_it(tmp_path, monkeypatch):
    """`auto_theme` asks the terminal, and the terminal would answer with its own dark or light."""
    import zettcode.tui as tui_module

    monkeypatch.setenv("ZETTCODE_CONFIG", str(_write_config(tmp_path, '\n[ui]\ntheme = "nord"\n')))
    monkeypatch.setattr(paths, "DEFAULT_THEME_FILE", tmp_path / "absent-theme.toml")
    given: dict[str, object] = {}

    class QuietRunner:
        def __init__(self, tui, *, terminal=None):
            given["boot"] = tui

        def after_next_paint(self, callback) -> None:
            pass

        async def run(self) -> None:
            await asyncio.sleep(0)

    class NoTerminal:
        def __init__(self, **_):
            pass

    async def stop() -> None:
        pass

    stub = SimpleNamespace(adopt=lambda boot: None, start_background=lambda: None, stop_background=stop, agent=None)
    monkeypatch.setattr(tui_module, "TerminalRunner", QuietRunner)
    monkeypatch.setattr(tui_module, "Terminal", NoTerminal)
    monkeypatch.setattr(cli, "build_application", lambda options, *, terminal=None: stub)
    monkeypatch.setattr(cli, "report_resume", lambda agent: None)

    await cli.launch(Options(workspace=tmp_path))

    boot = given["boot"]
    assert boot.theme.name == "nord" and boot.auto_theme is False


async def test_without_a_chosen_palette_the_boot_frame_still_follows_the_terminals_background(tmp_path, monkeypatch):
    import zettcode.tui as tui_module

    monkeypatch.setenv("ZETTCODE_CONFIG", str(_write_config(tmp_path)))
    monkeypatch.setattr(paths, "DEFAULT_THEME_FILE", tmp_path / "absent-theme.toml")
    given: dict[str, object] = {}

    class QuietRunner:
        def __init__(self, tui, *, terminal=None):
            given["boot"] = tui

        def after_next_paint(self, callback) -> None:
            pass

        async def run(self) -> None:
            await asyncio.sleep(0)

    class NoTerminal:
        def __init__(self, **_):
            pass

    async def stop() -> None:
        pass

    stub = SimpleNamespace(adopt=lambda boot: None, start_background=lambda: None, stop_background=stop, agent=None)
    monkeypatch.setattr(tui_module, "TerminalRunner", QuietRunner)
    monkeypatch.setattr(tui_module, "Terminal", NoTerminal)
    monkeypatch.setattr(cli, "build_application", lambda options, *, terminal=None: stub)
    monkeypatch.setattr(cli, "report_resume", lambda agent: None)

    await cli.launch(Options(workspace=tmp_path))

    assert given["boot"].auto_theme is True
