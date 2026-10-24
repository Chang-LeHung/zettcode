"""A request that goes wrong, through the real shell and a real provider: what the reader sees, and that it ends.

The provider is the real ``OpenAIProvider`` over an HTTP exchange written in the test, so what fails is what fails in
use: the library's own exceptions, wrapped the way zett-agent wraps them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from zett_agent.model import RetryOptions
from zett_agent.providers.openai import OpenAIProvider

from zettcode.app.agent.agent import TerminalAgent
from zettcode.app.agent.conversation.text import QUIET_SECONDS
from zettcode.app.ui.app import ZettCodeApp
from zettcode.app.ui.shell import EMPTY_REPLY
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.tui.testing import Harness

FAST = RetryOptions(base_delay=0.0, max_delay=0.0, max_retries=1)


def sse(*chunks: dict) -> str:
    import json

    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def piece(text: str | None = None, *, finish: str | None = None) -> dict:
    delta = {"content": text} if text is not None else {}
    return {
        "id": "1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


@pytest.fixture
def shell(tmp_path: Path, monkeypatch):
    """Build a shell whose provider answers with whatever handler the test gives."""

    def build(handler) -> tuple[ZettCodeApp, Harness]:
        monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
        monkeypatch.setattr(
            runtime_module,
            "_build_provider",
            lambda selected: OpenAIProvider(
                "gpt-9", "k", transport=httpx.MockTransport(handler), base_url="https://x/v1", retry=FAST
            ),
        )
        (tmp_path / "work").mkdir(exist_ok=True)
        config = ZettCodeConfig(
            workspace=tmp_path / "work",
            models=(ModelConfig(model="gpt-9", token="k"),),
            store=tmp_path / "sessions",
            plugins_enabled=False,
            skills_enabled=False,
            mcp_enabled=False,
            sessions_enabled=False,
            statusline_hidden=("pet",),
        )
        app = ZettCodeApp(TerminalAgent(runtime_module.ZettCodeEngine.preview(config)))
        app.app.resize(110, 30)
        app.app.mount()
        return app, Harness(app=app.app)

    return build


async def ask(app: ZettCodeApp, harness: Harness, text: str = "hello") -> str:
    harness.write(text)
    harness.press("enter")
    await asyncio.wait_for(app.task, 10)
    return harness.render().text


def status(code: int, body: object) -> object:
    return lambda request: httpx.Response(code, json=body)


# -- a refusal says why -------------------------------------------------------------------------------------------


async def test_a_model_that_does_not_exist_is_shown_with_the_servers_reason_and_what_to_do(shell):
    app, harness = shell(status(404, {"error": {"message": "The model `gpt-9` does not exist"}}))

    screen = await ask(app, harness)

    flat = " ".join(screen.split())
    assert "The model `gpt-9` does not exist" in flat and "HTTP 404" in flat
    assert "/config" in flat
    assert flat.count("The model `gpt-9` does not exist") == 1, (
        "said once, though the library says it in its own sentence too"
    )


async def test_a_refused_token_is_shown_with_what_to_do_and_none_of_the_token(shell):
    app, harness = shell(status(401, {"error": {"message": "Incorrect API key provided: sk-proj-****wxyz"}}))

    screen = await ask(app, harness)

    flat = " ".join(screen.split())  # the row wraps at the window, and a phrase may be split across two lines
    assert "HTTP 401" in flat and "check the token with /config" in flat, screen
    assert "sk-proj" not in flat and "wxyz" not in flat


async def test_a_server_that_is_down_after_its_retries_says_what_it_answered(shell):
    seen: list[int] = []

    def handler(request):
        seen.append(1)
        return httpx.Response(503, json={"error": {"message": "service unavailable, try later"}})

    app, harness = shell(handler)

    screen = await ask(app, harness)

    assert "HTTP 503: service unavailable, try later" in screen
    assert len(seen) == 2, "one try and the one retry the provider was given, not a hang"


async def test_a_refused_connection_says_what_the_connection_did(shell):
    def handler(request):
        raise httpx.ConnectError("[Errno 61] Connection refused")

    app, harness = shell(handler)

    assert "ConnectError: [Errno 61] Connection refused" in await ask(app, harness)


async def test_the_request_ends_the_wait_row_is_settled_and_the_composer_is_free_again(shell):
    app, harness = shell(status(500, {"error": {"message": "boom"}}))

    screen = await ask(app, harness)

    assert "Processed for" in screen and "Processing (" not in screen
    assert not app._busy and app._activity.value == "ready"
    harness.write("again")
    assert app.composer.text == "again", "the composer takes the next message"


async def test_the_error_is_the_last_thing_said_before_the_line_that_ends_the_request(shell):
    app, harness = shell(status(500, {"error": {"message": "boom"}}))

    await ask(app, harness)
    texts = [getattr(entry, "text", "") for entry in app.transcript.entries]

    error = next(index for index, text in enumerate(texts) if "HTTP 500" in text)
    assert "Processed for" in texts[error + 1]


# -- a request that quietly produced nothing ---------------------------------------------------------------------------


async def test_an_empty_reply_is_announced_instead_of_leaving_a_request_that_seems_lost(shell):
    app, harness = shell(
        lambda request: httpx.Response(
            200, text=sse(piece(finish="stop")), headers={"content-type": "text/event-stream"}
        )
    )

    screen = await ask(app, harness)

    assert EMPTY_REPLY in screen and "Processed for" in screen


async def test_a_reply_with_text_is_not_called_empty(shell):
    app, harness = shell(
        lambda request: httpx.Response(
            200, text=sse(piece("Hello there"), piece(finish="stop")), headers={"content-type": "text/event-stream"}
        )
    )

    screen = await ask(app, harness)

    assert "Hello there" in screen and EMPTY_REPLY not in screen


async def test_a_reply_that_is_only_a_failure_is_not_also_called_empty(shell):
    app, harness = shell(status(500, {"error": {"message": "boom"}}))

    assert EMPTY_REPLY not in await ask(app, harness)


# -- a server that never answers ---------------------------------------------------------------------------------------


async def test_a_server_that_never_answers_is_said_to_have_gone_quiet_and_the_request_can_be_stopped(
    shell, monkeypatch
):
    from zettcode.app.agent.conversation import text

    monkeypatch.setattr(text, "QUIET_SECONDS", 0.2)

    async def never(request):
        await asyncio.sleep(60)

    app, harness = shell(never)
    harness.write("hello")
    harness.press("enter")
    try:
        deadline = asyncio.get_running_loop().time() + 5
        while "nothing from the model" not in harness.render().text:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(harness.render().text)
            await asyncio.sleep(0.05)
            app.transcript.advance_frame()
        screen = harness.render().text
        assert "^C/Esc to interrupt" in screen

        harness.press("escape")
        await asyncio.wait_for(app.task, 5)

        assert "stopped" in harness.render().text and not app._busy
    finally:
        if app._task is not None and not app._task.done():
            app._task.cancel()
            await asyncio.gather(app._task, return_exceptions=True)


def test_the_threshold_is_long_enough_for_a_slow_first_token_and_short_enough_to_notice():
    assert 10 <= QUIET_SECONDS <= 60
