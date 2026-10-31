"""The daemons a machine is running: their records, the process around them, and the command that lists them."""

from __future__ import annotations

import json
import os
import time

import pytest

from zettcode.daemon import process
from zettcode.daemon.cli import daemon_program
from zettcode.daemon.run import Inbox, Options, _client
from zettcode.daemon.state import Record, Registry, State
from zettcode.sdk.types import IncomingMessage

MODEL = '[[models]]\nmodel = "fake"\ntoken = "t"\n'


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A config, a daemon folder and a broker folder of this test's own; nothing touches the reader's."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(MODEL, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemon"))
    monkeypatch.setenv("ZETTCODE_BROKER_DIR", str(tmp_path / "broker"))
    monkeypatch.setenv("ZETTCODE_BROKER_IDLE", "1")
    return workspace


def message(text: str = "hello") -> IncomingMessage:
    return IncomingMessage(sender_id="sender", sender="someone", text=text)


def state_for(home, *, pid: int | None = None, status: str = "idle") -> State:
    return State(
        session_id="01a1",
        workspace=str(home),
        pid=pid if pid is not None else os.getpid(),
        status=status,
        token="t",
        started_at=1.0,
    )


# -- the record ----------------------------------------------------------------------------------------------------
def test_a_state_round_trips_and_names_the_folder_it_is_in(tmp_path):
    folder = tmp_path / "daemon" / "ws" / "01a1"
    state = state_for(tmp_path)

    state.save(folder)

    assert State.load(folder) == state
    assert (folder / "state.json").read_text(encoding="utf-8").startswith("{")


def test_a_state_from_another_protocol_or_nonsense_is_not_believed(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "state.json").write_text('{"session_id": "x", "protocol": 999}', encoding="utf-8")

    assert State.load(folder) is None
    (folder / "state.json").write_text("not json", encoding="utf-8")
    assert State.load(folder) is None


def test_a_record_is_alive_only_while_its_process_and_its_heartbeat_are(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))

    assert not record.alive, "a pid with no heartbeat is not proof of anything"

    record.beat()
    assert Registry().record(home, "01a1").alive

    long_ago = time.time() - 3600
    os.utime(record.folder / "heartbeat", (long_ago, long_ago))
    assert not Registry().record(home, "01a1").alive, "a heartbeat that stopped long ago is a wedged process"

    record.save(state_for(home, pid=2**22 + 7))
    assert not Registry().record(home, "01a1").alive, "a pid nobody has is not a daemon"


def test_the_registry_finds_every_workspace_and_stopping_a_dead_one_removes_its_record(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home, pid=2**22 + 7))
    record.beat()

    found = Registry().all()

    assert [one.session_id for one in found] == ["01a1"]
    assert found[0].dead and found[0].status == "dead"
    assert process.Daemons().stop(found[0]) == "was already gone; its record was removed"
    assert Registry().all() == ()


def test_a_folder_that_never_wrote_its_state_is_still_listed_and_removable(home):
    folder = Registry().workspace(home, create=True) / "01a1"
    folder.mkdir()
    (folder / "log").write_text("died", encoding="utf-8")

    found = Registry().all()

    assert [one.session_id for one in found] == ["01a1"] and found[0].state is None
    assert found[0].status == "dead"


def test_a_record_leaves_the_workspace_folder_and_its_note(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home, pid=1))

    record.remove()

    assert not record.folder.exists()
    assert (Registry().workspace(home) / "workspace.txt").is_file()


# -- the inbox -----------------------------------------------------------------------------------------------------
def test_the_inbox_starts_one_message_and_queues_the_rest_up_to_four():
    started: list[IncomingMessage] = []
    inbox = Inbox(started.append)

    assert inbox.offer(message("one")).disposition == "started"
    for index in range(2, 6):
        receipt = inbox.offer(message(str(index)))
        assert receipt.accepted and receipt.disposition == "queued"

    refused = inbox.offer(message("six"))
    assert not refused.accepted and "4 messages waiting" in refused.reason
    assert [item.text for item in started] == ["one"]
    assert inbox.waiting == 4


