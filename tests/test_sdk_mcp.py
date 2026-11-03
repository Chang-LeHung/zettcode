"""MCP news through the SDK: what a program running a prompt is told about servers that start or cannot.

The real MCP extension and the real agent loop run; only the model is scripted and the servers are files that name
a command that does not exist, so no process is started.
"""

from __future__ import annotations

import json
from pathlib import Path

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, config_for, wire
from zettcode.sdk.events import Notice


def make(tmp_path: Path, servers: dict[str, object]) -> zc.Client:
    file = tmp_path / "mcp.json"
    file.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return zc.Client(config=config_for(tmp_path, mcp_enabled=True, mcp_config=file, mcp_scope="global"))


async def notices_of(stream) -> list[Notice]:
    return [event async for event in stream if isinstance(event, Notice)]


async def test_a_server_starting_is_progress_and_a_server_that_cannot_is_a_warning(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one"))
    async with make(tmp_path, {"docs": {"command": "/definitely/not/here"}}) as client:
        notices = await notices_of(client.prompt("hello"))

    by_text = {notice.text: notice.level for notice in notices}
    assert by_text["Starting MCP server 'docs' (process)…"] == "info"
    [down] = [level for text, level in by_text.items() if "is not available" in text]
    assert down == "warn", "a server that is down is something the reader may need to act on"


async def test_an_entry_the_file_cannot_use_is_a_warning_that_names_it(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one"))
    async with make(tmp_path, {"broken entry": {"nothing": True}}) as client:
        notices = await notices_of(client.prompt("hello"))

    [ignored] = [notice for notice in notices if "is ignored" in notice.text]
    assert ignored.level == "warn" and "broken entry" in ignored.text


async def test_the_news_is_said_at_the_first_turn_and_not_again_at_the_next(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with make(tmp_path, {"docs": {"command": "/definitely/not/here"}}) as client:
        first = await notices_of(client.prompt("hello"))
        second = await notices_of(client.prompt("again"))

    assert first, "the first turn explains why it was slow and what is missing"
    assert second == [], "a server that stays down is not announced at the top of every turn"
