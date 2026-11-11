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


async def test_a_duplicate_or_unknown_type_is_refused(tmp_path: pathlib.Path):
    manager = AgentManager(tmp_path, [FakePlugin()])
    await manager.create("echo", "one", "agent-1")
    with pytest.raises(AgentError):
        await manager.create("echo", "two", "agent-1")
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
