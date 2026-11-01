"""The daemons a machine is running: their records, the process around them, and the command that lists them."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from dataclasses import asdict, replace
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

    with pytest.raises(process.UpdateFailed, match="other changes were written"):
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

    with pytest.raises(process.UpdateFailed, match="other changes were written"):
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


def test_a_running_daemon_can_be_moved_to_another_model_and_effort(home):
    """The request is written into the record; the daemon puts it in force before its next turn."""
    from zettcode.sdk import list_models

    offered = list_models()
    assert offered, "the fixture config lists one model"
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    updated = process.Daemons().update(running, model=offered[0].name, effort=offered[0].efforts[0])

    assert updated.state is not None
    assert updated.state.requested_model == offered[0].name
    assert updated.state.requested_effort == offered[0].efforts[0]


def test_a_model_this_machine_does_not_have_is_refused_and_nothing_is_written(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed, match="No model called"):
        process.Daemons().update(running, model="not-configured")

    assert running.state is not None and running.state.requested_model is None


def test_a_daemon_that_is_gone_cannot_be_moved_to_another_model(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home, pid=2**22 + 17))
    record.beat()

    with pytest.raises(process.UpdateFailed, match="not running"):
        process.Daemons().update(record, model="fake")


def test_the_daemon_puts_a_requested_model_and_effort_in_force_and_clears_the_request(home):
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Client:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="01a1", title=None)
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)
            self.calls: list[tuple[str, str]] = []

        def use_model(self, name: str) -> None:
            self.calls.append(("model", name))
            self.model = SimpleNamespace(name=name, context_window=200_000)

        def use_effort(self, name: str) -> None:
            self.calls.append(("effort", name))
            self.effort = name

    client = Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))
    daemon.record.save(replace(state_for(home), requested_model="other", requested_effort="high"))

    asyncio.run(daemon._apply_requests())

    assert client.calls == [("model", "other"), ("effort", "high")]
    assert daemon.record.state is not None
    assert daemon.record.state.requested_model is None and daemon.record.state.requested_effort is None
    assert daemon.record.state.model == "other", "the record shows what it now runs on, not only at the next turn"


def test_a_request_that_cannot_be_applied_is_cleared_but_its_reason_is_kept(home):
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Client:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="01a1", title=None)
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)

        def use_model(self, name: str) -> None:
            raise ValueError(f"No model called {name!r}")

        def use_effort(self, name: str) -> None:
            self.effort = name

    daemon = Daemon(Client(), Options(workspace=home, token="t"))
    daemon.record.save(replace(state_for(home), requested_model="gone"))

    asyncio.run(daemon._apply_requests())

    assert daemon.record.state is not None
    assert daemon.record.state.requested_model is None, "a name that cannot work is not tried at every turn"
    assert daemon.record.state.requested_error is not None
    assert "No model called" in daemon.record.state.requested_error


def test_a_request_replaced_while_it_is_applied_is_kept(home):
    """The daemon clears the request it applied by value, so a reader's newer request is not lost."""
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Client:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="01a1", title=None)
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)
            self.daemon: Daemon | None = None

        def use_model(self, name: str) -> None:
            assert self.daemon is not None
            self.daemon.record.change(lambda current: replace(current, requested_model="newer"), wait=0)

        def use_effort(self, name: str) -> None:
            self.effort = name

    client = Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))
    client.daemon = daemon
    daemon.record.save(replace(state_for(home), requested_model="first"))

    asyncio.run(daemon._apply_requests())

    assert daemon.record.state is not None
    assert daemon.record.state.model == "fake"
    assert daemon.record.state.requested_model == "newer", "the request written during the change is next"


def test_a_level_the_model_does_not_take_is_refused(home):
    import os

    config = Path(os.environ["ZETTCODE_CONFIG"])
    config.write_text('[[models]]\nmodel = "fake"\ntoken = "t"\nreasoning_efforts = ["low"]\n', encoding="utf-8")
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), model="fake"))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed, match="takes low"):
        process.Daemons().update(running, effort="high")


def test_an_effort_cannot_be_checked_when_the_daemons_model_is_not_configured(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), model="a model this file lost"))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed, match="not in this configuration"):
        process.Daemons().update(running, effort="low")


