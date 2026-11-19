"""What the gateway needs of the SDK: peers, who sent a stored message, a conversation read by id, and the daemons."""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

import pytest

from sdk_helpers import ScriptedModel, config_for, wire
from zettcode.broker.protocol import PeerInfo
from zettcode.daemon.process import Daemons, SpawnFailed
from zettcode.daemon.state import STATE_FILE, Registry, State
from zettcode.sdk import daemons
from zettcode.sdk.client import Client
from zettcode.sdk.errors import ConfigurationError, DaemonStartError, SessionNotFoundError
from zettcode.sdk.types import DaemonInfo, IncomingMessage, SendLimits


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Daemon records and a broker folder of this test's own."""
    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemon"))
    monkeypatch.setenv("ZETTCODE_BROKER_DIR", str(tmp_path / "broker"))
    return tmp_path


async def run_relayed(client: Client, message: IncomingMessage) -> None:
    async with client.relay(message) as run:
        async for _ in run:
            pass


# -- who sent a stored message ---------------------------------------------------------------------------------
async def test_a_message_another_session_sent_is_stored_with_its_sender_and_a_typed_one_is_not(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with Client(config=config_for(tmp_path)) as client:
        await run_relayed(client, IncomingMessage("01peer", "reviewer", "please look", via="agent", hops=2))
        async with client.prompt("and I typed this") as run:
            async for _ in run:
                pass
        history = await client.session.history(full=True)

    relayed, typed = (message for message in history if message.role == "user")
    assert relayed.relay is not None
    assert (relayed.relay.sender_id, relayed.relay.sender, relayed.relay.via, relayed.relay.hops) == (
        "01peer",
        "reviewer",
        "agent",
        2,
    )
    assert relayed.text == "please look", "what the sender said, not the line that says where it came from"
    assert typed.relay is None


# -- a conversation by its id ----------------------------------------------------------------------------------
async def test_a_session_of_another_workspace_is_read_by_naming_the_workspace(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("reply"))
    config = config_for(tmp_path)
    async with Client(config=config) as writer:
        await run_relayed(writer, IncomingMessage("01peer", "peer", "hello"))
        session_id = writer.session.id
        project = config.workspace
    (tmp_path / "gateway").mkdir()
    async with Client(config=config_for(tmp_path, workspace=tmp_path / "gateway")) as reader:
        found = await reader.sessions.history_of(session_id, workspace=project)
        assert [message.role for message in found] == ["user", "assistant"]
        assert found[0].relay is not None and found[0].relay.sender_id == "01peer"
        with pytest.raises(SessionNotFoundError):
            await reader.sessions.history_of(session_id)  # its own workspace has no such session
        with pytest.raises(SessionNotFoundError):
            await reader.sessions.history_of("no-such-session", workspace=project)
        with pytest.raises(SessionNotFoundError):
            await reader.sessions.history_of("../escape", workspace=project)


async def test_the_stamp_of_a_stored_session_moves_when_it_does_and_is_nothing_for_a_session_that_is_not_there(
    tmp_path, monkeypatch
):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with Client(config=config_for(tmp_path)) as client:
        assert client.sessions.stamp(client.session.id) is None, "nothing is written until something is said"
        await run_relayed(client, IncomingMessage("01peer", "peer", "first"))
        first = client.sessions.stamp(client.session.id)
        await run_relayed(client, IncomingMessage("01peer", "peer", "second"))
        second = client.sessions.stamp(client.session.id)
        assert first is not None and second is not None and first != second
        assert client.sessions.stamp("no-such-session") is None
        assert client.sessions.stamp("../escape") is None


# -- peers -----------------------------------------------------------------------------------------------------
async def test_a_client_without_sessions_sees_nobody_and_is_not_reachable(tmp_path):
    async with Client(config=config_for(tmp_path)) as client:
        assert client.peers() == () and not client.reachable and client.handle == ""
        assert client.send_limits == SendLimits()
        client.watch_peers(lambda: None)  # nothing to watch, and nothing fails


async def test_peers_are_the_roster_in_the_sdks_words_and_a_change_reaches_the_watcher(tmp_path, folders):
    async with Client(config=config_for(tmp_path, sessions_enabled=True)) as client:
        calls: list[int] = []
        client.watch_peers(lambda: calls.append(1))
        messenger = client._link
        assert messenger is not None
        messenger.client._roster = (
            PeerInfo("01a", "api", "Fix the API", "/w/api", "working", "zettcode"),
            PeerInfo("01b", "nightly", "", "", "idle", "external"),
        )
        messenger.client._notify_roster()
        problem = messenger.client.on_problem
        assert problem is not None
        problem("the broker is out of reach")

        peers = client.peers()
        assert [(peer.session_id, peer.handle, peer.status, peer.kind) for peer in peers] == [
            ("01a", "api", "working", "zettcode"),
            ("01b", "nightly", "idle", "external"),
        ]
        assert peers[0].title == "Fix the API" and peers[0].workspace == "/w/api"
        assert len(calls) == 2, "a roster change and a broker problem both wake the watcher"

        client.watch_peers(None)
        messenger.client._notify_roster()
        assert len(calls) == 2


# -- daemons ---------------------------------------------------------------------------------------------------
def record(workspace: Path, session_id: str, **changes: object) -> None:
    """Write a daemon's state the way a running daemon would, with a heartbeat of its own process."""
    entry = Registry().record(workspace, session_id, create=True)
    values: dict[str, object] = {
        "session_id": session_id,
        "workspace": str(workspace),
        "pid": os.getpid(),
        "status": "idle",
        "token": "t",
        "started_at": time.time(),
        "model": "fast",
        "permission": "safe",
        "name": "reviewer",
    }
    values.update(changes)
    entry.save(State(**values))  # type: ignore[arg-type]
    entry.beat()


def test_the_daemons_are_listed_newest_first_with_what_each_recorded_and_a_gone_one_is_dead(folders):
    project = folders / "project"
    project.mkdir()
    record(project, "01old", started_at=1.0, pid=2**22 + 17, title="Old one")
    record(project, "01new", started_at=2_000_000_000.0, effort="high")

    found = daemons.list_daemons()

    assert [item.session_id for item in found] == ["01new", "01old"]
    # `updated_at` is the state file's own time, which is this test's clock: it is asserted on its own below.
    assert dataclasses.replace(found[0], updated_at=0.0) == DaemonInfo(
        session_id="01new",
        workspace=str(project),
        status="idle",
        name="reviewer",
        title=None,
        model="fast",
        effort="high",
        permission="safe",
        pid=os.getpid(),
        started_at=2_000_000_000.0,
    )
    assert found[1].status == "dead" and found[1].title == "Old one"


def test_a_record_says_when_its_state_was_last_written(folders):
    """The hub orders its daemons by this, so it has to be the record's own last change and not when it started."""
    project = folders / "project"
    project.mkdir()
    record(project, "01a", started_at=1.0)

    (found,) = daemons.list_daemons()
    entry = Registry().record(project, "01a")

    assert found.updated_at == (entry.folder / STATE_FILE).stat().st_mtime
    assert found.updated_at > found.started_at, "it was started in 1970 and its state was written just now"


def test_a_daemon_with_no_state_is_still_listed_by_the_name_of_its_folder(folders):
    entry = Registry().record(folders / "project", "01odd", create=True)
    entry.log("something")

    (found,) = daemons.list_daemons()

    assert found.session_id == "01odd" and found.status == "dead" and found.workspace == ""


def test_the_levels_the_sdk_offers_are_the_daemons_own():
    """The SDK and the daemon each spell the three levels; a test keeps the two spellings one list."""
    from zettcode.daemon import PERMISSIONS

    assert daemons.PERMISSIONS == PERMISSIONS


async def test_spawn_refuses_what_it_can_see_is_wrong_before_it_starts_anything(folders):
    with pytest.raises(ConfigurationError, match="deny, safe, full"):
        await daemons.spawn_daemon(folders, permission="ask")
    with pytest.raises(ConfigurationError, match="No such directory"):
        await daemons.spawn_daemon(folders / "absent")
    with pytest.raises(ConfigurationError, match="system prompt"):
        await daemons.spawn_daemon(folders, system_prompt=" \n\t ")


async def test_spawn_starts_with_the_level_given_and_full_when_none_is(folders, monkeypatch):
    started: list[dict[str, object]] = []

    def start(self, workspace, **options):
        started.append({"workspace": workspace, **options})
        record(workspace, "01made", name=options["name"], permission=options["permission"])
        return Registry().find("01made")

    monkeypatch.setattr(Daemons, "start", start)
    project = folders / "project"
    project.mkdir()

    made = await daemons.spawn_daemon(project, name="review", model="deep", effort="low", title="Fix the parser")

    assert started == [
        {
            "workspace": project,
            "model": "deep",
            "effort": "low",
            "resume": None,
            "name": "review",
            "title": "Fix the parser",
            "permission": "full",
            "system_prompt": None,
        }
    ]
    assert made.session_id == "01made" and made.permission == "full" and made.name == "review"


async def test_spawn_hands_the_role_to_the_daemon_and_a_record_lists_it_back(folders, monkeypatch):
    """The role is the daemon's own, so it travels to the child and comes back on the record ``list`` reads."""
    started: list[dict[str, object]] = []

    def start(self, workspace, **options):
        started.append({"workspace": workspace, **options})
        record(
            workspace,
            "01role",
            name=options["name"],
            permission=options["permission"],
            system_prompt=options["system_prompt"],
        )
        return Registry().find("01role")

    monkeypatch.setattr(Daemons, "start", start)
    project = folders / "project"
    project.mkdir()
    role = "You review changes. You never edit: you report what to change."

    made = await daemons.spawn_daemon(project, name="reviewer", system_prompt=f"  {role}\n")

    assert started[0]["system_prompt"] == role, "trimmed before it reaches the child"
    assert made.system_prompt == role
    assert daemons.list_daemons()[0].system_prompt == role


async def test_a_daemons_label_can_be_changed_and_one_that_is_not_there_says_so(folders):
    project = folders / "project"
    project.mkdir()
    record(project, "01d", name="old")

    changed = await daemons.update_daemon("01d", name="new")

    assert changed.name == "new"
    assert daemons.list_daemons()[0].name == "new"
    with pytest.raises(SessionNotFoundError):
        await daemons.update_daemon("01nope", name="x")


async def test_naming_a_running_daemons_session_through_the_sdk_is_refused(folders):
    project = folders / "project"
    project.mkdir()
    record(project, "01d")

    with pytest.raises(ConfigurationError, match="stop it"):
        await daemons.update_daemon("01d", title="Taken over")


async def test_a_daemon_that_never_became_reachable_says_what_it_said(folders, monkeypatch):
    def start(self, workspace, **options):
        raise SpawnFailed("no model is configured", folders / "spawn.log")

    monkeypatch.setattr(Daemons, "start", start)

    with pytest.raises(DaemonStartError, match="no model") as raised:
        await daemons.spawn_daemon(folders)

    assert raised.value.log == str(folders / "spawn.log")


async def test_stopping_a_daemon_removes_its_record_and_an_unknown_one_is_not_found(folders):
    project = folders / "project"
    project.mkdir()
    record(project, "01gone", pid=2**22 + 17)

    assert "gone" in await daemons.stop_daemon("01gone")
    assert daemons.list_daemons() == []
    with pytest.raises(SessionNotFoundError):
        await daemons.stop_daemon("01gone")


def test_a_daemons_log_is_read_from_its_end_and_an_unknown_daemon_has_none(folders):
    project = folders / "project"
    project.mkdir()
    record(project, "01log")
    entry = Registry().find("01log")
    assert entry is not None
    assert daemons.daemon_log("01log") == ""
    for number in range(5):
        entry.log(f"line {number}")

    tail = daemons.daemon_log("01log", lines=2).splitlines()

    assert [line.split(" ", 2)[2] for line in tail] == ["line 3", "line 4"]
    with pytest.raises(SessionNotFoundError):
        daemons.daemon_log("01none")


async def test_session_totals_reads_a_session_by_its_folder_or_finds_one_whose_folder_is_unknown(tmp_path):
    from zett_agent.messages import AssistantMessage, UserMessage
    from zett_agent.model import ModelUsage

    from zettcode.engine.storage import SessionStore

    work = tmp_path / "work"
    work.mkdir()
    store = SessionStore(tmp_path / "store", work)
    usage = ModelUsage(
        input_tokens=1000,
        output_tokens=100,
        cache_read_tokens=900,
        cache_write_tokens=0,
        reasoning_tokens=0,
        cache_reported=True,
    )
    await store.append("01s", "r1", UserMessage(content="q"))
    await store.append("01s", "r1", AssistantMessage(content="a", model="m"), usage=usage)

    named = daemons.session_totals({str(work): ["01s", "01missing"]}, store=tmp_path / "store")
    lost = daemons.session_totals({}, store=tmp_path / "store", unplaced=["01s", "../01s", "01missing"])

    assert set(named) == {"01s"} and named["01s"].requests == 1
    assert named["01s"].cache_share == 0.9
    assert set(lost) == {"01s"} and lost["01s"].input_tokens == 1000, "found in the store with no folder named"
    assert daemons.session_totals({"": ["01s"]}, store=tmp_path / "store") == {}, "no folder, no lookup"


async def test_kept_readers_are_reused_and_a_session_found_nowhere_is_not_searched_for_on_every_call(
    tmp_path, monkeypatch
):
    from zett_agent.messages import AssistantMessage, UserMessage
    from zett_agent.model import ModelUsage

    from zettcode.engine.storage import SessionStore
    from zettcode.engine.storage import ledger as ledger_module

    work = tmp_path / "work"
    work.mkdir()
    store = SessionStore(tmp_path / "store", work)
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=1,
        cache_read_tokens=5,
        cache_write_tokens=0,
        reasoning_tokens=0,
        cache_reported=True,
    )
    await store.append("01s", "r1", UserMessage(content="q"))
    await store.append("01s", "r1", AssistantMessage(content="a", model="m"), usage=usage)
    made: list[object] = []
    real = ledger_module.LedgerReader.at

    def counting(folder, **kwargs):
        made.append(folder)
        return real(folder, **kwargs)

    monkeypatch.setattr(ledger_module.LedgerReader, "at", staticmethod(counting))
    now = [0.0]
    readers = daemons.UsageReaders(clock=lambda: now[0])
    ask = {"wanted": {str(work): ["01s"]}, "store": tmp_path / "store", "readers": readers}

    daemons.session_totals(**ask, unplaced=["01gone"])
    daemons.session_totals(**ask, unplaced=["01gone"])

    assert len(made) == 1, "the second call used the reader the first one made"
    assert not readers.worth_searching("01gone"), "a session found nowhere is left alone for a while"
    now[0] = readers.RETRY + 1
    assert readers.worth_searching("01gone"), "and looked for again later, in case it has appeared"

    lost = daemons.session_totals({}, store=tmp_path / "store", unplaced=["01s"], readers=readers)
    assert lost["01s"].input_tokens == 10 and readers.folder_of("01s") is not None
    again = daemons.session_totals({}, store=tmp_path / "store", unplaced=["01s"], readers=readers)
    assert again["01s"].input_tokens == 10, "a session found once is read from the folder that was remembered"


