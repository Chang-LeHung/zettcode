"""The gateway's external-agent manager: plugin discovery shape, start, group join and removal."""

from __future__ import annotations

import pathlib

import pytest

from zettcode.gateway.agents import AgentError, AgentManager, AgentPlugin, avatar_data


class FakeSession:
    def __init__(self, session_id: str, title: str) -> None:
        self.session_id = session_id
        self.title = title
        self.kind = "zettcode"
        self.handle = ""
        self.connected = False
        self.joined: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        self.connected = True
        self.handle = self.session_id

    async def close(self) -> None:
        self.closed = True

    async def join_group(self, group: str) -> None:
        self.joined.append(group)


class FakePlugin(AgentPlugin):
    name = "echo"
    title = "Echo"
    description = "Answers with what it hears"

    def __init__(self) -> None:
        self.created: list[FakeSession] = []

    def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
        session = FakeSession(session_id, title)
        self.created.append(session)
        return session


async def test_a_manager_starts_lists_and_removes_one_agent(tmp_path: pathlib.Path):
    plugin = FakePlugin()
    manager = AgentManager(tmp_path, [plugin])

    assert manager.available()[0].name == "echo"
    session = await manager.create("echo", "Echo one", "agent-1", "review")

    assert session is plugin.created[0]
    assert session.connected and session.handle == "agent-1"
    assert session.joined == ["review"]
    assert manager.running() == {"agent-1": session}

    assert await manager.remove("agent-1")
    assert session.closed
    assert manager.running() == {}


async def test_starting_a_running_id_again_returns_it_and_an_unknown_type_is_refused(tmp_path: pathlib.Path):
    manager = AgentManager(tmp_path, [FakePlugin()])
    first = await manager.create("echo", "one", "agent-1")
    assert await manager.create("echo", "two", "agent-1") is first
    with pytest.raises(AgentError):
        await manager.create("missing", "two")
    await manager.close()


async def test_the_manager_caps_the_agents_it_starts(tmp_path: pathlib.Path, monkeypatch):
    from zettcode.gateway import agents as module

    monkeypatch.setattr(module, "MAX_AGENTS", 2)
    manager = AgentManager(tmp_path, [FakePlugin()])
    await manager.create("echo", "one", "agent-1")
    await manager.create("echo", "two", "agent-2")
    with pytest.raises(AgentError):
        await manager.create("echo", "three", "agent-3")
    await manager.close()


async def test_a_plugin_factory_that_raises_is_reported(tmp_path: pathlib.Path):
    class BrokenCreate(FakePlugin):
        def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
            raise RuntimeError("bad factory")

    manager = AgentManager(tmp_path, [BrokenCreate()])
    with pytest.raises(AgentError):
        await manager.create("echo", "broken")


async def test_a_failed_connect_is_closed_and_reported(tmp_path: pathlib.Path):
    class Broken(FakePlugin):
        def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
            session = super().create(session_id, title)
            session.connect = _fail  # type: ignore[method-assign]
            return session

    manager = AgentManager(tmp_path, [Broken()])
    with pytest.raises(AgentError):
        await manager.create("echo", "broken")
    assert manager.running() == {}


async def _fail() -> None:
    raise RuntimeError("no broker")


def test_an_avatar_can_be_a_local_file_or_base64(tmp_path):
    picture = tmp_path / "mark.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    assert avatar_data(str(picture)).startswith("data:image/png;base64,")
    assert avatar_data("base64:" + __import__("base64").b64encode(picture.read_bytes()).decode()).startswith(
        "data:image/png;base64,"
    )
    assert avatar_data(str(tmp_path / "missing.png")) == ""


async def test_agents_come_back_after_the_gateway_restarts(tmp_path: pathlib.Path):
    first = AgentManager(tmp_path, [FakePlugin()])
    await first.create("echo", "Echo one", "agent-1")
    await first.create("echo", "Echo two", "agent-2")
    await first.remove("agent-2")
    await first.close()

    plugin = FakePlugin()
    second = AgentManager(tmp_path, [plugin])
    assert await second.restore() == ["agent-1"]
    assert plugin.created[0].title == "Echo one" and plugin.created[0].connected
    assert second.kind_of("agent-1") == "echo"
    assert await second.restore() == []


async def test_an_agent_that_cannot_start_stays_on_the_roster(tmp_path: pathlib.Path):
    first = AgentManager(tmp_path, [FakePlugin()])
    await first.create("echo", "Echo one", "agent-1")
    await first.close()

    assert await AgentManager(tmp_path, []).restore() == []
    again = AgentManager(tmp_path, [FakePlugin()])
    assert await again.restore() == ["agent-1"]


