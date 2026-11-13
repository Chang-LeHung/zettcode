"""The settings a page may choose when it starts an external agent: checked by the plugin's fields, and by what the
gateway allows (its roots and ``--no-full``)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from gateway_fakes import FakeBackend
from zettcode.gateway.agents import AgentError, AgentField, AgentManager, AgentPlugin
from zettcode.gateway.service import Gateway, GatewayError
from zettcode.gateway.settings import Settings


class Session:
    def __init__(self, session_id: str, title: str, options: Mapping[str, str]) -> None:
        self.session_id = session_id
        self.title = title
        self.kind = "external"
        self.handle = session_id
        self.options = dict(options)

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def join_group(self, group: str) -> None:
        pass


class Plugin(AgentPlugin):
    name = "coder"
    title = "Coder"
    fields = (
        AgentField("cwd", "Folder", kind="directory"),
        AgentField(
            "access", "Access", kind="choice", choices=("read", "write", "all"), default="read", unrestricted="all"
        ),
        AgentField("note", "Note"),
    )

    def __init__(self) -> None:
        self.made: list[Session] = []

    def create(self, session_id: str, title: str) -> Session:  # type: ignore[override]
        return self.create_with(session_id, title, {})

    def create_with(self, session_id: str, title: str, options: Mapping[str, str]) -> Session:  # type: ignore[override]
        session = Session(session_id, title, options)
        self.made.append(session)
        return session


class OldPlugin(AgentPlugin):
    """Written before options existed: no fields, only ``create``."""

    name = "old"
    title = "Old"

    def __init__(self) -> None:
        self.made: list[Session] = []

    def create(self, session_id: str, title: str) -> Session:  # type: ignore[override]
        session = Session(session_id, title, {})
        self.made.append(session)
        return session


async def make(tmp_path: Path, **changes: object) -> tuple[Gateway, Plugin, Path]:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    plugin = Plugin()
    values: dict[str, object] = {"token": "t", "roots": (work,), "directory": tmp_path / "gw", "allow_full": True}
    values.update(changes)
    backend = FakeBackend()
    gateway = Gateway(
        backend,
        Settings(**values),  # type: ignore[arg-type]
        clock=lambda: 1000.0,
        agents=AgentManager(tmp_path / "agents", [plugin, OldPlugin()]),
    )
    await gateway.start(watch=False)
    return gateway, plugin, work


# -- the manager ----------------------------------------------------------------------------------


def test_a_type_lists_its_fields_and_an_old_plugin_lists_none(tmp_path):
    manager = AgentManager(tmp_path, [Plugin(), OldPlugin()])
    listed = {item.name: item.to_dict() for item in manager.available()}

    assert [item["name"] for item in listed["coder"]["fields"]] == ["cwd", "access", "note"]
    assert listed["coder"]["fields"][1]["choices"] == ["read", "write", "all"]
    assert listed["old"]["fields"] == []


def test_options_are_checked_against_the_fields_and_defaults_fill_in(tmp_path):
    manager = AgentManager(tmp_path, [Plugin()])

    assert manager.check_options("coder", {"note": "  hi "}) == {"note": "hi", "access": "read"}
    assert manager.check_options("coder", None) == {"access": "read"}
    assert manager.check_options("coder", {"access": "write", "note": ""}) == {"access": "write"}
    for bad in ({"nope": "x"}, {"access": "root"}, {"note": 5}, {"note": "x" * 1001}, ["access"], "access"):
        with pytest.raises(AgentError):
            manager.check_options("coder", bad)


async def test_a_plugin_without_options_is_started_as_before_and_refuses_any_option(tmp_path):
    old = OldPlugin()
    manager = AgentManager(tmp_path, [old])

    await manager.create("old", "Old one", "a1")
    assert old.made[0].options == {}
    with pytest.raises(AgentError):
        manager.check_options("old", {"anything": "x"})


# -- the gateway ----------------------------------------------------------------------------------


async def test_a_chosen_folder_and_access_reach_the_plugin_and_the_folder_is_resolved(tmp_path):
    gateway, plugin, work = await make(tmp_path)
    inside = work / "project"
    inside.mkdir()

    await gateway.create_agent(
        {"kind": "coder", "session_id": "c1", "options": {"cwd": str(inside), "access": "write"}}
    )

    assert plugin.made[0].options == {"cwd": str(inside.resolve()), "access": "write"}


async def test_a_folder_outside_the_roots_or_missing_is_refused_before_anything_starts(tmp_path):
    gateway, plugin, work = await make(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    with pytest.raises(GatewayError) as refused:
        await gateway.create_agent({"kind": "coder", "options": {"cwd": str(outside)}})
    with pytest.raises(GatewayError) as missing:
        await gateway.create_agent({"kind": "coder", "options": {"cwd": str(work / "nope")}})
    with pytest.raises(GatewayError) as escaping:
        await gateway.create_agent({"kind": "coder", "options": {"cwd": str(work / ".." / "elsewhere")}})

    assert refused.value.status == 403 and missing.value.status == 400 and escaping.value.status == 403
    assert plugin.made == []


async def test_the_unrestricted_choice_is_refused_by_a_gateway_started_with_no_full_and_a_default_cannot_sneak_it_in(
    tmp_path,
):
    gateway, plugin, _ = await make(tmp_path, allow_full=False)

    with pytest.raises(GatewayError) as refused:
        await gateway.create_agent({"kind": "coder", "options": {"access": "all"}})
    assert refused.value.status == 403 and plugin.made == []

    await gateway.create_agent({"kind": "coder", "session_id": "c2", "options": {"access": "write"}})
    assert plugin.made[0].options == {"access": "write"}

    # The same plugin's default when nothing is sent is the cautious one, and goes through.
    await gateway.create_agent({"kind": "coder", "session_id": "c3"})
    assert plugin.made[1].options == {"access": "read"}


async def test_a_malformed_option_is_a_400_and_a_failed_start_does_not_count_as_running(tmp_path):
    gateway, plugin, _ = await make(tmp_path)

    for bad in ({"access": "root"}, {"unknown": "x"}, {"note": 3}):
        with pytest.raises(GatewayError) as error:
            await gateway.create_agent({"kind": "coder", "options": bad})
        assert error.value.status == 400
    with pytest.raises(GatewayError) as shape:
        await gateway.create_agent({"kind": "coder", "options": ["a"]})
    assert shape.value.status == 400 and plugin.made == [] and gateway.agents.running() == {}
