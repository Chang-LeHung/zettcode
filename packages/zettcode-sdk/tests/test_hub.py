"""The headless `/hub` document: sessions, daemons, and the messages between sessions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult
from zettcode.engine.plugins.context import PluginContext
from zettcode.sdk.commandline import CommandLine
from zettcode.sdk.hub import hub_markdown


def _context(tmp_path: Path) -> PluginContext:
    return PluginContext(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)),
        {},
        name="commandline",
    )


def test_the_document_names_the_sessions_daemons_and_messages():
    document = hub_markdown(
        {
            "sessions": [
                {"session_id": "s-1", "handle": "api", "title": "Pagination", "status": "working", "kind": "zettcode"}
            ],
            "daemons": [
                {"session_id": "s-2", "name": "review-api", "title": "API review", "status": "idle", "workspace": "/w"}
            ],
            "edges": [{"a": "s-1", "b": "s-2", "count": 3}],
            "error": "",
        }
    )

    assert "# Who is here" in document
    assert "`api` — Pagination (working, zettcode)" in document
    assert "`review-api` — API review (idle, `/w`)" in document
    assert "`api` ↔ `review-api`: 3 messages" in document


def test_an_unreadable_graph_does_not_claim_nobody_is_connected():
    error = "The message graph could not be read: broker is down"
    document = hub_markdown({"sessions": [], "daemons": [], "edges": [], "error": error})

    assert "No session list could be read" in document
    assert "No other session is connected" not in document, "the host cannot know that without a roster"
    assert error in document


def test_an_empty_graph_with_no_error_says_nobody_is_connected():
    document = hub_markdown({"sessions": [], "daemons": [], "edges": [], "error": ""})

    assert "No other session is connected" in document


async def test_the_plain_command_opens_the_hub_as_a_document(tmp_path: Path):
    ctx = _context(tmp_path)
    CommandLine().activate(ctx)
    command = next(item for item in ctx.commands.commands if item.name == "/hub")

    async def hub() -> dict[str, object]:
        return {"sessions": [], "daemons": [], "edges": [], "error": ""}

    host = SimpleNamespace(hub=hub)
    result = await command.handler(PlainCommandContext(host=host))  # type: ignore[arg-type]

    assert isinstance(result, TextCommandResult)
    assert result.markdown.startswith("# Who is here")
    assert command.when_busy == "now"


async def test_a_host_failure_is_the_front_ends_to_report(tmp_path: Path):
    """The handler does not turn a real fault into a toast; the runner maps what it raises."""
    ctx = _context(tmp_path)
    CommandLine().activate(ctx)
    command = next(item for item in ctx.commands.commands if item.name == "/hub")

    async def hub() -> dict[str, object]:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await command.handler(PlainCommandContext(host=SimpleNamespace(hub=hub)))  # type: ignore[arg-type]
