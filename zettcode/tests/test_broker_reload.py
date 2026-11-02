"""A broker older than the code that is starting is replaced by itself, and only when that strands nothing."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from broker_helpers import hold_lock
from zettcode.broker import cli, reload
from zettcode.broker.files import Note, lock_path, write_note
from zettcode.broker.protocol import PROTOCOL_VERSION


def a_broker(directory: Path, version: int):
    """A process that holds the broker's lock, and a note that says what it speaks."""
    directory.mkdir(parents=True, exist_ok=True)
    holder = hold_lock(lock_path(directory))
    write_note(directory, Note(holder.pid, 5555, "tok", version))
    return holder


@pytest.fixture
def spawned(monkeypatch) -> list[list[str]]:
    """Record what the module would start, without touching ``subprocess`` itself (a test's own holder needs it)."""
    calls: list[list[str]] = []
    stand_in = SimpleNamespace(
        DEVNULL=subprocess.DEVNULL,
        DETACHED_PROCESS=0,
        CREATE_NEW_PROCESS_GROUP=0,
        CREATE_NO_WINDOW=0,
        Popen=lambda args, **options: calls.append(args),
    )
    monkeypatch.setattr(reload, "subprocess", stand_in)
    return calls


def test_only_a_running_broker_of_an_older_protocol_is_outdated(tmp_path: Path):
    assert reload.outdated(tmp_path) is None, "nothing running"
    holder = a_broker(tmp_path, PROTOCOL_VERSION - 1)
    try:
        found = reload.outdated(tmp_path)
        assert found is not None and found.version == PROTOCOL_VERSION - 1
        write_note(tmp_path, Note(holder.pid, 5555, "tok", PROTOCOL_VERSION))
        assert reload.outdated(tmp_path) is None, "current"
        write_note(tmp_path, Note(holder.pid, 5555, "tok", PROTOCOL_VERSION + 1))
        assert reload.outdated(tmp_path) is None, "newer: an older program does not undo an upgrade"
    finally:
        holder.kill()
        holder.wait()
    write_note(tmp_path, Note(holder.pid, 5555, "tok", PROTOCOL_VERSION - 1))
    assert reload.outdated(tmp_path) is None, "a note that outlived its broker is not a broker"


def test_starting_zettcode_with_an_old_broker_running_starts_one_reload_in_the_background(tmp_path: Path, spawned):
    holder = a_broker(tmp_path, PROTOCOL_VERSION - 1)
    try:
        assert reload.check_in_background(tmp_path, now=1000.0) is True
        assert len(spawned) == 1 and spawned[0][-2:] == ["broker", "reload"]
        assert reload.check_in_background(tmp_path, now=1010.0) is False, "not again at every start"
        assert len(spawned) == 1
        assert reload.check_in_background(tmp_path, now=1000.0 + reload.RETRY_AFTER + 1) is True, "but later it is"
    finally:
        holder.kill()
        holder.wait()


@pytest.mark.parametrize("version", [PROTOCOL_VERSION, PROTOCOL_VERSION + 1])
def test_a_current_or_newer_broker_starts_nothing(tmp_path: Path, spawned, version: int):
    holder = a_broker(tmp_path, version)
    try:
        assert reload.check_in_background(tmp_path) is False and spawned == []
    finally:
        holder.kill()
        holder.wait()


def test_no_broker_at_all_starts_nothing_and_leaves_no_trace(tmp_path: Path, spawned):
    assert reload.check_in_background(tmp_path / "not-there") is False
    assert spawned == [] and not (tmp_path / "not-there").exists()


def test_a_check_that_cannot_run_never_stops_zettcode_from_starting(tmp_path: Path, monkeypatch):
    holder = a_broker(tmp_path, PROTOCOL_VERSION - 1)

    def fails(*args, **options):
        raise OSError("no processes for you")

    monkeypatch.setattr(reload, "subprocess", SimpleNamespace(DEVNULL=subprocess.DEVNULL, Popen=fails))
    try:
        assert reload.check_in_background(tmp_path) is False
    finally:
        holder.kill()
        holder.wait()


# -- the command the background process runs --------------------------------------------------------------------
class Agents(cli.Companions):
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.stopped = False

    def listing(self) -> list[str]:
        return self.lines

    def stop(self) -> list[str]:
        self.stopped = True
        return []

    def start(self) -> list[tuple[bool, str]]:
        return []


def test_reload_replaces_an_old_broker_and_says_so(tmp_path: Path, monkeypatch, capsys):
    order: list[str] = []
    old = Note(77, 1, "t", PROTOCOL_VERSION - 1)
    write_note(tmp_path, old)
    monkeypatch.setattr(cli, "outdated", lambda directory: old)
    monkeypatch.setattr(cli, "stop", lambda directory, expect=None: order.append("stop") or 0)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or 0)

    assert cli.reload(tmp_path, Agents([])) == 0 and order == ["stop", "start"]
    assert "replaced broker 77" in capsys.readouterr().out