def test_the_inbox_hands_back_one_at_a_time_and_is_idle_only_when_empty():
    started: list[IncomingMessage] = []
    inbox = Inbox(started.append)
    inbox.offer(message("one"))
    inbox.offer(message("two"))

    assert inbox.done() is not None, "the next message runs"
    assert inbox.busy and inbox.waiting == 0, "and the daemon stays busy while it does"
    assert inbox.done() is None
    assert not inbox.busy


# -- the process ---------------------------------------------------------------------------------------------------
def test_a_started_daemon_is_listed_alive_and_stopping_it_removes_the_record(home, capsys):
    record = process.Daemons().start(home)
    try:
        assert record.status == "idle" and record.state is not None
        assert record.state.workspace == str(home.resolve())
        listed = Registry().all()
        assert [one.session_id for one in listed] == [record.session_id]
        assert listed[0].alive and listed[0].status == "idle"

        assert daemon_program(["list", "--json"]) == 0
        shown = json.loads(capsys.readouterr().out)
        assert shown[0]["session"] == record.session_id and shown[0]["status"] == "idle"
    finally:
        found = Registry().find(record.session_id)
        assert found is not None
        assert process.Daemons().stop(found) == "stopped"

    assert Registry().all() == (), "the record goes"
    assert not any(folder.name == record.session_id for folder in (home.parent / "daemon").rglob("*"))


def test_a_daemon_that_cannot_start_says_why_and_leaves_no_record(home, monkeypatch, tmp_path):
    broken = tmp_path / "broken.toml"
    broken.write_text("[[models]]\nmodel = 3\n", encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(broken))

    with pytest.raises(process.SpawnFailed) as raised:
        process.Daemons().start(home)

    assert "zettcode daemon:" in str(raised.value)
    assert Registry().all() == (), "a start that failed leaves nothing to clean up"


def test_kill_reports_a_session_no_daemon_has(home, capsys):
    assert daemon_program(["kill", "nope"]) == 1
    assert "no daemon with that session" in capsys.readouterr().out


def test_list_says_so_when_nothing_runs(home, capsys):
    assert daemon_program(["list"]) == 0
    assert "No daemons" in capsys.readouterr().out


def test_a_daemon_runs_at_the_shell_level_it_was_started_with(home, monkeypatch):
    """The level is a choice: `full` unless it said otherwise, and never `ask`, which nobody is there to answer."""
    seen: list[dict[str, object]] = []

    class Recorder:
        def __init__(self, workspace, **settings):
            seen.append({"workspace": workspace, **settings})

    monkeypatch.setattr("zettcode.sdk.client.Client", Recorder)

    _client(Options(workspace=home, token="t"))
    _client(Options(workspace=home, token="t", permission="safe"))

    assert seen[0]["permission"] == "full", "the default, for a daemon that fetched nothing and approved nothing"
    assert seen[1]["permission"] == "safe", "a sandboxed daemon is a sandboxed daemon"
    assert all(entry["sessions_enabled"] is True for entry in seen), "being messaged is what a daemon is for"
    assert all(entry["ask_user_enabled"] is False for entry in seen), "nobody can answer a question here"


def test_ask_is_not_a_permission_a_daemon_can_be_given():
    """`ask` needs a reader, so the command refuses it before anything starts."""
    with pytest.raises(SystemExit) as raised:
        daemon_program(["spawn", "--permission", "ask"])

    assert raised.value.code == 2


def test_the_process_spawn_starts_refuses_ask_as_well(home):
    """`spawn` is not the only door into `run`: the hidden command refuses it too."""
    with pytest.raises(SystemExit) as raised:
        daemon_program(["run", "--token", "t", "--workspace", str(home), "--permission", "ask"])

    assert raised.value.code == 2


def test_a_start_at_a_level_nobody_can_give_is_refused_before_a_process_is_made(home):
    with pytest.raises(process.SpawnFailed) as raised:
        process.Daemons().start(home, permission="ask")

    assert "one of deny, safe, full" in str(raised.value)
    assert Registry().all() == ()


def test_a_start_in_a_directory_that_is_not_there_says_so_rather_than_raising(home, tmp_path):
    """Popen's own refusal for a missing cwd is a FileNotFoundError, which says nothing about the argument."""
    missing = tmp_path / "nowhere"

    with pytest.raises(process.SpawnFailed) as raised:
        process.Daemons().start(missing)

    assert "is not a directory" in str(raised.value)
    assert Registry().all() == ()


