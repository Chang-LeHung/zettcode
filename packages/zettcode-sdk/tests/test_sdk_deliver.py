"""Delivering a message into this session: the same two ways a reader's message has."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, config_for, wire
from zettcode.sdk.errors import SessionNotFoundError


def make(tmp_path: Path) -> zc.Client:
    return zc.Client(config=config_for(tmp_path))


async def drive(run: object) -> None:
    """Await a run in the background: a ``RunStream`` is awaitable, not a coroutine ``create_task`` takes."""
    await run  # type: ignore[misc]


async def _history(client: zc.Client) -> list[str]:
    """Return what the reader would see as this session's own messages; nothing written is an empty list."""
    try:
        stored = await client.session.history()
    except SessionNotFoundError:
        return []
    return [message.text for message in stored if message.role == "user"]


async def test_a_message_delivered_while_idle_becomes_the_next_turn(tmp_path, monkeypatch):
    """Nothing is running, so the inbox starts a turn: the model reads it and the conversation keeps it."""
    model = wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        assert client.deliver("the build finished") == "started"

        for _ in range(500):
            if await _history(client):
                break
            await asyncio.sleep(0.01)

        assert await _history(client) == ["the build finished"]
        assert model.requests, "the turn actually reached the model"


async def test_a_followup_delivered_while_idle_starts_a_turn_as_well(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        assert client.deliver("later", mode="followup") == "started"

        for _ in range(500):
            if await _history(client):
                break
            await asyncio.sleep(0.01)

        assert await _history(client) == ["later"]


async def test_a_message_with_a_picture_a_model_cannot_see_is_refused(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        with pytest.raises(zc.ConfigurationError):
            client.deliver("look", images=[zc.Image(b"\x89PNG", "image/png")])


async def test_a_mode_that_is_not_steer_or_followup_is_refused(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        with pytest.raises(ValueError):
            client.deliver("hello", mode="sideways")
