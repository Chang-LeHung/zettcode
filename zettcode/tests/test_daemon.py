"""The daemons a machine is running: their records, the process around them, and the command that lists them."""

from __future__ import annotations

import json
import os
import time

import pytest

from zettcode.daemon import process
from zettcode.daemon.cli import daemon_program
from zettcode.daemon.run import Inbox
from zettcode.daemon.state import State, alive, entries, remove, session_folder, workspace_folder
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


# -- the record ----------------------------------------------------------------------------------------------------
def test_a_state_round_trips_and_names_the_folder_it_is_in(tmp_path):
    folder = tmp_path / "daemon" / "ws" / "01a1"
    state = State(session_id="01a1", workspace="/work", pid=os.getpid(), status="idle", token="t", started_at=1.0)

    state.write(folder)

    assert State.read(folder) == state
    assert (folder / "state.json").read_text(encoding="utf-8").startswith("{")


def test_a_state_from_another_protocol_or_nonsense_is_not_believed(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "state.json").write_text('{"session_id": "x", "protocol": 999}', encoding="utf-8")

    assert State.read(folder) is None
    (folder / "state.json").write_text("not json", encoding="utf-8")
    assert State.read(folder) is None


def test_a_daemon_is_alive_only_while_its_process_and_its_heartbeat_are(tmp_path, home):
    folder = session_folder(home, "01a1", create=True)
    state = State(session_id="01a1", workspace=str(home), pid=os.getpid(), status="idle", token="t", started_at=1.0)
    state.write(folder)

    assert not alive(folder, state), "a pid with no heartbeat is not proof of anything"

    (folder / "heartbeat").write_text("now", encoding="utf-8")
    assert alive(folder, state)

    (folder / "heartbeat").write_text("old", encoding="utf-8")
    long_ago = time.time() - 3600
    os.utime(folder / "heartbeat", (long_ago, long_ago))
    assert not alive(folder, state), "a heartbeat that stopped long ago is a process that wedged"

    state = State(session_id="01a1", workspace=str(home), pid=2**22 + 7, status="idle", token="t", started_at=1.0)
    assert not alive(folder, state), "a pid nobody has is not a daemon"


def test_entries_finds_every_workspace_and_kill_can_remove_a_dead_one(tmp_path, home):
    dead = session_folder(home, "01a1", create=True)
    State(session_id="01a1", workspace=str(home), pid=2**22 + 7, status="idle", token="t", started_at=1.0).write(dead)
    (dead / "heartbeat").write_text("x", encoding="utf-8")

    found = entries()

    assert [entry.session_id for entry in found] == ["01a1"]
    assert found[0].dead and found[0].status == "dead"
    assert process.kill(found[0]) == "was already gone; its record was removed"
    assert entries() == ()


def test_a_folder_that_never_wrote_its_state_is_still_listed_and_removable(tmp_path, home):
    folder = workspace_folder(home, create=True) / "01a1"
    folder.mkdir()
    (folder / "log").write_text("died", encoding="utf-8")

    found = entries()

    assert [entry.session_id for entry in found] == ["01a1"] and found[0].state is None
    assert found[0].status == "dead"


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
def test_a_spawned_daemon_is_listed_alive_and_a_kill_stops_it(home, capsys):
    state = process.spawn(home, token="tok")
    try:
        assert state.status == "idle" and state.workspace == str(home.resolve())
        listed = entries()
        assert [entry.session_id for entry in listed] == [state.session_id]
        assert listed[0].alive and listed[0].status == "idle"

        assert daemon_program(["list", "--json"]) == 0
        shown = json.loads(capsys.readouterr().out)
        assert shown[0]["session"] == state.session_id and shown[0]["status"] == "idle"
    finally:
        entry = process.find(state.session_id)
        assert entry is not None
        assert process.kill(entry) == "stopped"

    assert entries() == (), "the record goes"
    assert not any(folder.name == state.session_id for folder in (home.parent / "daemon").rglob("*"))


def test_a_daemon_that_cannot_start_says_why_and_leaves_no_record(home, monkeypatch, tmp_path):
    broken = tmp_path / "broken.toml"
    broken.write_text("[[models]]\nmodel = 3\n", encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(broken))

    with pytest.raises(process.SpawnFailed) as raised:
        process.spawn(home, token="tok")

    assert "zettcode daemon:" in str(raised.value)
    assert entries() == (), "a start that failed leaves nothing to clean up"


def test_kill_reports_a_session_no_daemon_has(home, capsys):
    assert daemon_program(["kill", "nope"]) == 1
    assert "no daemon with that session" in capsys.readouterr().out


def test_list_says_so_when_nothing_runs(home, capsys):
    assert daemon_program(["list"]) == 0
    assert "No daemons" in capsys.readouterr().out


def test_remove_leaves_the_workspace_folder_and_its_note(home):
    folder = session_folder(home, "01a1", create=True)
    State(session_id="01a1", workspace=str(home), pid=1, status="idle", token="t", started_at=1.0).write(folder)

    remove(folder)

    assert not folder.exists()
    assert (workspace_folder(home) / "workspace.txt").is_file()