async def _one_reply(tmp_path, session="01s"):
    """A store holding one session with one counted reply, and the workspace it belongs to."""
    from zett_agent.messages import AssistantMessage, UserMessage
    from zett_agent.model import ModelUsage

    from zettcode.engine.storage import SessionStore

    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    store = SessionStore(tmp_path / "store", work)
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=1,
        cache_read_tokens=5,
        cache_write_tokens=0,
        reasoning_tokens=0,
        cache_reported=True,
    )
    await store.append(session, "r1", UserMessage(content="q"))
    await store.append(session, "r1", AssistantMessage(content="a", model="m"), usage=usage)
    return work, store


async def test_a_workspace_folder_that_is_renamed_is_followed_not_read_as_empty(tmp_path):
    work, store = await _one_reply(tmp_path)
    readers = daemons.UsageReaders()
    ask = {"wanted": {str(work): ["01s"]}, "store": tmp_path / "store", "readers": readers}
    assert daemons.session_totals(**ask)["01s"].input_tokens == 10

    moved = store.workspace_dir.with_name("moved-by-an-opening-terminal")
    store.workspace_dir.rename(moved)
    # The workspace now resolves to a folder with nothing in it yet, as it does after a rename: the kept reader must not
    # keep answering from the old place.
    assert daemons.session_totals(**ask) == {}

    moved.rename(store.workspace_dir)
    assert daemons.session_totals(**ask)["01s"].input_tokens == 10, "back where the workspace names it, it reads again"


