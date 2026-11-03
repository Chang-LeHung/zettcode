"""Smoke: the SDK drives the real agent, with only the provider scripted."""

from __future__ import annotations

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, config_for, wire


async def test_a_prompt_runs_through_the_real_agent_and_returns_the_answer(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("Hello from the model."))

    async with zc.Client(config=config_for(tmp_path)) as client:
        result = await client.prompt("say hello")

    assert result.text == "Hello from the model."
    assert result.ok and result.usage.requests == 1
    assert result.usage.input_tokens == 100 and result.usage.output_tokens == 20
    assert len(model.requests) == 1


async def test_a_prompt_can_be_iterated_for_its_events(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("abcdef", chunk=2))

    async with zc.Client(config=config_for(tmp_path)) as client:
        async with client.prompt("go") as run:
            events = [event async for event in run]

    assert "".join(e.text for e in events if isinstance(e, zc.TextDelta)) == "abcdef"
    assert isinstance(events[-1], zc.Finished) or any(isinstance(e, zc.Finished) for e in events)
    assert run.result is not None and run.result.text == "abcdef"


@pytest.mark.parametrize("name", ["run", "stream", "prompt"])
async def test_run_stream_and_prompt_are_the_same_entry(tmp_path, monkeypatch, name):
    wire(monkeypatch, ScriptedModel("same"))

    async with zc.Client(config=config_for(tmp_path)) as client:
        outcome = getattr(client, name)("go")
        result = await outcome

    assert result.text == "same"