def test_an_effort_is_checked_against_the_model_already_requested(home):
    import os

    config = Path(os.environ["ZETTCODE_CONFIG"])
    config.write_text(
        '[[models]]\nmodel = "fake"\ntoken = "t"\nreasoning_efforts = ["low", "high"]\n\n'
        '[[models]]\nmodel = "other"\ntoken = "t"\nreasoning_efforts = ["low"]\n',
        encoding="utf-8",
    )
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), model="fake"))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    process.Daemons().update(running, model="other")

    with pytest.raises(process.UpdateFailed, match="other takes low"):
        process.Daemons().update(running, effort="high")


def test_a_model_is_checked_against_the_level_already_requested(home):
    import os

    config = Path(os.environ["ZETTCODE_CONFIG"])
    config.write_text(
        '[[models]]\nmodel = "fake"\ntoken = "t"\nreasoning_efforts = ["low", "high"]\n\n'
        '[[models]]\nmodel = "other"\ntoken = "t"\nreasoning_efforts = ["low"]\n',
        encoding="utf-8",
    )
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), model="fake"))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    process.Daemons().update(running, effort="high")

    with pytest.raises(process.UpdateFailed) as raised:
        process.Daemons().update(running, model="other")

    assert "other takes low" in str(raised.value)
    assert "already requested" in str(raised.value) and "set one it takes first" in str(raised.value)


def test_a_label_is_written_when_the_model_asked_for_is_refused(home):
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), model="fake"))
    record.beat()
    running = Registry().find("01a1")
    assert running is not None and running.alive

    with pytest.raises(process.UpdateFailed, match="other changes were written"):
        process.Daemons().update(running, name="reader", model="not-configured")

    assert running.state is not None and running.state.name == "reader"


def test_a_title_is_written_when_the_model_asked_for_is_refused(home, tmp_path, monkeypatch):
    import zettcode.engine.storage as storage

    class Store:
        def __init__(self, *, workspace: str) -> None:
            self.workspace = workspace

        def session_dir(self, session_id: str) -> Path:
            return tmp_path / session_id

        async def set_title(self, session_id: str, title: str) -> None:
            self.title = title

    monkeypatch.setattr(storage, "SessionStore", Store)
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home, pid=2**22 + 17), model="fake"))
    record.beat()
    stopped = Registry().find("01a1")
    assert stopped is not None and not stopped.alive

    with pytest.raises(process.UpdateFailed, match="other changes were written"):
        process.Daemons().update(stopped, title="Named anyway", model="not-configured")

    assert stopped.state is not None and stopped.state.title == "Named anyway"


def test_list_shows_a_pending_request_and_why_the_last_one_failed(home, capsys):
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Client:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="01a1", title=None)
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)

    daemon = Daemon(Client(), Options(workspace=home, token="t"))
    daemon.record.save(replace(state_for(home), requested_model="next-model", requested_error="No model called 'gone'"))

    asyncio.run(daemon.mark("idle"))

    assert daemon.record.state is not None and daemon.record.state.requested_error == "No model called 'gone'"
    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out
    assert "next" in shown and "next-model" in shown
    assert "error" in shown and "No model called 'gone'" in shown


def test_update_asks_for_another_model_and_says_what_comes_next(home, capsys):
    from zettcode.sdk import list_models

    offered = list_models()
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()

    assert daemon_program(["update", "01a1", "--model", offered[0].name]) == 0
    shown = capsys.readouterr().out

    assert "next" in shown and offered[0].name in shown


def test_prompt_sends_the_text_through_the_broker(home, monkeypatch, capsys):
    """The command line is a sender like any other: the broker delivers, the daemon runs a turn, and no answer
    comes back here — the sender is a name, not a session, so the conversation is read with `resume`."""
    import httpx

    from zettcode.broker.files import Note
    from zettcode.broker.protocol import PROTOCOL_VERSION

    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    monkeypatch.setattr("zettcode.broker.files.read_note", lambda directory: Note(1, 1234, "tok", PROTOCOL_VERSION))
    calls: list[tuple[str, dict[str, object]]] = []

    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"disposition": "started"}

    def post(url: str, **options: object) -> Response:
        calls.append((url, options))
        return Response()

    monkeypatch.setattr(httpx, "post", post)

    assert daemon_program(["prompt", "01a1", "review", "the", "diff"]) == 0

    assert calls[0][0] == "http://127.0.0.1:1234/messages"
    body = calls[0][1]["json"]
    assert isinstance(body, dict)
    assert body["to"] == "01a1" and body["text"] == "review the diff"
    assert body["via"] == "external" and body["from"] == {"name": "zettcode daemon prompt"}
    assert calls[0][1]["headers"] == {"Authorization": "Bearer tok"}
    assert calls[0][1]["timeout"] == 15.0, "past the broker's own ack wait, or a timeout reads as unreachable"
    assert calls[0][1]["trust_env"] is False, "the broker is on this machine; a proxy in the environment is not for it"
    assert "started" in capsys.readouterr().out


