"""The daemons a machine is running: their records, the process around them, and the command that lists them."""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path

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


def test_a_title_given_at_the_start_is_put_on_the_command_line(home):
    """`spawn --title` reaches the process that names the session, without the parent knowing how it does it."""
    from zettcode.daemon.process import Daemons, _options

    argv = Daemons()._command(_options(home, "t", None, None, None, None, "Fix the parser", "safe"))

    assert argv[argv.index("--title") + 1] == "Fix the parser"


def test_the_label_of_a_daemon_can_be_changed_while_it_runs(home):
    """The label is the daemon's own, not the session's, so a reader may relabel it without stopping it."""
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()

    updated = process.Daemons().update(record, name="now a reviewer")

    assert updated.state is not None
    assert updated.state.name == "now a reviewer"
    assert updated.state.status == "idle", "nothing else the daemon said is touched"


def test_naming_a_running_daemons_session_is_refused(home):
    """A running daemon holds its session's lock: naming it from here would be a write another process owns."""
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed) as raised:
        process.Daemons().update(running, title="Taken over")

    assert "stop it before naming it" in str(raised.value)
    assert running.state is not None and running.state.title is None


def test_a_stopped_daemons_session_can_be_named(home, tmp_path, monkeypatch):
    """With the process gone the session is free, and its title is written where `list` and `resume` read it."""
    import zettcode.engine.storage as storage

    named: list[tuple[str, str]] = []

    class Store:
        def __init__(self, *, workspace: str) -> None:
            self.workspace = workspace

        def session_dir(self, session_id: str) -> Path:
            return tmp_path / session_id

        async def set_title(self, session_id: str, title: str) -> None:
            named.append((session_id, title))

    monkeypatch.setattr(storage, "SessionStore", Store)
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home, pid=2**22 + 17), name="reviewer"))
    record.beat()

    updated = process.Daemons().update(record, title="Fix the parser")

    assert named == [("01a1", "Fix the parser")]
    assert updated.state is not None and updated.state.title == "Fix the parser"
    assert updated.state.name == "reviewer", "naming a session does not clear the daemon's own label"


def test_updating_nothing_leaves_the_record_as_it_was(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), name="reviewer", title="Old title"))

    same = process.Daemons().update(record)

    assert same.state is not None
    assert (same.state.name, same.state.title) == ("reviewer", "Old title")


def test_a_blank_title_still_writes_the_label_it_was_given_with(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home, pid=2**22 + 17))
    record.beat()

    with pytest.raises(process.UpdateFailed, match="label was changed"):
        process.Daemons().update(record, title="   ", name="reader")

    assert record.state is not None and record.state.name == "reader"


def test_a_blank_title_is_refused_before_anything_is_written(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home, pid=2**22 + 17))
    record.beat()

    with pytest.raises(process.UpdateFailed) as raised:
        process.Daemons().update(record, title="   ")

    assert "at least one character" in str(raised.value)
    assert record.state is not None and record.state.title is None


def test_update_says_what_it_changed_and_refuses_a_record_with_nothing_in_it(home, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))

    assert daemon_program(["update", "01a1", "--name", "reader"]) == 0
    shown = capsys.readouterr().out
    assert "01a1" in shown and "reader" in shown

    assert daemon_program(["update", "01a1"]) == 2
    assert "nothing to change" in capsys.readouterr().err
    assert daemon_program(["update", "nope", "--name", "x"]) == 1
    assert "no daemon with that session" in capsys.readouterr().err


def test_a_daemon_names_its_own_session_and_keeps_a_label_a_reader_put_there(home):
    """After its first answer a daemon asks for a title; the record follows the session, and a reader's label stays."""
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Session:
        id = "01a1"
        title: str | None = None
        asked = 0

        async def name_it(self) -> str | None:
            self.asked += 1
            self.title = "Fix the parser"
            return self.title

    usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)
    model = SimpleNamespace(name="fast", context_window=200_000)
    client = SimpleNamespace(session=Session(), model=model, effort="medium", usage=usage)
    daemon = Daemon(client, Options(workspace=home, token="t", name="spawned"))
    asyncio.run(daemon.mark("idle"))
    assert daemon.record.state is not None and daemon.record.state.name == "spawned"

    process.Daemons().update(daemon.record, name="reader")
    asyncio.run(daemon.mark("idle"))
    asyncio.run(daemon._name_it())
    asyncio.run(daemon._name_it())
    asyncio.run(daemon.mark("idle"))

    state = daemon.record.state
    assert state is not None
    assert client.session.asked == 1, "a session that has a title is not named again"
    assert state.title == "Fix the parser", "the title is the session's, and the record follows it"
    assert state.name == "reader", "the label is the daemon's, and a reader's lasts"