async def test_an_agent_on_the_roster_that_is_not_running_still_has_its_type_and_comes_back_when_it_can(tmp_path):
    plugin = FakePlugin()
    first = AgentManager(tmp_path, [plugin])
    await first.create("echo", "Echo one", "agent-1", "")
    await first.close()

    second = AgentManager(tmp_path, [plugin])
    assert second.running() == {} and second.kind_of("agent-1") == "echo", "a page can offer to start it again"

    assert await second.restore() == ["agent-1"]
    assert second.running()["agent-1"] is plugin.created[-1]
    assert await second.restore() == [], "what is running is not started twice"


async def test_a_failed_restore_is_tried_again_and_reported_once(tmp_path, caplog):
    class Failing(FakePlugin):
        broken = True

        def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
            session = super().create(session_id, title)
            if self.broken:

                async def refuse() -> None:
                    raise RuntimeError("no broker")

                session.connect = refuse  # type: ignore[method-assign]
            return session

    plugin = Failing()
    manager = AgentManager(tmp_path, [plugin])
    manager._write_roster({"agent-1": {"kind": "echo", "title": "Echo"}})

    assert await manager.restore() == []
    assert await manager.restore() == []
    assert len([r for r in caplog.records if r.getMessage() == "agents.restore_failed"]) == 1

    plugin.broken = False
    assert await manager.restore() == ["agent-1"]


class _Unrunnable(FakePlugin):
    def probe(self) -> str:
        return "echo was not found on this gateway's PATH"


async def test_an_agent_that_cannot_run_is_listed_with_why_and_is_never_registered(tmp_path):
    plugin = _Unrunnable()
    manager = AgentManager(tmp_path, [plugin])

    listed = manager.available()[0]
    assert (listed.runnable, listed.reason) == (False, "echo was not found on this gateway's PATH")
    assert listed.to_dict()["runnable"] is False

    with pytest.raises(AgentError, match="not found on this gateway's PATH"):
        await manager.create("echo", "Echo", "agent-1", "review")
    assert plugin.created == [], "no session was made, so none was registered or put in the group"
    assert manager.running() == {} and not (tmp_path / "agents.json").exists(), "and none is on the roster"


async def test_a_probe_that_raises_is_a_reason_and_does_not_hide_the_other_types(tmp_path):
    class Broken(FakePlugin):
        name = "broken"

        def probe(self) -> str:
            raise RuntimeError("boom")

    manager = AgentManager(tmp_path, [Broken(), FakePlugin()])
    by_name = {item.name: item for item in manager.available()}
    assert by_name["broken"].runnable is False and "boom" in by_name["broken"].reason
    assert by_name["echo"].runnable is True


async def test_a_page_and_the_keeper_cannot_both_start_the_same_agent(tmp_path):
    import asyncio

    gate = asyncio.Event()

    class Slow(FakePlugin):
        def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
            session = super().create(session_id, title)
            original = session.connect

            async def connect() -> None:
                await gate.wait()
                await original()

            session.connect = connect  # type: ignore[method-assign]
            return session

    plugin = Slow()
    manager = AgentManager(tmp_path, [plugin])
    manager._write_roster({"agent-1": {"kind": "echo", "title": "Echo"}})

    keeper = asyncio.ensure_future(manager.restore())
    await asyncio.sleep(0)
    page = asyncio.ensure_future(manager.create("echo", "Echo", "agent-1", ""))
    await asyncio.sleep(0)
    assert not page.done(), "the page waits for the start in flight instead of being refused or starting a second one"
    assert await manager.restore() == [], "the keeper does not start what is being started"
    gate.set()
    assert await keeper == ["agent-1"]
    assert await page is manager.running()["agent-1"]
    assert len(plugin.created) == 1


async def test_an_agent_removed_while_the_keeper_was_starting_it_does_not_come_up_behind_the_page(tmp_path):
    import asyncio

    gate = asyncio.Event()

    class Slow(FakePlugin):
        def create(self, session_id: str, title: str) -> FakeSession:  # type: ignore[override]
            session = super().create(session_id, title)
            original = session.connect

            async def connect() -> None:
                await gate.wait()
                await original()

            session.connect = connect  # type: ignore[method-assign]
            return session

    plugin = Slow()
    manager = AgentManager(tmp_path, [plugin])
    manager._write_roster({"agent-1": {"kind": "echo", "title": "Echo"}})

    keeper = asyncio.ensure_future(manager.restore())
    await asyncio.sleep(0)
    removal = asyncio.ensure_future(manager.remove("agent-1"))
    await asyncio.sleep(0)
    assert not removal.done(), "the removal waits for the start in flight, so it removes what that start made"
    gate.set()
    assert await keeper == ["agent-1"]
    assert await removal is True
    assert manager.running() == {} and plugin.created[0].closed and manager.kept() == {}