def test_prompt_refuses_a_broker_of_another_protocol(home, monkeypatch, capsys):
    from zettcode.broker.files import Note

    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    monkeypatch.setattr("zettcode.broker.files.read_note", lambda directory: Note(1, 1234, "tok", 6))

    assert daemon_program(["prompt", "01a1", "hi"]) == 1
    assert "speaks protocol 6" in capsys.readouterr().err


def test_prompt_needs_a_session_that_is_a_daemon_and_some_text(home, monkeypatch, capsys):
    from zettcode.broker.files import Note
    from zettcode.broker.protocol import PROTOCOL_VERSION

    assert daemon_program(["prompt", "nope", "hi"]) == 1
    assert "no daemon with that session" in capsys.readouterr().err

    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    monkeypatch.setattr("zettcode.broker.files.read_note", lambda directory: Note(1, 1234, "tok", PROTOCOL_VERSION))

    assert daemon_program(["prompt", "01a1", "  "]) == 2
    assert "needs some text" in capsys.readouterr().err


def test_prompt_says_why_the_broker_refused_it(home, monkeypatch, capsys):
    import httpx

    from zettcode.broker.files import Note
    from zettcode.broker.protocol import PROTOCOL_VERSION

    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    monkeypatch.setattr("zettcode.broker.files.read_note", lambda directory: Note(1, 1234, "tok", PROTOCOL_VERSION))

    class Response:
        status_code = 409

        def json(self) -> dict[str, object]:
            return {"error": {"reason": "gone", "message": "@01a1 is no longer connected"}}

    monkeypatch.setattr(httpx, "post", lambda url, **options: Response())

    assert daemon_program(["prompt", "01a1", "hi"]) == 1
    assert "no longer connected" in capsys.readouterr().err


def test_prompt_without_a_broker_says_so(home, monkeypatch, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.beat()
    monkeypatch.setattr("zettcode.broker.files.read_note", lambda directory: None)

    assert daemon_program(["prompt", "01a1", "hi"]) == 1
    assert "no session broker" in capsys.readouterr().err


def test_list_says_when_a_daemon_cannot_reach_the_broker(home, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home), broker=False))
    record.beat()

    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out
    assert "broker" in shown and "offline" in shown

    assert daemon_program(["list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["broker"] is False


def test_a_change_in_reachability_is_recorded(home):
    import asyncio
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Client:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="01a1", title=None)
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)
            self.reachable = True

    client = Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))
    daemon.record.save(state_for(home))

    asyncio.run(daemon._note_connection())

    assert daemon.record.state is not None and daemon.record.state.broker is True

    client.reachable = False
    asyncio.run(daemon._note_connection())

    assert daemon.record.state is not None and daemon.record.state.broker is False


def test_log_prints_the_last_lines_a_daemon_wrote(home, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(state_for(home))
    record.log("first thing")
    record.log("second thing")

    assert daemon_program(["log", "01a1", "-n", "1"]) == 0
    shown = capsys.readouterr().out
    assert "second thing" in shown and "first thing" not in shown

    assert daemon_program(["log", "nope"]) == 1
    assert "no daemon with that session" in capsys.readouterr().err


def _daemon_with(
    home,
    outcomes,
    *,
    resumable: bool = True,
    resumable_raises: BaseException | None = None,
    delivers: bool = True,
):
    """A daemon whose session runs the given outcomes: an exception is raised, a string is the answer, ``None`` is
    a clean turn with no text."""
    from types import SimpleNamespace

    from zettcode.daemon.run import Daemon

    class Run:
        def __init__(self, outcome: BaseException | str | None) -> None:
            self.outcome = outcome
            self.result = SimpleNamespace(text=outcome) if isinstance(outcome, str) else None

        async def __aenter__(self):
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            return self

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Session:
        id = "01a1"
        title = None

        def __init__(self) -> None:
            self.outcomes = list(outcomes)
            self.relays = 0
            self.resumes = 0
            self.prompts = 0

        async def resumable(self):
            if resumable_raises is not None:
                raise resumable_raises
            return SimpleNamespace(description="continuing") if resumable else None

        def _next(self) -> Run:
            return Run(self.outcomes.pop(0))

        def relay(self, message):
            self.relays += 1
            return self._next()

        def resume_stream(self):
            self.resumes += 1
            return self._next()

        def prompt(self, text):
            self.prompts += 1
            return self._next()

    class Client:
        def __init__(self) -> None:
            self.session = Session()
            self.model = SimpleNamespace(name="fake", context_window=200_000)
            self.effort = "low"
            self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, context_tokens=0)
            self.reachable = True
            self.sent: list[tuple[str, str]] = []

        async def send_back(self, message, text: str):
            self.sent.append((message.sender_id, text))
            return True if delivers else None

    client = Client()
    daemon = Daemon(client, Options(workspace=home, token="t"))
    return daemon, client