def test_list_says_how_much_a_daemon_has_spent_and_how_full_its_context_is(home, capsys):
    """The counters are what a reader checks when a daemon is working: how full it is, and what it has cost."""
    record = Registry().record(home, "01a1", create=True)
    record.save(
        replace(
            state_for(home),
            input_tokens=12_345,
            output_tokens=678,
            context_tokens=34_000,
            context_window=200_000,
        )
    )
    record.beat()

    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out

    assert "context" in shown and "34k of 200k · 17%" in shown
    assert "input" in shown and "12.3k" in shown
    assert "output" in shown and "678" in shown


def test_a_record_from_before_the_counters_were_kept_says_nothing_rather_than_zero(home, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()

    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out

    cells = [line.split() for line in shown.splitlines()]
    values = [row[-1] for row in cells if row[:1] in (["context"], ["input"], ["output"])]
    assert values == ["-", "-", "-"], "a daemon that never counted anything is not a daemon that spent nothing"


def test_a_token_count_never_rounds_up_into_the_next_unit():
    from zettcode.daemon.cli import _tokens_cell

    assert _tokens_cell(999) == "999"
    assert _tokens_cell(1_000) == "1k"
    assert _tokens_cell(999_949) == "999.9k"
    assert _tokens_cell(999_950) == "1M", "rounded, this is a million tokens, not a thousand k"
    assert _tokens_cell(1_200_000) == "1.2M"


def test_a_label_is_written_even_when_the_running_daemon_refuses_its_title(home):
    """The two are allowed differently: the label may change now, the title may not, and the error says which landed."""
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed, match="label was changed"):
        process.Daemons().update(running, title="Taken over", name="reader")

    assert running.state is not None
    assert running.state.name == "reader" and running.state.title is None


def test_naming_a_session_another_process_holds_is_refused_and_nothing_is_written(home, tmp_path, monkeypatch):
    """The lock is the authority: a session a terminal resumed is not ours to name, however the record looks."""
    import zettcode.engine.storage as storage
    from zettcode.filelock import SingletonLock

    named: list[str] = []

    class Store:
        def __init__(self, *, workspace: str) -> None:
            self.workspace = workspace

        def session_dir(self, session_id: str) -> Path:
            return tmp_path / session_id

        async def set_title(self, session_id: str, title: str) -> None:
            named.append(title)

    monkeypatch.setattr(storage, "SessionStore", Store)
    holder = SingletonLock(tmp_path / "01a1" / "session.lock")
    assert holder.acquire()
    try:
        record = Registry().record(home, "01a1", create=True)
        record.save(state_for(home, pid=2**22 + 17))
        record.beat()
        stopped = Registry().find("01a1")
        assert stopped is not None and not stopped.alive

        with pytest.raises(process.UpdateFailed, match="open in another process"):
            process.Daemons().update(stopped, title="New")
    finally:
        holder.release()

    assert named == []


def test_a_start_with_a_blank_title_is_refused_before_anything_runs(home):
    with pytest.raises(process.SpawnFailed, match="at least one character"):
        process.Daemons().start(home, title="   ")

    assert Registry().all() == ()


def test_a_context_at_or_past_its_window_is_shown_as_a_count_not_a_share(home, capsys):
    """A billed count at or past the window is not a share of it; the shell refuses such a figure too."""
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), context_tokens=240_000, context_window=200_000))
    record.beat()

    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out

    assert "240k" in shown and "120%" not in shown


def test_a_label_given_at_the_start_is_recorded_and_listed(home, capsys):
    """A spawn says what the daemon is for; `list` shows it beside the session, so a machine with several is legible."""
    record = process.Daemons().start(home, name="reviewer")
    try:
        assert record.state is not None and record.state.name == "reviewer"
        assert Registry().find(record.session_id).state.name == "reviewer"

        assert daemon_program(["list"]) == 0
        shown = capsys.readouterr().out
        assert "name" in shown and "reviewer" in shown, "the label is with the daemon, not in a table heading"

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