def test_reload_never_stops_background_agents_and_says_how_to_do_it_knowingly(tmp_path: Path, monkeypatch, capsys):
    order: list[str] = []
    agents = Agents(["parser · working"])
    monkeypatch.setattr(cli, "outdated", lambda directory: Note(77, 1, "t", PROTOCOL_VERSION - 1))
    monkeypatch.setattr(cli, "stop", lambda directory: order.append("stop") or 0)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or 0)

    assert cli.reload(tmp_path, agents) == 0
    assert order == [] and agents.stopped is False
    assert "zettcode broker restart" in capsys.readouterr().out


def test_reload_does_nothing_and_says_nothing_when_the_broker_is_current(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "outdated", lambda directory: None)
    monkeypatch.setattr(cli, "stop", lambda directory: pytest.fail("nothing to replace"))

    assert cli.reload(tmp_path, Agents(["x"])) == 0 and capsys.readouterr().out == ""


def test_reload_that_cannot_stop_the_old_broker_does_not_start_a_second(tmp_path: Path, monkeypatch):
    order: list[str] = []
    old = Note(77, 1, "t", PROTOCOL_VERSION - 1)
    write_note(tmp_path, old)
    monkeypatch.setattr(cli, "outdated", lambda directory: old)
    monkeypatch.setattr(cli, "stop", lambda directory, expect=None: order.append("stop") or 1)
    monkeypatch.setattr(cli, "start", lambda directory: order.append("start") or 0)

    assert cli.reload(tmp_path, Agents([])) == 1 and order == ["stop"]


def test_the_reload_word_is_one_of_the_brokers_actions(tmp_path: Path, monkeypatch):
    seen: list[Path] = []
    monkeypatch.setenv("ZETTCODE_BROKER_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "reload", lambda directory, companions=None: seen.append(directory) or 0)

    assert cli.broker_program(["reload"]) == 0 and seen == [tmp_path]


def test_a_reload_that_finds_another_start_got_there_first_does_not_stop_the_new_broker(tmp_path: Path, monkeypatch):
    """The real ``stop`` compares the note itself, so a broker put there since is never the one that is ended."""
    old = Note(77, 1, "t", PROTOCOL_VERSION - 1)
    monkeypatch.setattr(cli, "outdated", lambda directory: old)
    monkeypatch.setattr(cli.process, "end", lambda *a, **k: pytest.fail("the new broker must not be ended"))
    monkeypatch.setattr(cli, "start", lambda directory: pytest.fail("nothing is to be started: one is running"))

    holder = a_broker(tmp_path, PROTOCOL_VERSION)  # the broker the other start put in its place (its pid is not 77)
    try:
        assert cli.stop(tmp_path, expect=77) == 0, "asked to end a broker that is not the one running: nothing to do"
        assert cli.reload(tmp_path, Agents([])) == 0
        assert holder.poll() is None and cli.running(tmp_path), "and the one that is running was left alone"
    finally:
        holder.kill()
        holder.wait()


def test_stop_with_no_expectation_still_ends_whatever_is_running(tmp_path: Path, monkeypatch):
    ended: list[int] = []
    holder = a_broker(tmp_path, PROTOCOL_VERSION)
    monkeypatch.setattr(cli.process, "end", lambda pid, module, released: ended.append(pid) or True)
    try:
        assert cli.stop(tmp_path) == 0 and ended == [holder.pid], "a person who says stop means it"
        ended.clear()
        assert cli.stop(tmp_path, expect=holder.pid) == 0 and ended == [holder.pid], "and the pid it names is ended"
    finally:
        holder.kill()
        holder.wait()


def test_a_spawn_that_fails_is_not_waited_ten_minutes_for(tmp_path: Path):
    holder = a_broker(tmp_path, PROTOCOL_VERSION - 1)

    def fails(*args, **options):
        raise OSError("no processes for you")

    real = reload.subprocess
    reload.subprocess = SimpleNamespace(DEVNULL=subprocess.DEVNULL, Popen=fails)  # type: ignore[assignment]
    try:
        assert reload.check_in_background(tmp_path, now=1.0) is False
        assert not (tmp_path / reload.TRIED_FILE).exists(), "so that the next start tries again"
    finally:
        reload.subprocess = real  # type: ignore[assignment]
        holder.kill()
        holder.wait()


def test_what_the_background_reload_says_goes_to_the_brokers_log(tmp_path: Path):
    """The reload runs with no terminal, so its words (agents were on it; it was replaced) must be somewhere readable."""
    from zettcode.broker.files import log_path

    seen: list[dict] = []

    def popen(args, **options):
        seen.append(options)

    holder = a_broker(tmp_path, PROTOCOL_VERSION - 1)
    real = reload.subprocess
    reload.subprocess = SimpleNamespace(  # type: ignore[assignment]
        DEVNULL=subprocess.DEVNULL, DETACHED_PROCESS=0, CREATE_NEW_PROCESS_GROUP=0, CREATE_NO_WINDOW=0, Popen=popen
    )
    try:
        assert reload.check_in_background(tmp_path, now=5.0) is True
    finally:
        reload.subprocess = real  # type: ignore[assignment]
        holder.kill()
        holder.wait()

    assert log_path(tmp_path).exists(), "the log it is appended to is made"
    assert seen[0]["stdout"] is seen[0]["stderr"] and seen[0]["stdout"] is not subprocess.DEVNULL
