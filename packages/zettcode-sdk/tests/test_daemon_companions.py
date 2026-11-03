"""The daemons as a broker restart sees them: only live ones, stopped and started again on their own sessions."""

from __future__ import annotations

from pathlib import Path

from zettcode.daemon.companions import DaemonCompanions
from zettcode.daemon.process import SpawnFailed
from zettcode.daemon.state import State


def state(session: str, **more) -> State:
    return State(
        session_id=session,
        workspace=f"/work/{session}",
        pid=1,
        status="idle",
        token="t",
        started_at=0.0,
        model="fast",
        effort="high",
        name=more.pop("name", "review"),
        permission=more.pop("permission", "full"),
        **more,
    )


class FakeRecord:
    def __init__(self, st: State | None, *, dead: bool = False) -> None:
        self.state, self.dead = st, dead
        self.session_id = st.session_id if st else "?"


class FakeDaemons:
    def __init__(self, records: list[FakeRecord], fail: set[str] | None = None) -> None:
        self.registry = type("R", (), {"all": lambda _self: tuple(records)})()
        self.stopped: list[str] = []
        self.started: list[dict] = []
        self.fail = fail or set()

    def stop(self, record: FakeRecord) -> str:
        self.stopped.append(record.session_id)
        return "stopped"

    def start(self, workspace: Path, **options) -> None:
        if options["resume"] in self.fail:
            raise SpawnFailed("no model")
        self.started.append({"workspace": workspace, **options})


def companions(records, fail=None):
    made = DaemonCompanions()
    made.daemons = FakeDaemons(records, fail)  # type: ignore[assignment]
    return made, made.daemons


def test_only_daemons_that_are_running_are_listed():
    made, _ = companions([FakeRecord(state("a")), FakeRecord(state("b"), dead=True), FakeRecord(None)])

    assert made.listing() == ["a  review  /work/a"]


def test_stopped_daemons_are_started_again_on_the_same_session_with_the_same_settings():
    made, fake = companions([FakeRecord(state("a")), FakeRecord(state("c", name="docs", permission="safe"))])

    stopped = made.stop()
    result = made.start()

    assert fake.stopped == ["a", "c"] and len(stopped) == 2
    assert all(worked for worked, _ in result)
    assert [(s["resume"], s["name"], s["permission"], s["model"], s["effort"]) for s in fake.started] == [
        ("a", "review", "full", "fast", "high"),
        ("c", "docs", "safe", "fast", "high"),
    ]
    assert fake.started[0]["workspace"] == Path("/work/a")


def test_one_that_cannot_start_is_reported_and_the_others_still_start():
    made, fake = companions([FakeRecord(state("a")), FakeRecord(state("c"))], fail={"a"})

    made.stop()
    result = made.start()

    assert [worked for worked, _ in result] == [False, True]
    assert "no model" in result[0][1] and [s["resume"] for s in fake.started] == ["c"]
    assert made.start() == [], "what was started again is not started twice"
