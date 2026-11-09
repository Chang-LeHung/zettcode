"""The daemon guard: started once, resumed next time, and not hammered when it cannot start."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from zettcode.im.guard import DaemonGuard, DaemonUnavailable
from zettcode.im.state import BridgeState


@dataclass
class Info:
    session_id: str
    status: str


class Daemons:
    """What the SDK answers, arranged by the test."""

    def __init__(self) -> None:
        self.records: list[Info] = []
        self.spawned: list[dict[str, Any]] = []
        self.fails: Exception | None = None
        self.next_session = "01started"

    def list_daemons(self) -> list[Info]:
        return list(self.records)

    async def spawn_daemon(self, workspace, **kwargs):
        self.spawned.append({"workspace": workspace, **kwargs})
        if self.fails is not None:
            raise self.fails
        resumed = kwargs.get("resume") or self.next_session
        self.records = [Info(resumed, "idle")]
        return Info(resumed, "idle")


@pytest.fixture()
def daemons(monkeypatch) -> Daemons:
    fake = Daemons()
    from zettcode.sdk import daemons as module

    monkeypatch.setattr(module, "list_daemons", fake.list_daemons)
    monkeypatch.setattr(module, "spawn_daemon", fake.spawn_daemon)
    return fake


def guard(tmp_path: Path, state: BridgeState, **kwargs) -> DaemonGuard:
    return DaemonGuard(workspace=tmp_path, state=state, waits=kwargs.pop("waits", (60.0,)), **kwargs)


def test_the_first_message_starts_a_daemon_and_the_session_is_kept(tmp_path: Path, daemons: Daemons) -> None:
    state = BridgeState.load(tmp_path / "state.json")
    started = guard(tmp_path, state)

    assert asyncio_run(started.ensure()) == "01started"
    assert daemons.spawned[0]["resume"] is None, "the first daemon of this bridge starts an empty session"
    assert state.session_id == "01started", "and the id is written where a restart finds it"
    assert BridgeState.load(tmp_path / "state.json").session_id == "01started"


def test_after_a_restart_the_same_session_is_resumed_and_a_running_daemon_is_left_alone(
    tmp_path: Path, daemons: Daemons
) -> None:
    state = BridgeState.load(tmp_path / "state.json")
    state.session_id = "01a1"
    state.save()
    daemons.records = [Info("01a1", "working")]

    assert asyncio_run(guard(tmp_path, state).ensure()) == "01a1"
    assert daemons.spawned == [], "a daemon that is there is not started again"

    daemons.records = [Info("01a1", "dead")]
    assert asyncio_run(guard(tmp_path, state).ensure()) == "01a1"
    assert daemons.spawned[0]["resume"] == "01a1", "a stopped one is resumed, not replaced"


def test_a_start_that_fails_is_not_retried_before_its_wait_and_the_wait_grows(tmp_path: Path, daemons: Daemons) -> None:
    from zettcode.sdk.errors import DaemonStartError

    state = BridgeState.load(tmp_path / "state.json")
    daemons.fails = DaemonStartError("the model rejected the key")
    started = guard(tmp_path, state)

    with pytest.raises(DaemonUnavailable) as first:
        asyncio_run(started.ensure())
    assert "the model rejected the key" in str(first.value)
    assert started.failures == 1
    assert daemons.spawned, "the first attempt did run"

    attempts = len(daemons.spawned)
    with pytest.raises(DaemonUnavailable) as second:
        asyncio_run(started.ensure())
    assert len(daemons.spawned) == attempts, "the second message does not spawn again while the wait runs"
    assert second.value.retry_in > 0

    started.forget()  # a reader who fixed the key (or a test) may try at once
    daemons.fails = None
    assert asyncio_run(started.ensure()) == "01started"
    assert started.failures == 0, "a start that worked clears the count"


def test_a_failed_start_leaves_the_old_session_id_in_place(tmp_path: Path, daemons: Daemons) -> None:
    """A start that failed must not forget which conversation the bridge was having."""
    state = BridgeState.load(tmp_path / "state.json")
    state.session_id = "01a1"
    state.save()
    daemons.fails = RuntimeError("no")

    with pytest.raises(DaemonUnavailable):
        asyncio_run(guard(tmp_path, state).ensure())

    assert BridgeState.load(tmp_path / "state.json").session_id == "01a1"


def asyncio_run(coroutine):
    """Run one coroutine, which is what the bridge does inside its own loop."""
    import asyncio

    return asyncio.run(coroutine)
