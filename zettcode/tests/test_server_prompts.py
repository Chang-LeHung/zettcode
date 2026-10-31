"""A prompt streamed as server-sent events: the frames, the answers to approvals, and stopping a run."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from server_fakes import FakeClient, FakeRun
from zettcode.sdk.errors import RunError, SessionBusyError
from zettcode.sdk.events import (
    ApprovalRequested,
    CompactionDelta,
    CompactionFinished,
    Finished,
    Notice,
    ReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    Steered,
    SteeringFinished,
    SteeringInterrupted,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
)
from zettcode.sdk.types import Compaction, RunResult, ToolRecord, Usage
from zettcode.server.app import error_body, failure_of, sse_frame
from zettcode.server.runner import approval_handler
from zettcode.server.schemas import ApprovalPolicy
from zettcode.server.settings import Settings

#: The session every event in this file belongs to.
SESSION = "session-1"


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[httpx.AsyncClient]:
    from zettcode.server.app import create_app

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
            Notice(SESSION, "an MCP server is down", "warn"),
            Notice(SESSION, "Starting MCP server 'docs' (process)…"),
            Steered(SESSION, "one more thing"),
            TextDelta(SESSION, "done"),
        ]
    )
    async with serve(FakeClient(runs=[run])) as http:
        body = (await http.post("/prompts", json={"text": "go"})).text

    events = payloads(body, "event")
    assert events[0] == {"type": "compaction_finished", "applied": True, "summary": "summary"}
    assert events[1] == {"type": "notice", "text": "an MCP server is down", "level": "warn"}
    assert events[2] == {"type": "notice", "text": "Starting MCP server 'docs' (process)…", "level": "info"}
    assert events[3] == {"type": "steered", "text": "one more thing"}
    assert events[4] == {"type": "text_delta", "text": "done"}


async def test_the_events_that_mark_a_span_keep_their_names_and_the_text_they_carry():
    run = FakeRun(
        [
            ReasoningStarted(SESSION),
            ReasoningFinished(SESSION),
            CompactionDelta(SESSION, "the gist"),
            SteeringFinished(SESSION),
            SteeringInterrupted(SESSION, "first"),
            TextDelta(SESSION, "done"),
        ]
    )
    async with serve(FakeClient(runs=[run])) as http:
        body = (await http.post("/prompts", json={"text": "go"})).text

    assert payloads(body, "event")[:5] == [
        {"type": "reasoning_started"},
        {"type": "reasoning_finished"},
        {"type": "compaction_delta", "text": "the gist"},
        {"type": "steering_finished"},
        {"type": "steering_interrupted", "text": "first"},
    ]


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


async def test_a_prompt_may_choose_how_it_uses_the_prompt_cache():
    """A one-off report asks not to extend the cache; a prompt that says nothing takes the default."""
    client = FakeClient()

    async with serve(client) as http:
        await http.post("/prompts", json={"text": "read only", "cache": "read"})
        await http.post("/prompts", json={"text": "as usual"})

    assert client.prompt_options[-2]["cache"] == "read"
    assert client.prompt_options[-1]["cache"] is None


async def test_a_cache_word_the_schema_does_not_know_is_refused_before_a_run_starts():
    """A typo is the caller's to fix, and a 422 reaches them; an error frame would arrive after a turn was drawn."""
    client = FakeClient()

    async with serve(client) as http:
        refused = await http.post("/prompts", json={"text": "go", "cache": "sometimes"})

    assert refused.status_code == 422
    assert refused.json()["error"] == "invalid" and "cache" in refused.json()["message"]
    assert client.prompt_options == [], "nothing was started"


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


async def test_a_side_question_streams_its_answer_in_the_frames_a_prompt_uses_and_joins_nothing():
    client = FakeClient()

    async with serve(client) as http:
        response = await http.post("/sessions/current/ask/stream", json={"question": "the pager"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    deltas = [event["text"] for event in payloads(response.text, "event") if event["type"] == "text_delta"]
    assert deltas == ["about ", "the pager"], "the answer arrives in pieces, not once at the end"
    assert payloads(response.text, "result")[0]["text"] == "about the pager"
    assert client.session.asked_side == ["the pager"]
    assert client.asked == [], "a side question is not a prompt"


async def test_a_side_question_is_refused_while_a_run_goes_and_cancel_stops_a_streamed_one():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta(SESSION, "working")], hold=hold)])

    async with serve(client) as http:
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        refused = await http.post("/sessions/current/ask/stream", json={"question": "meanwhile"})
        await http.post("/runs/cancel")
        await first

        client.session.side_hold = asyncio.Event()
        side = asyncio.ensure_future(http.post("/sessions/current/ask/stream", json={"question": "slowly"}))
        await until(lambda: client.session.asked_side == ["slowly"])
        during = await http.post("/prompts", json={"text": "too soon"})
        stopped = await http.post("/runs/cancel")
        body = (await side).text

    assert refused.status_code == 409 and refused.json()["error"] == "busy"
    assert during.status_code == 409, "a prompt cannot start under a side question that is being answered"
    assert stopped.json() == {"cancelled": True}
    assert payloads(body, "cancelled") and not payloads(body, "result")


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


async def test_the_compaction_point_cannot_move_while_a_run_is_going_and_other_settings_still_can():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta(SESSION, "working")], hold=hold)])

    async with serve(client) as http:
        first = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: client.asked)
        refused = await http.patch("/settings", json={"compact_percent": 50})
        await http.post("/runs/cancel")
        await first
        moved = await http.patch("/settings", json={"compact_percent": 50})

    assert refused.status_code == 409 and refused.json()["error"] == "busy"
    assert moved.status_code == 200 and moved.json()["model"]["compact_percent"] == 50


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
