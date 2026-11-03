"""``zettcode broker``: start, stop and restart, decided from the lock and the note a broker leaves.

The control flow is tested with the lock and the spawned process stood in for, because both are what the broker tests
already drive for real; what is checked here is which of them the command looks at and what it says.
"""

from __future__ import annotations

from pathlib import Path

from zettcode.broker import cli
from zettcode.broker.files import Note, read_note, write_note
from zettcode.broker.protocol import PROTOCOL_VERSION


def note(pid: int = 4321, port: int = 5555, token: str = "tok") -> Note:
    return Note(pid, port, token, PROTOCOL_VERSION)


def test_start_spawns_a_broker_and_reports_where_it_listens(tmp_path: Path, monkeypatch, capsys):
    state = {"running": False}
    spawned: list[Path] = []

    def spawn(directory: Path) -> None:
        spawned.append(directory)
        state["running"] = True
        write_note(directory, note())

    monkeypatch.setattr(cli, "running", lambda directory: state["running"])
    monkeypatch.setattr(cli, "spawn_broker", spawn)

    assert cli.start(tmp_path) == 0
    assert spawned == [tmp_path]
    said = capsys.readouterr().out
    assert "4321" in said and "5555" in said


def test_start_leaves_a_broker_that_is_already_running_alone(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note())
    spawned: list[Path] = []
    monkeypatch.setattr(cli, "running", lambda directory: True)
    monkeypatch.setattr(cli, "spawn_broker", spawned.append)

    assert cli.start(tmp_path) == 0
    assert spawned == []
    assert "already running" in capsys.readouterr().out


def test_a_start_that_never_says_where_it_listens_is_a_failure(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "running", lambda directory: False)
    monkeypatch.setattr(cli, "spawn_broker", lambda directory: None)
    monkeypatch.setattr(cli, "START_WAIT", 0.05)

    assert cli.start(tmp_path) == 1
    assert "did not start" in capsys.readouterr().err


def test_start_ignores_a_note_left_by_a_broker_that_died(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note(pid=1111, port=2222, token="old"))
    state = {"running": False}

    def spawn(directory: Path) -> None:
        state["running"] = True
        write_note(directory, note(pid=3333, port=4444, token="new"))

    monkeypatch.setattr(cli, "running", lambda directory: state["running"])
    monkeypatch.setattr(cli, "spawn_broker", spawn)

    assert cli.start(tmp_path) == 0
    said = capsys.readouterr().out
    assert "3333" in said and "4444" in said and "1111" not in said


def test_a_stale_note_that_never_becomes_a_new_broker_is_not_reported_as_one(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note(pid=1111, port=2222, token="old"))
    monkeypatch.setattr(cli, "running", lambda directory: False)
    monkeypatch.setattr(cli, "spawn_broker", lambda directory: None)
    monkeypatch.setattr(cli, "START_WAIT", 0.05)

    assert cli.start(tmp_path) == 1
    assert "1111" not in capsys.readouterr().out


def test_a_spawn_that_cannot_run_is_a_failure(tmp_path: Path, monkeypatch, capsys):
    def spawn(directory: Path) -> None:
        raise OSError("no such interpreter")

    monkeypatch.setattr(cli, "running", lambda directory: False)
    monkeypatch.setattr(cli, "spawn_broker", spawn)

    assert cli.start(tmp_path) == 1
    assert "could not be started" in capsys.readouterr().err


def test_stop_asks_the_broker_the_note_names_to_end(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note())
    asked: list[tuple[int, str]] = []
    monkeypatch.setattr(cli, "running", lambda directory: True)
    monkeypatch.setattr(cli.process, "end", lambda pid, module, *, released: asked.append((pid, module)) or True)

    assert cli.stop(tmp_path) == 0
    assert asked == [(4321, "zettcode.broker")]
    assert "stopped broker 4321" in capsys.readouterr().out


def test_stop_stops_a_broker_whoever_it_says_it_is(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, Note(4321, 5555, "tok", PROTOCOL_VERSION + 5))
    monkeypatch.setattr(cli, "running", lambda directory: True)
    killed: list[int] = []
    monkeypatch.setattr(cli.process, "end", lambda pid, module, *, released: killed.append(pid) or True)

    assert cli.stop(tmp_path) == 0
    assert killed == [4321], "an explicit stop does not wait for the version to agree"


def test_stop_that_could_not_end_the_broker_says_so(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note())
    monkeypatch.setattr(cli, "running", lambda directory: True)
    monkeypatch.setattr(cli.process, "end", lambda pid, module, *, released: False)

    assert cli.stop(tmp_path) == 1
    assert "did not stop" in capsys.readouterr().err


def test_stop_with_nothing_running_clears_a_note_left_behind(tmp_path: Path, monkeypatch, capsys):
    write_note(tmp_path, note())
    monkeypatch.setattr(cli, "running", lambda directory: False)

    assert cli.stop(tmp_path) == 0
    assert read_note(tmp_path) is None
    assert "not running" in capsys.readouterr().out


def test_a_broker_that_holds_the_lock_without_a_note_is_not_guessed_at(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "running", lambda directory: True)

    assert cli.stop(tmp_path) == 1
    assert "cannot be identified" in capsys.readouterr().err