def test_a_turn_that_may_pass_is_continued_rather_than_sent_again(home, monkeypatch):
    from zettcode.sdk.errors import RunError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(home, [RunError("timed out", retryable=True), None])

    asyncio.run(daemon._turn(message()))

    assert client.session.relays == 1, "the prompt is not sent a second time"
    assert client.session.resumes == 1, "the interrupted request is continued instead"
    assert client.sent == []


def test_a_turn_that_keeps_failing_is_tried_three_times_and_the_sender_is_told(home, monkeypatch):
    from zettcode.sdk.errors import RunError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(home, [RunError("timed out", retryable=True)] * 4)

    asyncio.run(daemon._turn(message()))

    assert (client.session.relays, client.session.resumes) == (1, 3)
    assert client.sent and client.sent[0][0] == "sender"
    assert "timed out" in client.sent[0][1]


def test_a_failure_that_would_fail_again_is_not_retried_and_the_sender_is_told(home):
    from zettcode.sdk.errors import RunError

    daemon, client = _daemon_with(home, [RunError("bad key")])

    asyncio.run(daemon._turn(message()))

    assert (client.session.relays, client.session.resumes) == (1, 0)
    assert client.sent and "bad key" in client.sent[0][1]


def test_a_failure_with_nothing_stored_to_continue_is_reported_without_a_second_try(home, monkeypatch):
    from zettcode.sdk.errors import RunError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(home, [RunError("rate limited", retryable=True)], resumable=False)

    asyncio.run(daemon._turn(message()))

    assert (client.session.relays, client.session.resumes) == (1, 0)
    assert client.sent and "rate limited" in client.sent[0][1]


def test_a_direct_turn_answered_after_a_retry_is_sent_back(home, monkeypatch):
    from zettcode.sdk.errors import RunError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(home, [RunError("timed out", retryable=True), "the answer"])
    direct = IncomingMessage(sender_id="01chat", sender="window", text="hello", direct=True)

    asyncio.run(daemon._turn(direct))

    assert (client.session.prompts, client.session.resumes) == (1, 1)
    assert client.sent == [("01chat", "the answer")], "the continued answer is what the window gets"


def test_a_direct_turn_that_fails_tells_its_window(home):
    from zettcode.sdk.errors import RunError

    daemon, client = _daemon_with(home, [RunError("bad key")])
    direct = IncomingMessage(sender_id="01chat", sender="window", text="hello", direct=True)

    asyncio.run(daemon._turn(direct))

    assert client.session.prompts == 1
    assert client.sent and client.sent[0][0] == "01chat" and client.sent[0][1].startswith("The turn failed: ")


def test_a_plain_network_error_is_retried_too(home, monkeypatch):
    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(home, [OSError("connection reset"), None])

    asyncio.run(daemon._turn(message()))

    assert (client.session.relays, client.session.resumes) == (1, 1)
    assert client.sent == []


def test_a_continuation_that_cannot_run_reports_the_turns_own_failure(home, monkeypatch):
    from zettcode.sdk.errors import RunError, SessionLockedError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(
        home, [RunError("timed out", retryable=True)], resumable_raises=SessionLockedError("locked elsewhere")
    )

    asyncio.run(daemon._turn(message()))

    assert client.session.resumes == 0
    assert client.sent and "timed out" in client.sent[0][1], "the sender hears the turn's failure, not the lock"
    assert "could not be continued" in daemon.record.log_path.read_text(encoding="utf-8")