def test_a_label_given_at_the_start_is_recorded_and_listed(home, capsys):
    """A spawn says what the daemon is for; `list` shows it beside the session, so a machine with several is legible."""
    record = process.Daemons().start(home, name="reviewer")
    try:
        assert record.state is not None and record.state.name == "reviewer"
        assert Registry().find(record.session_id).state.name == "reviewer"

        assert daemon_program(["list"]) == 0
        shown = capsys.readouterr().out
        assert "NAME" in shown and "reviewer" in shown

        assert daemon_program(["list", "--json"]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed[0]["name"] == "reviewer"
    finally:
        found = Registry().find(record.session_id)
        assert found is not None
        assert process.Daemons().stop(found) == "stopped"


def test_model_lists_what_a_spawn_can_be_given(home, capsys):
    """`daemon model` shows the names `spawn --model` takes, and which one a daemon would use by itself."""
    assert daemon_program(["model", "-w", str(home)]) == 0

    shown = capsys.readouterr().out
    assert "fake (default)" in shown and "128,000" in shown
    assert "spawn --model" in shown, "the reader is told what to do with the names"


def test_model_json_is_what_a_program_reads(home, capsys):
    assert daemon_program(["model", "-w", str(home), "--json"]) == 0

    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["name"] == "fake" and listed[0]["default"] is True
    assert listed[0]["efforts"][0] == "off"


def test_model_without_a_configuration_says_why(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "absent.toml"))

    assert daemon_program(["model", "-w", str(tmp_path)]) == 1

    assert "zettcode daemon:" in capsys.readouterr().err


def test_a_record_points_at_its_own_log(home):
    record: Record = Registry().record(home, "01a1", create=True)

    record.log("something happened")

    assert "something happened" in record.log_path.read_text(encoding="utf-8")


# -- a reader's chat window ------------------------------------------------------------------------------------
class _Stream:
    """What ``session.prompt`` and ``session.relay`` return: iterable, an async context, and a result at the end."""

    def __init__(self, text: str) -> None:
        self.result = type("Result", (), {"text": text})()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _Session:
    id = "01a1"
    title = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def prompt(self, text):
        self.calls.append(("prompt", text))
        return _Stream("final answer")

    def relay(self, incoming):
        self.calls.append(("relay", incoming.text))
        return _Stream("ignored")


class _Client:
    def __init__(self) -> None:
        self.session = _Session()
        self.model = type("Model", (), {"name": "fake"})()
        self.effort = None
        self.returned: list[tuple[str, str]] = []

    async def send_back(self, incoming, text):
        self.returned.append((incoming.sender_id, text))


async def test_a_direct_message_is_run_as_the_readers_own_prompt_and_its_final_answer_goes_back(home):
    from zettcode.daemon.run import Daemon

    client = _Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))

    await daemon._turn(IncomingMessage("web", "web-gateway", "run it", via="user", direct=True))
    await daemon._turn(IncomingMessage("peer", "peer", "from a colleague"))

    assert client.session.calls == [("prompt", "run it"), ("relay", "from a colleague")]
    assert client.returned == [("web", "final answer")], "only a direct turn is answered by the daemon itself"


async def test_a_direct_turn_that_fails_or_writes_nothing_is_still_answered_so_the_window_is_not_left_waiting(home):
    from zettcode.daemon.run import Daemon
    from zettcode.sdk.errors import RunError

    client = _Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))

    def failing(text):
        raise RunError("the model stopped")

    client.session.prompt = failing  # type: ignore[method-assign]
    await daemon._turn(IncomingMessage("web", "web-gateway", "run it", via="user", direct=True))
    client.session.prompt = lambda text: _Stream("   ")  # type: ignore[method-assign]
    await daemon._turn(IncomingMessage("web", "web-gateway", "again", via="user", direct=True))
    await daemon._turn(IncomingMessage("peer", "peer", "not direct"))

    sent = [text for _, text in client.returned]
    assert sent[0].startswith("The turn failed: the model stopped")
    assert "without a written answer" in sent[1] and len(sent) == 2, "a message that is not direct is not answered here"