def test_restart_stops_then_starts_only_when_a_broker_is_running(tmp_path: Path, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(cli, "running", lambda directory: True)
    monkeypatch.setattr(cli, "stop", lambda directory: order.append("stop") or 0)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or 0)

    assert cli.restart(tmp_path) == 0 and order == ["stop", "start"]

    order.clear()
    monkeypatch.setattr(cli, "running", lambda directory: False)
    assert cli.restart(tmp_path) == 0 and order == ["start"]


def test_a_restart_that_could_not_stop_does_not_start_a_second_broker(tmp_path: Path, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(cli, "running", lambda directory: True)
    monkeypatch.setattr(cli, "stop", lambda directory: order.append("stop") or 1)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or 0)

    assert cli.restart(tmp_path) == 1 and order == ["stop"]


def test_the_action_word_picks_the_work_in_the_brokers_own_directory(tmp_path: Path, monkeypatch):
    used: list[Path] = []
    monkeypatch.setattr(cli, "broker_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "stop", lambda directory: used.append(directory) or 0)

    assert cli.broker_program(["stop"]) == 0
    assert used == [tmp_path]


# -- a restart and the background agents that live on the broker ---------------------------------------------------


class FakeCompanions(cli.Companions):
    def __init__(self, lines: list[str], order: list[str], *, fail: bool = False) -> None:
        self.lines, self.order, self.fail = lines, order, fail

    def listing(self) -> list[str]:
        return self.lines

    def stop(self) -> list[str]:
        self.order.append("stop-agents")
        return [f"{line}  stopped" for line in self.lines]

    def start(self) -> list[tuple[bool, str]]:
        self.order.append("start-agents")
        return [(not self.fail, f"{line}  again") for line in self.lines]


def wired(monkeypatch, order: list[str], *, running: bool = True, stop_status: int = 0, start_status: int = 0):
    monkeypatch.setattr(cli, "running", lambda directory: running)
    monkeypatch.setattr(cli, "stop", lambda directory: order.append("stop") or stop_status)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or start_status)


def test_a_restart_with_agents_running_asks_and_on_yes_stops_them_then_the_broker_then_starts_both(
    tmp_path: Path, monkeypatch, capsys
):
    order: list[str] = []
    wired(monkeypatch, order)
    asked: list[str] = []

    status = cli.restart(
        tmp_path,
        FakeCompanions(["a  review  /w"], order),
        ask=lambda prompt: asked.append(prompt) or "y",
        interactive=lambda: True,
    )

    assert status == 0 and len(asked) == 1
    assert order == ["stop-agents", "stop", "start", "start-agents"]
    assert "a  review  /w" in capsys.readouterr().out


def test_saying_no_changes_nothing(tmp_path: Path, monkeypatch, capsys):
    order: list[str] = []
    wired(monkeypatch, order)

    status = cli.restart(tmp_path, FakeCompanions(["a  x  /w"], order), ask=lambda prompt: "", interactive=lambda: True)

    assert status == 1 and order == []
    assert "nothing was changed" in capsys.readouterr().out


def test_with_nobody_to_ask_and_no_yes_nothing_is_stopped(tmp_path: Path, monkeypatch, capsys):
    order: list[str] = []
    wired(monkeypatch, order)

    status = cli.restart(tmp_path, FakeCompanions(["a  x  /w"], order), interactive=lambda: False)

    assert status == 1 and order == []
    assert "--yes" in capsys.readouterr().err


def test_yes_does_not_ask(tmp_path: Path, monkeypatch):
    order: list[str] = []
    wired(monkeypatch, order)

    def never(prompt: str) -> str:
        raise AssertionError("asked")

    status = cli.restart(tmp_path, FakeCompanions(["a  x  /w"], order), assume_yes=True, ask=never)

    assert status == 0 and order == ["stop-agents", "stop", "start", "start-agents"]


def test_no_agents_means_no_question_and_the_old_behaviour(tmp_path: Path, monkeypatch):
    order: list[str] = []
    wired(monkeypatch, order)

    def never(prompt: str) -> str:
        raise AssertionError("asked")

    assert cli.restart(tmp_path, FakeCompanions([], order), ask=never) == 0
    assert order == ["stop", "start"]


def test_when_the_broker_cannot_be_stopped_the_agents_are_brought_back_and_it_fails(tmp_path: Path, monkeypatch):
    order: list[str] = []
    wired(monkeypatch, order, stop_status=1)

    assert cli.restart(tmp_path, FakeCompanions(["a  x  /w"], order), assume_yes=True) == 1
    assert order == ["stop-agents", "stop", "start-agents"]


def test_an_agent_that_cannot_be_started_again_makes_the_restart_a_failure_and_is_reported(
    tmp_path: Path, monkeypatch, capsys
):
    order: list[str] = []
    wired(monkeypatch, order)

    assert cli.restart(tmp_path, FakeCompanions(["a  x  /w"], order, fail=True), assume_yes=True) == 1
    assert "a  x  /w  again" in capsys.readouterr().err


def test_the_yes_flag_reaches_the_restart(tmp_path: Path, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(cli, "broker_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cli, "restart", lambda directory, companions=None, *, assume_yes=False: seen.append(assume_yes) or 0
    )

    assert cli.broker_program(["restart", "--yes"]) == 0 and cli.broker_program(["restart"]) == 0
    assert seen == [True, False]