def test_a_continuation_with_nothing_to_do_keeps_the_turns_own_failure(home, monkeypatch):
    from zettcode.sdk.errors import NothingToDoError, RunError

    monkeypatch.setattr("zettcode.daemon.run.RETRY_DELAYS", (0.0, 0.0, 0.0))
    daemon, client = _daemon_with(
        home, [RunError("timed out", retryable=True), NothingToDoError("nothing to continue")]
    )

    asyncio.run(daemon._turn(message()))

    assert client.session.resumes == 1
    assert client.sent and "timed out" in client.sent[0][1]
    assert "nothing to continue" in daemon.record.log_path.read_text(encoding="utf-8")


def test_a_window_that_cannot_be_reached_leaves_the_answer_in_the_log(home):
    daemon, client = _daemon_with(home, ["the answer"], delivers=False)
    direct = IncomingMessage(sender_id="01chat", sender="window", text="hello", direct=True)

    asyncio.run(daemon._turn(direct))

    assert "could not be told how the turn ended" in daemon.record.log_path.read_text(encoding="utf-8")


def test_a_sender_that_cannot_be_reached_leaves_the_reason_in_the_log(home):
    from zettcode.sdk.errors import RunError

    daemon, client = _daemon_with(home, [RunError("bad key")], delivers=False)

    asyncio.run(daemon._turn(message()))

    assert "the sender could not be told the turn failed" in daemon.record.log_path.read_text(encoding="utf-8")


def test_a_dead_record_does_not_claim_to_keep_trying(home, capsys):
    record = Registry().record(home, "01a1", create=True)
    record.save(replace(state_for(home, pid=2**22 + 17), broker=False))
    record.beat()

    assert daemon_program(["list"]) == 0
    shown = capsys.readouterr().out
    assert "dead" in shown and "offline" not in shown


def test_a_record_written_before_the_broker_field_is_still_read(home):
    record = Registry().record(home, "01a1", create=True)
    data = {key: value for key, value in asdict(state_for(home)).items() if key != "broker"}
    (record.folder / "state.json").write_text(json.dumps(data), encoding="utf-8")

    loaded = State.load(record.folder)

    assert loaded is not None and loaded.broker is None


def test_log_refuses_a_number_of_lines_below_one(home):
    with pytest.raises(SystemExit) as raised:
        daemon_program(["log", "01a1", "-n", "0"])

    assert raised.value.code == 2


def test_an_unchanged_connection_is_not_written_again(home, monkeypatch):
    daemon, client = _daemon_with(home, [])
    daemon.record.save(state_for(home))
    asyncio.run(daemon._note_connection())

    def must_not_write(*args: object, **options: object) -> None:
        raise AssertionError("an unchanged connection rewrote the record")

    monkeypatch.setattr("zettcode.daemon.state.Record.change", must_not_write)
    asyncio.run(daemon._note_connection())


def test_counters_are_refreshed_while_a_turn_runs(home):
    daemon, client = _daemon_with(home, [])
    daemon.record.save(replace(state_for(home), status="working", name="reviewer", requested_model="v2"))
    daemon.inbox = Inbox(lambda waiting: None)
    daemon.inbox.offer(message())
    client.usage = type("Usage", (), {"input_tokens": 12_000, "output_tokens": 400, "context_tokens": 34_000})()

    daemon._refresh_counters()

    assert daemon.record.state is not None
    assert (daemon.record.state.input_tokens, daemon.record.state.output_tokens) == (12_000, 400)
    assert daemon.record.state.context_tokens == 34_000
    assert daemon.record.state.status == "working", "the status is the turn's to end, not the counter's"
    assert daemon.record.state.name == "reviewer" and daemon.record.state.requested_model == "v2"


def test_counters_that_cannot_be_read_do_not_erase_the_record(home, monkeypatch):
    daemon, client = _daemon_with(home, [])
    stored = dict(input_tokens=1_000, output_tokens=10, context_tokens=2_000, context_window=200_000)
    daemon.record.save(replace(state_for(home), **stored))
    daemon.inbox = Inbox(lambda waiting: None)
    daemon.inbox.offer(message())
    monkeypatch.setattr(daemon, "_spend", lambda: (None, None, None))

    def must_not_write(*args: object, **options: object) -> None:
        raise AssertionError("counters that could not be read rewrote the record")

    monkeypatch.setattr("zettcode.daemon.state.Record.change", must_not_write)
    daemon._refresh_counters()


