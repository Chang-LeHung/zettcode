"""What the gateway needs of the SDK: peers, who sent a stored message, a conversation read by id, and the daemons."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sdk_helpers import ScriptedModel, config_for, wire
from zettcode.broker.protocol import PeerInfo
from zettcode.daemon.process import Daemons, SpawnFailed
from zettcode.daemon.state import Registry, State
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
        messenger = client._agent.runtime.messenger
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
    assert found[0] == DaemonInfo(
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


def test_a_daemon_with_no_state_is_still_listed_by_the_name_of_its_folder(folders):
    entry = Registry().record(folders / "project", "01odd", create=True)
    entry.log("something")

    (found,) = daemons.list_daemons()

    assert found.session_id == "01odd" and found.status == "dead" and found.workspace == ""


async def test_spawn_refuses_what_it_can_see_is_wrong_before_it_starts_anything(folders):
    with pytest.raises(ConfigurationError, match="deny, safe, full"):
        await daemons.spawn_daemon(folders, permission="ask")
    with pytest.raises(ConfigurationError, match="No such directory"):
        await daemons.spawn_daemon(folders / "absent")


async def test_spawn_starts_with_the_level_given_and_safe_when_none_is(folders, monkeypatch):
    started: list[dict[str, object]] = []

    def start(self, workspace, **options):
        started.append({"workspace": workspace, **options})
        record(workspace, "01made", name=options["name"], permission=options["permission"])
        return Registry().find("01made")

    monkeypatch.setattr(Daemons, "start", start)
    project = folders / "project"
    project.mkdir()

    made = await daemons.spawn_daemon(project, name="review", model="deep", effort="low")

    assert started == [
        {"workspace": project, "model": "deep", "effort": "low", "resume": None, "name": "review", "permission": "safe"}
    ]
    assert made.session_id == "01made" and made.permission == "safe" and made.name == "review"


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