async def test_a_folder_is_one_reader_whether_it_was_reached_by_workspace_or_by_looking(tmp_path):
    work, store = await _one_reply(tmp_path)
    readers = daemons.UsageReaders()

    daemons.session_totals({str(work): ["01s"]}, store=tmp_path / "store", unplaced=["01other"], readers=readers)
    first = readers.reader(tmp_path / "store", work)

    assert first is readers.reader_at(store.workspace_dir)
    assert len(readers._readers) == 1


async def test_a_remembered_folder_that_disappears_is_searched_for_again(tmp_path):
    _, store = await _one_reply(tmp_path)
    readers = daemons.UsageReaders()
    ask = {"wanted": {}, "store": tmp_path / "store", "readers": readers, "unplaced": ["01s"]}
    assert daemons.session_totals(**ask)["01s"].input_tokens == 10
    assert readers.folder_of("01s") is not None

    moved = store.workspace_dir.with_name("elsewhere")
    store.workspace_dir.rename(moved)

    assert "01s" not in daemons.session_totals(**ask), "the call that finds the old place empty says so, and forgets it"
    assert readers.folder_of("01s") is None
    assert daemons.session_totals(**ask)["01s"].input_tokens == 10, "the next one searches and finds the new folder"
    assert readers.folder_of("01s") == moved


async def test_a_store_that_cannot_be_listed_does_not_mark_a_session_as_missed(tmp_path):
    readers = daemons.UsageReaders()

    assert daemons.session_totals({}, store=tmp_path / "no-such-store", unplaced=["01x"], readers=readers) == {}

    assert readers.worth_searching("01x"), "an unreadable store says nothing about the session"


async def test_what_a_call_did_not_use_is_dropped_from_the_kept_maps(tmp_path):
    work, _ = await _one_reply(tmp_path)
    readers = daemons.UsageReaders()
    daemons.session_totals({str(work): ["01s"]}, store=tmp_path / "store", unplaced=["01gone"], readers=readers)
    assert "01gone" in readers._missed and len(readers._readers) == 1

    daemons.session_totals({}, store=tmp_path / "store", readers=readers)

    assert not readers._missed and not readers._readers and not readers._folders
