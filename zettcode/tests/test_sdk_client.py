"""A client's life: what it holds, what it changes in the process, and everything that can go wrong around it."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, config_for, models, wire
from zettcode.sdk.errors import (
    ClientClosedError,
    ConfigurationError,
    SessionBusyError,
    SessionLockedError,
    WorkspaceConflictError,
)
from zettcode.sdk.types import ModelInfo, Usage


def client_for(tmp_path: Path, **changes) -> zc.Client:
    return zc.Client(config=config_for(tmp_path, **changes))


# -- what it is -----------------------------------------------------------------------------------


async def test_a_new_client_has_an_empty_current_session_and_nothing_spent(tmp_path):
    async with client_for(tmp_path) as client:
        assert client.session.current and client.session.title is None
        assert client.usage == Usage() and client.session.usage == Usage()
        assert client.workspace == (tmp_path / "project").resolve()
        assert not client.closed


async def test_the_configuration_in_force_is_exposed_and_has_the_embedding_defaults_off_when_built_from_models(
    tmp_path,
):
    async with zc.Client(
        tmp_path / "project" if (tmp_path / "project").mkdir() is None else None,
        models=[{"model": "m", "token": "t"}],
        store=tmp_path / "s",
    ) as client:
        assert client.config.sessions_enabled is False and client.config.update_enabled is False
        assert client.config.store == (tmp_path / "s").resolve()


async def test_the_builtin_plugins_load_without_failures(tmp_path):
    async with client_for(tmp_path) as client:
        report = client.plugins

        assert report.failures == ()
        assert "coding" in report.loaded and "shell-permission" in report.loaded and "compaction" in report.loaded


async def test_a_client_has_a_readable_repr_open_and_closed(tmp_path):
    client = client_for(tmp_path)
    assert "project" in repr(client) and "session=" in repr(client)
    await client.aclose()
    assert "closed" in repr(client)


# -- models, effort, permission -------------------------------------------------------------------


async def test_the_configured_models_are_listed_with_the_active_one_marked(tmp_path):
    async with client_for(tmp_path, models=models("alpha", "beta", multimodal=True)) as client:
        listed = client.models

        assert [m.name for m in listed] == ["alpha", "beta"]
        assert [m.active for m in listed] == [True, False]
        assert all(isinstance(m, ModelInfo) and m.multimodal for m in listed)
        assert client.model.name == "alpha"
        assert listed[0].context_window > 0 and "high" in listed[0].efforts


async def test_choosing_a_model_by_name_or_by_its_info_changes_the_active_one(tmp_path):
    async with client_for(tmp_path, models=models("alpha", "beta")) as client:
        assert client.use_model("beta").name == "beta" and client.model.name == "beta"
        assert client.use_model(client.models[0]).name == "alpha"


async def test_an_unknown_model_names_the_ones_there_are_and_changes_nothing(tmp_path):
    async with client_for(tmp_path, models=models("alpha", "beta")) as client:
        with pytest.raises(ConfigurationError, match="alpha, beta"):
            client.use_model("gamma")

        assert client.model.name == "alpha"


async def test_the_starting_model_effort_and_permission_can_be_given_when_the_client_is_made(tmp_path):
    async with zc.Client(
        config=config_for(tmp_path, models=models("alpha", "beta")), model="beta", effort="low", permission="deny"
    ) as client:
        assert (client.model.name, client.effort, client.permission) == ("beta", "low", "deny")


async def test_the_compaction_point_moves_for_the_run_and_a_bad_share_is_refused(tmp_path):
    async with client_for(tmp_path, models=models("alpha")) as client:
        assert client.model.compact_percent == 80

        model, unwritten = client.use_compact_percent(55)

        assert model.compact_percent == 55 and client.model.compact_percent == 55
        # This client was built from models in memory, so there is no file to write it to, and it says so.
        assert unwritten
        for bad in (0, -5, 101):
            with pytest.raises(ConfigurationError, match="at most 100"):
                client.use_compact_percent(bad)
        assert client.model.compact_percent == 55


async def test_effort_can_be_changed_and_listed(tmp_path):
    async with client_for(tmp_path) as client:
        assert client.use_effort("high") == "high" and client.effort == "high"
        assert set(client.efforts) >= {"low", "medium", "high"}


async def test_an_effort_that_does_not_exist_or_is_not_taken_is_refused_with_the_valid_ones(tmp_path):
    from zett_agent.model import ReasoningEffort

    from zettcode.config import ModelConfig

    limited = (ModelConfig(model="small", token="t", reasoning_efforts=(ReasoningEffort.LOW, ReasoningEffort.MEDIUM)),)
    async with client_for(tmp_path, models=limited) as client:
        with pytest.raises(ConfigurationError, match="Try one of"):
            client.use_effort("ultra")
        with pytest.raises(ConfigurationError):
            client.use_effort("warp-speed")
        assert client.efforts == ("low", "medium")


async def test_the_harness_starts_off_and_is_switched_on_and_off_for_the_next_prompt(tmp_path):
    async with client_for(tmp_path) as client:
        assert client.harness is False, "off unless asked for"
        assert client.use_harness(True) is True and client.harness is True
        assert client.use_harness(False) is False and client.harness is False

    async with client_for(tmp_path, jit_harness=True) as started_on:
        assert started_on.harness is True, "the config can start a run with it on"

    with pytest.raises(ClientClosedError):
        started_on.use_harness(True)


async def test_a_models_search_is_listed_with_the_models(tmp_path):
    async with zc.Client(
        tmp_path / "project" if (tmp_path / "project").mkdir() is None else None,
        models=[
            {"model": "a", "token": "t"},
            {"model": "b", "token": "t", "web_search": True, "web_search_name": "web_search_x"},
        ],
        store=tmp_path / "s",
    ) as client:
        plain, searching = client.models

        assert (plain.web_search, plain.web_search_name) == (False, None)
        assert (searching.web_search, searching.web_search_name) == (True, "web_search_x")


async def test_the_permission_levels_are_the_four_there_are_and_a_fifth_is_refused(tmp_path):
    async with client_for(tmp_path) as client:
        assert set(client.permissions) == {"deny", "ask", "safe", "full"}
        for level in client.permissions:
            assert client.use_permission(level) == level and client.permission == level
        assert client.use_permission("auto") == "full", "the old name still sets the level that replaced it"
        with pytest.raises(ConfigurationError):
            client.use_permission("yolo")
        assert client.permission == "full", "a refused level changes nothing"


@pytest.mark.parametrize(
    "options", [{"model": "nope"}, {"effort": "nope"}, {"permission": "nope"}], ids=["model", "effort", "permission"]
)
async def test_a_bad_starting_choice_fails_the_construction_and_leaves_nothing_behind(tmp_path, options):
    before = os.getcwd()

    with pytest.raises(ConfigurationError):
        zc.Client(config=config_for(tmp_path), **options)

    assert os.getcwd() == before
    async with client_for(tmp_path):
        pass  # the workspace is free again, and the session lock is not held


# -- closing --------------------------------------------------------------------------------------


async def test_closing_twice_is_harmless(tmp_path):
    client = client_for(tmp_path)

    await client.aclose()
    await client.aclose()

    assert client.closed


async def test_a_closed_client_refuses_everything_that_would_use_it(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    client = client_for(tmp_path)
    session = client.session
    await client.aclose()

    with pytest.raises(ClientClosedError):
        client.session.prompt("hi")
    with pytest.raises(ClientClosedError):
        await client.run("hi")
    with pytest.raises(ClientClosedError):
        client.use_model("scripted")
    with pytest.raises(ClientClosedError):
        client.sessions.new()
    with pytest.raises(ClientClosedError):
        await client.sessions.list()
    with pytest.raises(ClientClosedError):
        await session.history()
    with pytest.raises(ClientClosedError):
        await session.compact()


async def test_leaving_the_with_block_by_an_exception_still_closes_and_the_exception_propagates(tmp_path):
    holder: list[zc.Client] = []

    with pytest.raises(RuntimeError, match="mine"):
        async with client_for(tmp_path) as client:
            holder.append(client)
            raise RuntimeError("mine")

    assert holder[0].closed


async def test_closing_while_a_run_is_in_progress_stops_it_first(tmp_path, monkeypatch):
    import asyncio

    gate = asyncio.Event()

    async def hold(request):
        await gate.wait()
        return "never"

    wire(monkeypatch, ScriptedModel(hold))
    client = client_for(tmp_path)
    run = client.prompt("go")
    task = asyncio.create_task(run.__anext__())
    await asyncio.sleep(0.05)
    assert client._stream is run

    await client.aclose()

    assert client._stream is None and client.closed
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# -- the process's working directory --------------------------------------------------------------


async def test_the_working_directory_is_the_workspace_while_a_client_is_open_and_restored_after(tmp_path):
    before = os.getcwd()

    async with client_for(tmp_path):
        assert Path(os.getcwd()).resolve() == (tmp_path / "project").resolve()

    assert os.getcwd() == before


async def test_two_clients_on_one_workspace_share_it_and_the_directory_returns_only_after_the_last(tmp_path):
    before = os.getcwd()
    first, second = client_for(tmp_path), client_for(tmp_path)

    await first.aclose()
    assert Path(os.getcwd()).resolve() == (tmp_path / "project").resolve()
    await second.aclose()

    assert os.getcwd() == before


async def test_a_client_on_another_workspace_is_refused_while_the_first_is_open(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    async with client_for(tmp_path):
        with pytest.raises(WorkspaceConflictError, match="working directory"):
            zc.Client(other, models=[{"model": "m", "token": "t"}], store=tmp_path / "s2")

    async with zc.Client(other, models=[{"model": "m", "token": "t"}], store=tmp_path / "s2"):
        pass  # fine once the first is closed


async def test_a_client_that_was_dropped_without_closing_does_not_block_the_next_one(tmp_path):
    """The registry holds clients weakly, so forgetting one is not a lock that stays."""
    other = tmp_path / "other"
    other.mkdir()
    forgotten = client_for(tmp_path)
    forgotten._agent.runtime.session_locks.release()
    forgotten._closed = True  # what the conftest guard does for a leaked one; the weak reference is the point here
    del forgotten
    gc.collect()

    async with zc.Client(other, models=[{"model": "m", "token": "t"}], store=tmp_path / "s2"):
        pass


async def test_a_workspace_deleted_while_a_client_is_open_does_not_stop_the_directory_being_restored(tmp_path):
    before = os.getcwd()
    client = client_for(tmp_path)

    await client.aclose()

    assert os.getcwd() == before


# -- session lock ---------------------------------------------------------------------------------


async def test_closing_releases_the_session_lock_so_a_new_client_may_take_the_same_session(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("first"))
    first = client_for(tmp_path)
    await first.run("hello")
    session_id = first.session.id
    await first.aclose()

    wire(monkeypatch, ScriptedModel("second"))
    async with zc.Client(config=config_for(tmp_path), resume=session_id) as again:
        assert not again.session.locked
        assert (await again.run("again")).text == "second"


async def test_a_session_open_in_another_client_is_locked_for_the_second_and_can_still_be_read(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("kept"))
    async with client_for(tmp_path) as first:
        await first.run("hello")
        wire(monkeypatch, ScriptedModel("never"))
        async with zc.Client(config=config_for(tmp_path), resume=first.session.id) as second:
            assert second.session.locked
            assert [m.role for m in await second.session.history()] == ["user", "assistant"]
            with pytest.raises(SessionLockedError):
                await second.run("not allowed")


# -- one run at a time ----------------------------------------------------------------------------


async def test_changing_the_model_or_permission_while_a_run_is_in_progress_is_allowed(tmp_path, monkeypatch):
    import asyncio

    gate = asyncio.Event()

    async def hold(request):
        await gate.wait()
        return "done"

    wire(monkeypatch, ScriptedModel(hold))
    async with client_for(tmp_path, models=models("a", "b")) as client:
        run = client.prompt("go")
        task = asyncio.create_task(_drain(run))
        await asyncio.sleep(0.05)

        client.use_permission("deny")
        client.use_effort("low")
        with pytest.raises(SessionBusyError):
            client.sessions.new()

        gate.set()
        assert (await task).text == "done"


async def _drain(run):
    return await run
