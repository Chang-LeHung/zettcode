"""The one-call forms: ``prompt`` for async code and ``prompt_sync`` for code that is not."""

from __future__ import annotations

import os

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, config_for, models, wire
from zettcode.sdk.errors import RunError, RunTimeoutError


async def test_one_prompt_makes_a_client_runs_and_closes_everything_again(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("the answer"))
    before = os.getcwd()

    result = await zc.prompt("question", config=config_for(tmp_path))

    assert result.text == "the answer" and os.getcwd() == before


async def test_one_prompt_can_be_made_from_models_and_a_workspace_alone(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("hello"))
    workspace = tmp_path / "w"
    workspace.mkdir()

    result = await zc.prompt(
        "hi", workspace=workspace, models=[{"model": "m", "token": "t"}], store=tmp_path / "s", permission="deny"
    )

    assert result.text == "hello"


async def test_one_prompt_passes_its_run_options_through(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a"))
    seen = []

    result = await zc.prompt("q", config=config_for(tmp_path), on_event=seen.append, timeout=30)

    assert result.ok and any(isinstance(e, zc.Finished) for e in seen)


async def test_one_prompt_closes_the_client_when_the_run_fails(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(ValueError("bad")))
    before = os.getcwd()

    with pytest.raises(RunError):
        await zc.prompt("q", config=config_for(tmp_path))

    assert os.getcwd() == before
    async with zc.Client(config=config_for(tmp_path)):
        pass  # the workspace and the session lock are free again


async def test_one_prompt_closes_the_client_when_it_times_out(tmp_path, monkeypatch):
    import asyncio

    async def stuck(request):
        await asyncio.Event().wait()

    wire(monkeypatch, ScriptedModel(stuck))

    with pytest.raises(RunTimeoutError):
        await zc.prompt("q", config=config_for(tmp_path), timeout=0.1)

    async with zc.Client(config=config_for(tmp_path)):
        pass


async def test_one_prompt_reports_a_bad_configuration_before_doing_anything(tmp_path):
    # `prompt` passes its settings straight to `Client`, whose signature is where they are named: a name that is
    # not one of them is refused by Python at the call, before a client (or a session, or a provider) is made.
    with pytest.raises(TypeError, match="unexpected keyword argument 'bogus'"):
        await zc.prompt("q", workspace=tmp_path, models=[{"model": "m", "token": "t"}], bogus=1)


async def test_one_prompt_can_continue_a_stored_session(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("first", "second"))
    first = await zc.prompt("one", config=config_for(tmp_path))

    second = await zc.prompt("two", config=config_for(tmp_path), resume=first.session_id)

    assert second.session_id == first.session_id


async def test_the_text_is_positional_only_so_it_cannot_collide_with_an_option(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("ok"))

    with pytest.raises(TypeError):
        await zc.prompt(text="q", config=config_for(tmp_path))  # type: ignore[call-arg]


def test_the_blocking_form_runs_to_the_end_outside_an_event_loop(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("sync answer"))

    result = zc.prompt_sync("question", config=config_for(tmp_path), model="scripted")

    assert result.text == "sync answer"


def test_the_blocking_form_can_be_called_again_and_again(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))

    first = zc.prompt_sync("a", config=config_for(tmp_path))
    second = zc.prompt_sync("b", config=config_for(tmp_path), resume=first.session_id)

    assert (first.text, second.text) == ("one", "two")


async def test_the_blocking_form_refuses_to_run_inside_a_running_loop_instead_of_deadlocking(tmp_path):
    with pytest.raises(RuntimeError, match="running event loop"):
        zc.prompt_sync("q", config=config_for(tmp_path), models=models("m"))
