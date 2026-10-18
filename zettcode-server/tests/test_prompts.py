"""A prompt streamed as server-sent events: the frames, the answers to approvals, and stopping a run."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from fakes import FakeClient, FakeRun
from zettcode.sdk.errors import RunError, SessionBusyError
from zettcode.sdk.events import (
    ApprovalRequested,
    CompactionFinished,
    Finished,
    Notice,
    ReasoningDelta,
    Steered,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
)
from zettcode.sdk.types import Compaction, RunResult, ToolRecord, Usage
from zettcode_server.app import error_body, failure_of, sse_frame
from zettcode_server.runner import approval_handler
from zettcode_server.schemas import ApprovalPolicy
from zettcode_server.settings import Settings

#: The session every event in this file belongs to.
SESSION = "session-1"


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[httpx.AsyncClient]:
    from zettcode_server.app import create_app

    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10) as http:
            yield http


def frames(text: str) -> list[tuple[str, str]]:
    """Return ``(event, data)`` for every frame of an SSE body, cut in the two places the format cuts them."""
    found: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = "\n".join(line[len("data: ") :] for line in lines if line.startswith("data: "))
        found.append((event, data))
    return found


def payloads(text: str, name: str) -> list[dict[str, object]]:
    import json

    return [json.loads(data) for event, data in frames(text) if event == name]


async def until(condition, seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("waited for something that did not happen")


async def test_a_run_streams_each_event_and_ends_with_the_result():
    run = FakeRun(
        [
            ReasoningDelta(SESSION, "thinking"),
            TextDelta(SESSION, "Hello"),
            ToolStarted(SESSION, "call-1", "read_file", {"path": "README.md"}),
            ToolFinished(SESSION, "call-1", "read_file", "the readme", True),
            UsageUpdated(SESSION, Usage(input_tokens=5, output_tokens=1)),
            Finished(SESSION, "Hello"),
        ],
        result=RunResult(
            text="Hello",
            session_id="session-1",
            usage=Usage(input_tokens=5, output_tokens=1),
            tools=(ToolRecord("call-1", "read_file", {"path": "README.md"}, "the readme", True),),
        ),
    )
    client = FakeClient(runs=[run])
    async with serve(client) as http:
        response = await http.post("/prompts", json={"text": "say hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert [event for event, _ in frames(body)] == ["event", "event", "event", "event", "event", "event", "result"]
    assert payloads(body, "event")[0] == {"type": "reasoning_delta", "text": "thinking"}
    assert payloads(body, "event")[1] == {"type": "text_delta", "text": "Hello"}
    started = payloads(body, "event")[2]
    assert started == {
        "type": "tool_started",
        "call_id": "call-1",
        "name": "read_file",
        "arguments": {"path": "README.md"},
    }
    finished = payloads(body, "event")[3]
    assert finished["ok"] is True and finished["output"] == "the readme"
    result = payloads(body, "result")[0]
    assert result["text"] == "Hello" and result["session_id"] == "session-1"
    assert result["usage"]["input_tokens"] == 5
    assert result["tools"][0]["name"] == "read_file"
    assert client.asked == ["say hello"]


async def test_the_rest_of_the_events_keep_their_fields():
    run = FakeRun(
        [
            CompactionFinished(SESSION, True, Compaction("summary", 10, 2)),
            Notice(SESSION, "an MCP server is down"),
            Steered(SESSION, "one more thing"),
            TextDelta(SESSION, "done"),
        ]
    )
    async with serve(FakeClient(runs=[run])) as http:
        body = (await http.post("/prompts", json={"text": "go"})).text

    events = payloads(body, "event")
    assert events[0] == {"type": "compaction_finished", "applied": True, "summary": "summary"}
    assert events[1] == {"type": "notice", "text": "an MCP server is down"}
    assert events[2] == {"type": "steered", "text": "one more thing"}
    assert events[3] == {"type": "text_delta", "text": "done"}


async def test_the_approval_rule_of_the_request_is_the_one_the_run_answers_with():
    seen: list[object] = []
    first = FakeRun([ApprovalRequested(SESSION, "call-1", "pytest -q")])
    second = FakeRun([ApprovalRequested(SESSION, "call-2", "rm -rf /")])
    client = FakeClient(runs=[first, second])

    original = client.prompt

    def prompt(text, **options):
        seen.append(options.get("on_approval"))
        return original(text, **options)

    client.prompt = prompt  # type: ignore[method-assign]
    async with serve(client) as http:
        ran = await http.post(
            "/prompts", json={"text": "run the tests", "approvals": {"mode": "commands", "commands": ["pytest"]}}
        )
        always = await http.post("/prompts", json={"text": "again", "approvals": {"mode": "auto"}})

    handler = seen[0]
    assert handler is not None
    assert handler(ApprovalRequested(SESSION, "c", "pytest -q")) is True
    assert handler(ApprovalRequested(SESSION, "c", "rm -rf /")) is False
    assert handler(ApprovalRequested(SESSION, "c", "pytest; rm -rf /")) is False, (
        "a chained command is not the approved one"
    )
    assert callable(seen[1]) and seen[1](ApprovalRequested(SESSION, "c", "rm -rf /")) is True
    assert payloads(ran.text, "event")[0]["approved"] is True, "the stream says the handler answered"
    assert payloads(always.text, "event")[0]["approved"] is True


async def test_the_default_rule_denies_every_command():
    handler = approval_handler(ApprovalPolicy())

    assert handler(ApprovalRequested(SESSION, "c", "pytest")) is False
    assert handler(ApprovalRequested(SESSION, "c", "ls")) is False


async def test_a_command_a_rule_could_not_match_is_refused_before_the_stream_opens():
    async with serve(FakeClient()) as http:
        response = await http.post(
            "/prompts", json={"text": "go", "approvals": {"mode": "commands", "commands": ["git status && rm -rf /"]}}
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid"


async def test_a_failure_inside_the_run_ends_the_stream_with_an_error_frame():
    async with serve(
        FakeClient(
            runs=[
                FakeRun(
                    [
                        TextDelta(SESSION, "half"),
                    ],
                    error=RunError("the model went away"),
                )
            ]
        )
    ) as http:
        body = (await http.post("/prompts", json={"text": "go"})).text

    assert payloads(body, "event") == [{"type": "text_delta", "text": "half"}]
    error = payloads(body, "error")[0]
    assert error["error"] == "run" and "the model went away" in error["message"]


async def test_a_second_prompt_while_one_runs_is_refused_with_409_and_the_draft_never_reaches_the_agent():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta(SESSION, "working")], hold=hold)])

    async with serve(client) as http:
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        refused = await http.post("/prompts", json={"text": "the second one"})
        await http.post("/runs/cancel")
        await first

    assert refused.status_code == 409
    assert refused.json()["error"] == "busy"
    assert client.asked == ["the long one"], "the refused prompt never started"


async def test_cancelling_a_run_ends_its_stream_as_cancelled_and_leaves_the_server_ready():
    hold = asyncio.Event()
    run = FakeRun([TextDelta(SESSION, "working")], hold=hold)
    client = FakeClient(runs=[run, FakeRun([TextDelta(SESSION, "next")])])

    async with serve(client) as http:
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "long"}))
        await until(lambda: client.asked)
        cancelled = await http.post("/runs/cancel")
        response = await first
        afterwards = await http.post("/prompts", json={"text": "short"})
        idle = await http.post("/runs/cancel")

    assert cancelled.json() == {"cancelled": True}
    assert run.closed, "the SDK's run was closed, which is what stops the agent"
    assert [event for event, _ in frames(response.text)][-1] == "cancelled"
    assert payloads(response.text, "cancelled")[0] == {"type": "cancelled"}
    assert afterwards.status_code == 200 and payloads(afterwards.text, "result")
    assert idle.json() == {"cancelled": False}


async def test_a_timeout_and_a_busy_error_map_to_the_statuses_a_client_branches_on():
    from zettcode.sdk.errors import (
        ConfigurationError,
        NothingToDoError,
        RunTimeoutError,
        SessionLockedError,
        SessionNotFoundError,
    )

    assert failure_of(SessionNotFoundError("x")) == (404, "not_found")
    assert failure_of(SessionLockedError("x")) == (409, "locked")
    assert failure_of(SessionBusyError("x")) == (409, "busy")
    assert failure_of(NothingToDoError("x")) == (409, "nothing_to_do")
    assert failure_of(ConfigurationError("x")) == (400, "invalid")
    assert failure_of(ValueError("x")) == (400, "invalid")
    assert failure_of(RunTimeoutError(1.0))[0] == 504
    assert failure_of(RunError("x"))[0] == 502
    assert failure_of(KeyError("x")) == (500, "internal")
    assert error_body("busy", "wait") == {"error": "busy", "message": "wait"}


def test_an_sse_frame_is_one_named_event_and_one_data_line():
    assert sse_frame("event", {"type": "text_delta", "text": "a\nb \\ c"}) == (
        b'event: event\ndata: {"type":"text_delta","text":"a\\nb \\\\ c"}\n\n'
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [({}, "text"), ({"text": ""}, "text"), ({"text": "go", "timeout": 0}, "timeout")],
)
async def test_a_prompt_body_is_validated(body, message):
    async with serve(FakeClient()) as http:
        response = await http.post("/prompts", json=body)

    assert response.status_code == 422
    assert message in response.json()["message"]
