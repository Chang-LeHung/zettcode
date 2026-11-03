"""The ``zettcode gateway`` command: its arguments become settings, and start/stop/restart act on a recorded gateway."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.gateway import cli, runfile
from zettcode.gateway.cli import build_parser, settings_from, version_text
from zettcode.gateway.runfile import Running
from zettcode.gateway.settings import TOKEN_VARIABLE, Settings


def test_with_no_token_there_is_no_sign_in_and_a_given_token_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    made = settings_from(["-r", str(tmp_path)])
    given = settings_from(["-r", str(tmp_path), "--token", "abc"])

    assert made.open and made.token == "" and not given.open and given.token == "abc"
    assert made.host == "127.0.0.1" and made.allow_full is True and made.roots == (tmp_path.resolve(),)


def test_with_no_root_given_any_directory_may_be_chosen_and_no_full_turns_the_full_level_off(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    everywhere = settings_from([])
    limited = settings_from(["-r", str(tmp_path), "--no-full"])

    # The top of the drive the home directory is on: "/" on a POSIX machine, "C:\\" on a Windows one.
    assert everywhere.roots == (Path(Path.home().anchor or "/").resolve(),) and everywhere.allow_full is True
    assert limited.allow_full is False


def test_the_token_may_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_VARIABLE, "from-env")

    settings = settings_from(["-r", str(tmp_path)])

    assert settings.token == "from-env" and not settings.open


def test_a_gateway_with_no_token_refuses_to_listen_beyond_this_machine(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    with pytest.raises(SystemExit) as refused:
        settings_from(["-r", str(tmp_path), "--host", "0.0.0.0"])

    assert "needs a token" in str(refused.value)
    assert settings_from(["-r", str(tmp_path), "--host", "0.0.0.0", "--token", "t"]).host == "0.0.0.0"


def test_a_root_that_is_not_a_directory_or_a_bad_port_stops_the_start(tmp_path):
    with pytest.raises(SystemExit):
        settings_from(["-r", str(tmp_path / "absent")])
    with pytest.raises(SystemExit):
        settings_from(["-r", str(tmp_path), "--port", "0"])


def test_help_and_version_answer_without_loading_the_app(capsys):
    assert version_text().startswith("zettcode gateway ")
    assert "--no-full" in build_parser().format_help()


# -- what start, stop and restart keep from the gateway that is running ------------------------------------


def settings(tmp_path: Path, **changes: object) -> Settings:
    values = {
        "token": "kept",
        "host": "127.0.0.1",
        "port": 8765,
        "roots": (tmp_path,),
        "allow_full": True,
        "directory": tmp_path / "gw",
        "log_level": "info",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def test_a_restart_with_no_flags_keeps_the_recorded_settings(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)
    recorded = settings(tmp_path, port=9123, token="secret", allow_full=False, log_level="debug")

    kept = settings_from([], base=recorded)

    assert (kept.host, kept.port, kept.token) == ("127.0.0.1", 9123, "secret")
    assert kept.roots == recorded.roots and kept.directory == recorded.directory
    assert kept.allow_full is False and kept.log_level == "debug"


def test_a_flag_given_to_a_restart_wins_over_the_recorded_one(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)
    recorded = settings(tmp_path, port=9123, token="secret", allow_full=True)

    changed = settings_from(["--port", "9000", "--no-full"], base=recorded)

    assert changed.port == 9000 and changed.token == "secret"
    assert changed.allow_full is False


def test_a_background_start_keeps_the_token_in_the_environment_not_on_the_command_line(tmp_path, monkeypatch):
    recorded = settings(tmp_path, token="secret")
    spawned: list[tuple[list[str], dict[str, object]]] = []

    class Child:
        pid = 4321

    def fake_popen(arguments: list[str], **options: object) -> Child:
        spawned.append((arguments, options))
        return Child()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    cli.spawn(recorded)

    arguments, options = spawned[0]
    assert "--token" not in arguments and "secret" not in " ".join(arguments)
    assert options["env"][TOKEN_VARIABLE] == "secret"  # type: ignore[index]
    assert arguments[:4] == [cli.sys.executable, "-m", cli.GATEWAY_MODULE, "serve"]


def test_start_does_not_start_a_second_gateway(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: "/venv/bin/python -m zettcode.gateway.cli serve")
    starts: list[Settings] = []
    monkeypatch.setattr(cli, "spawn", starts.append)

    assert cli.start(recorded) == 0
    assert starts == []
    assert "already running" in capsys.readouterr().out


def test_start_refuses_when_the_recorded_process_cannot_be_read_but_is_still_there(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli, "still_there", lambda pid: True)
    monkeypatch.setattr(cli, "spawn", lambda settings: pytest.fail("nothing may be started"))

    assert cli.start(recorded) == 1
    assert "could not be read" in capsys.readouterr().err


def test_start_replaces_the_record_of_a_process_that_is_gone(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)

    class Child:
        pid = 4321

        def poll(self) -> None:
            return None

    monkeypatch.setattr(runfile, "read", lambda directory: Running(1111, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli, "still_there", lambda pid: False)
    monkeypatch.setattr(cli, "spawn", lambda settings: Child())
    monkeypatch.setattr(cli, "wait_serving", lambda settings, process: True)

    assert cli.start(recorded) == 0
    assert "running in the background (pid 4321)" in capsys.readouterr().out


def test_start_spawns_one_and_says_where_it_is(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)

    class Child:
        pid = 4321

        def poll(self) -> None:
            return None

    monkeypatch.setattr(runfile, "read", lambda directory: None)
    monkeypatch.setattr(cli, "spawn", lambda settings: Child())
    monkeypatch.setattr(cli, "wait_serving", lambda settings, process: True)

    assert cli.start(recorded) == 0
    assert "running in the background (pid 4321)" in capsys.readouterr().out


def test_a_start_that_never_listens_reports_the_log(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)

    class Child:
        pid = 4321

        def poll(self) -> None:
            return None

    monkeypatch.setattr(runfile, "read", lambda directory: None)
    monkeypatch.setattr(cli, "spawn", lambda settings: Child())
    monkeypatch.setattr(cli, "wait_serving", lambda settings, process: False)

    assert cli.start(recorded) == 1
    assert "did not start" in capsys.readouterr().err


def test_stop_ends_a_gateway_that_is_still_there(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: "/venv/bin/python -m zettcode.gateway.cli serve")
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: killed.append((pid, number)))
    monkeypatch.setattr(cli, "_wait_gone", lambda pid, seconds: True)

    assert cli.stop(recorded.directory) == 0
    assert killed == [(4321, cli.signal.SIGTERM)]
    assert "stopped the gateway (4321)" in capsys.readouterr().out


def test_stop_of_a_pinned_process_that_is_not_a_gateway_does_nothing(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: "vim gateway.txt")
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: pytest.fail("nothing may be signalled"))

    assert cli.stop(recorded.directory) == 0
    assert "not running" in capsys.readouterr().out


def test_stop_of_a_process_it_cannot_read_but_that_is_still_there_keeps_the_record(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli, "still_there", lambda pid: True)
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: pytest.fail("an unread process is not signalled"))

    assert cli.stop(recorded.directory) == 1
    assert "could not be read" in capsys.readouterr().err


def test_stop_clears_the_record_of_a_process_that_is_gone(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli, "still_there", lambda pid: False)

    assert cli.stop(recorded.directory) == 0
    assert "not running" in capsys.readouterr().out


def test_force_leaves_a_pid_that_became_another_program_alone(monkeypatch):
    monkeypatch.setattr(cli, "_wait_gone", lambda pid, seconds: False)
    monkeypatch.setattr(cli, "command_line", lambda pid: "vim gateway.txt")
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: pytest.fail("nothing may be killed"))

    assert cli._force(4321, 0.0) is True


def test_force_does_not_kill_a_process_it_can_no_longer_identify(monkeypatch):
    monkeypatch.setattr(cli, "_wait_gone", lambda pid, seconds: False)
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: pytest.fail("nothing may be killed"))

    assert cli._force(4321, 0.0) is False


def test_restart_keeps_the_recorded_token_over_an_environment_one(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_VARIABLE, "from-env")
    recorded = settings(tmp_path, token="kept")

    assert settings_from([], base=recorded).token == "kept"
    assert settings_from(["--token", "new"], base=recorded).token == "new"


def test_full_undoes_a_recorded_no_full(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)
    recorded = settings(tmp_path, allow_full=False)

    assert settings_from(["--full"], base=recorded).allow_full is True


def test_restart_says_why_it_could_not_stop(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    monkeypatch.setattr(cli, "command_line", lambda pid: None)
    monkeypatch.setattr(cli, "still_there", lambda pid: True)

    assert cli.restart(recorded) == 1
    assert "could not be read" in capsys.readouterr().err


def test_stop_does_not_call_a_gateway_stopped_when_its_command_line_goes_unreadable(tmp_path, monkeypatch, capsys):
    recorded = settings(tmp_path)
    monkeypatch.setattr(runfile, "read", lambda directory: Running(4321, recorded))
    answers = iter(["/venv/bin/python -m zettcode.gateway.cli serve", None])
    monkeypatch.setattr(cli, "command_line", lambda pid: next(answers, None))
    monkeypatch.setattr(cli, "still_there", lambda pid: True)
    monkeypatch.setattr(cli.os, "kill", lambda pid, number: None)
    monkeypatch.setattr(cli, "STOP_GRACE", 0.0)
    monkeypatch.setattr(cli, "STOP_FORCE", 0.0)

    assert cli.stop(recorded.directory) == 1
    assert "did not stop" in capsys.readouterr().err


def test_restart_stops_then_starts_and_a_failed_stop_stops_there(tmp_path, monkeypatch):
    recorded = settings(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(cli, "stop", lambda directory, *, quiet=False: order.append("stop") or 0)
    monkeypatch.setattr(cli, "start", lambda settings: order.append("start") or 0)

    assert cli.restart(recorded) == 0 and order == ["stop", "start"]

    order.clear()
    monkeypatch.setattr(cli, "stop", lambda directory, *, quiet=False: order.append("stop") or 1)
    assert cli.restart(recorded) == 1 and order == ["stop"]


def test_only_a_gateway_command_line_is_recognised():
    assert cli._is_gateway("/venv/bin/python -m zettcode.gateway.cli serve")
    assert cli._is_gateway("/venv/bin/python3 /venv/bin/zettcode gateway --port 8765")
    assert cli._is_gateway('"C:\\venv\\Scripts\\zettcode.exe" gateway')
    assert not cli._is_gateway("/venv/bin/zettcode-server --port 3290")
    assert not cli._is_gateway("vim gateway.txt")
    assert not cli._is_gateway("/venv/bin/python -m zettcode.broker")


def test_the_action_words_dispatch_without_serving(tmp_path, monkeypatch):
    done: list[str] = []
    monkeypatch.setattr(cli, "stop", lambda directory: done.append("stop") or 0)
    monkeypatch.setattr(cli, "restart", lambda settings: done.append("restart") or 0)
    monkeypatch.setattr(cli, "start", lambda settings: done.append("start") or 0)
    monkeypatch.setattr(cli, "serve", lambda settings: done.append("serve"))
    monkeypatch.setattr(cli, "settings_from", lambda argv, base=None: settings(tmp_path))
    monkeypatch.setattr(cli, "default_directory", lambda: tmp_path / "gw")

    for words, expected in ((["stop"], "stop"), (["start"], "start"), (["restart"], "restart"), ([], "serve")):
        if words:
            with pytest.raises(SystemExit):
                cli.main(words)
        else:
            cli.main(words)
        assert done[-1] == expected