def test_the_beat_refreshes_counters_only_while_a_turn_runs(home, monkeypatch):
    daemon, client = _daemon_with(home, [])
    daemon.record.save(state_for(home))
    calls: list[str] = []
    monkeypatch.setattr(daemon, "_refresh_counters", lambda: calls.append("refresh"))

    async def no_requests() -> None:
        calls.append("apply")

    monkeypatch.setattr(daemon, "_apply_requests", no_requests)

    async def one_beat() -> list[str]:
        task = asyncio.ensure_future(daemon._beat())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return list(calls)

    idle = asyncio.run(one_beat())
    daemon.inbox = Inbox(lambda waiting: None)
    daemon.inbox.offer(message())
    calls.clear()
    busy = asyncio.run(one_beat())

    assert idle == ["apply"] and busy == ["refresh"]


def test_counters_are_not_refreshed_when_nothing_is_running(home, monkeypatch):
    daemon, client = _daemon_with(home, [])
    daemon.record.save(state_for(home))
    client.usage = type("Usage", (), {"input_tokens": 12_000, "output_tokens": 400, "context_tokens": 34_000})()

    def must_not_write(*args: object, **options: object) -> None:
        raise AssertionError("a daemon with nothing running rewrote the record")

    monkeypatch.setattr("zettcode.daemon.state.Record.change", must_not_write)
    daemon._refresh_counters()


def test_an_unchanged_counter_does_not_rewrite_the_record(home, monkeypatch):
    daemon, client = _daemon_with(home, [])
    zeros = dict(input_tokens=0, output_tokens=0, context_tokens=0, context_window=200_000)
    daemon.record.save(replace(state_for(home), **zeros))
    daemon.inbox = Inbox(lambda waiting: None)
    daemon.inbox.offer(message())
    client.usage = type("Usage", (), {"input_tokens": 0, "output_tokens": 0, "context_tokens": 0})()

    def must_not_write(*args: object, **options: object) -> None:
        raise AssertionError("an unchanged counter rewrote the record")

    monkeypatch.setattr("zettcode.daemon.state.Record.change", must_not_write)
    daemon._refresh_counters()


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


def test_a_tool_line_says_what_the_call_was_for():
    from zettcode.daemon.run import tool_detail

    assert tool_detail({"command": "git  status\n-s"}) == "git status -s"
    assert tool_detail({"file_path": "src/a.py", "offset": 3}) == "src/a.py"
    assert tool_detail({"to": "dawn", "message": "hi"}) == "dawn → hi"
    assert tool_detail({"group": "review", "message": "ready"}) == "#review → ready"
    assert tool_detail({"unknown": "x"}) == ""
    long = tool_detail({"command": "x" * 500})
    assert len(long) == 160 and long.endswith("…")


def test_tools_are_logged_with_their_detail_failures_and_slow_calls(home, monkeypatch):
    # The gateway's log page parses these exact lines (clients/gateway/src/lib/logs.ts, test/logs.test.ts).
    from types import SimpleNamespace

    from zettcode.daemon import run as run_module
    from zettcode.daemon.run import Daemon
    from zettcode.sdk.events import ToolFinished, ToolStarted

    client = SimpleNamespace(session=SimpleNamespace(id="01a1", title=None))
    daemon = Daemon(client, Options(workspace=home, token="t"))  # type: ignore[arg-type]
    clock = iter([100.0, 100.5, 200.0, 207.0, 300.0, 301.0])
    monkeypatch.setattr(run_module.time, "monotonic", lambda: next(clock))

    daemon._see(ToolStarted("s", "c1", "bash", {"command": "ls"}))
    daemon._see(ToolFinished("s", "c1", "bash", "ok", True))
    daemon._see(ToolStarted("s", "c2", "read", {"file_path": "a.py"}))
    daemon._see(ToolFinished("s", "c2", "read", "ok", True))
    daemon._see(ToolStarted("s", "c3", "bash", {"command": "false"}))
    daemon._see(ToolFinished("s", "c3", "bash", "exit 1\n  boom", False))

    lines = daemon.record.log_path.read_text(encoding="utf-8").splitlines()
    assert [line[20:] for line in lines] == [
        "tool bash · ls",
        "tool read · a.py",
        "tool read finished in 7.0s",
        "tool bash · false",
        "tool bash failed after 1.0s: exit 1 boom",
    ]
