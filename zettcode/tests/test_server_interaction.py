"""What a terminal can do mid-run, an HTTP client can too: answer approvals, answer questions, steer, continue."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from server_fakes import FakeClient, FakeRun
from zettcode.sdk.events import ApprovalRequested, QuestionAsked, TextDelta
from zettcode.sdk.types import ResumeInfo, RunResult
from zettcode.server.app import create_app
from zettcode.server.settings import Settings

SESSION = "session-1"


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=15) as http:
            yield http, app


def frames(text: str) -> list[tuple[str, dict[str, object]]]:
    found: list[tuple[str, dict[str, object]]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = "\n".join(line[len("data: ") :] for line in lines if line.startswith("data: "))
        found.append((event, json.loads(data)))
    return found


def of(text: str, name: str) -> list[dict[str, object]]:
    return [payload for event, payload in frames(text) if event == name]


async def until(condition, seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("waited for something that did not happen")


async def test_an_approval_the_client_must_answer_is_streamed_and_posted_back():
    run = FakeRun([ApprovalRequested(SESSION, "call-1", "pytest -q", remember_supported=True)])
    client = FakeClient(runs=[run])
    async with serve(client) as (http, app):
        task = asyncio.ensure_future(
            http.post("/prompts", json={"text": "test it", "approvals": {"mode": "ask"}, "answer_timeout": 10})
        )
        await until(lambda: app.state.runner.pending is not None)
        state = (await http.get("/runs/current")).json()
        answered = await http.post("/runs/approvals", json={"call_id": "call-1", "approve": True, "remember": True})
        response = await task
        settled = await http.get("/runs/current")

    assert state["running"] is True
    assert state["pending"] == {
        "kind": "approval",
        "call_id": "call-1",
        "command": "pytest -q",
        "work_dir": None,
        "timeout_seconds": None,
        "remember_supported": True,
        "question": None,
        "options": [],
        "allow_multiple": False,
    }
    assert answered.json() == {"resolved": True}
    assert run.events[0].approved is True and run.events[0].answered is True
    assert of(response.text, "event")[0]["approved"] is None, "the frame asks; the POST answers"
    assert of(response.text, "result")[0]["text"] == "done"
    assert settled.json() == {"running": False, "pending": None}


async def test_an_approval_can_be_denied():
    run = FakeRun([ApprovalRequested(SESSION, "call-1", "rm -rf /")])
    async with serve(FakeClient(runs=[run])) as (http, app):
        task = asyncio.ensure_future(http.post("/prompts", json={"text": "go", "approvals": {"mode": "ask"}}))
        await until(lambda: app.state.runner.pending is not None)
        await http.post("/runs/approvals", json={"call_id": "call-1", "approve": False})
        await task

    assert run.events[0].approved is False


async def test_an_answer_for_a_call_that_is_not_waiting_resolves_nothing():
    async with serve(FakeClient()) as (http, app):
        idle = await http.post("/runs/approvals", json={"call_id": "call-1", "approve": True})

    assert idle.json() == {"resolved": False}


async def test_an_unanswered_approval_is_denied_after_the_answer_timeout_and_the_run_carries_on():
    run = FakeRun([ApprovalRequested(SESSION, "call-1", "pytest -q")])
    async with serve(FakeClient(runs=[run])) as (http, app):
        response = await http.post(
            "/prompts", json={"text": "go", "approvals": {"mode": "ask"}, "answer_timeout": 0.05}
        )

    assert run.events[0].approved is False
    notes = [payload for payload in of(response.text, "event") if payload["type"] == "notice"]
    assert notes and "denied" in str(notes[0]["text"])
    assert of(response.text, "result"), "the run was not left hanging"


async def test_an_unanswered_question_keeps_waiting_past_the_answer_timeout():
    """An approval gives up on a clock; a question waits for the reader who was asked."""
    run = FakeRun([QuestionAsked(SESSION, "call-1", "Which database?")])
    async with serve(FakeClient(runs=[run])) as (http, app):
        task = asyncio.ensure_future(
            http.post("/prompts", json={"text": "build it", "questions": "ask", "answer_timeout": 0.01})
        )
        await until(lambda: app.state.runner.pending is not None)
        await asyncio.sleep(0.1)

        still = (await http.get("/runs/current")).json()
        assert still["pending"]["kind"] == "question"
        assert run.events[0].answered is False

        answered = await http.post("/runs/questions", json={"call_id": "call-1", "answer": "sqlite"})
        response = await task

    assert answered.json() == {"resolved": True}
    assert run.events[0].answered is True
    assert of(response.text, "result"), "the run carried on from the answer"


async def test_a_question_the_model_asks_is_sent_down_the_stream_and_answered():
    run = FakeRun([QuestionAsked(SESSION, "call-1", "Which database?", ("sqlite", "postgres"), allow_multiple=False)])
    async with serve(FakeClient(runs=[run])) as (http, app):
        task = asyncio.ensure_future(http.post("/prompts", json={"text": "build it", "questions": "ask"}))
        await until(lambda: app.state.runner.pending is not None)
        state = (await http.get("/runs/current")).json()
        answered = await http.post("/runs/questions", json={"call_id": "call-1", "answer": "sqlite"})
        response = await task

    assert state["pending"]["kind"] == "question"
    assert state["pending"]["question"] == "Which database?"
    assert state["pending"]["options"] == ["sqlite", "postgres"]
    assert answered.json() == {"resolved": True}
    assert run.events[0].answered is True
    assert of(response.text, "event")[0]["question"] == "Which database?"


async def test_a_question_can_be_declined_and_by_default_it_is_never_asked_of_the_client():
    run = FakeRun([QuestionAsked(SESSION, "call-1", "Which database?")])
    async with serve(FakeClient(runs=[run])) as (http, app):
        response = await http.post("/prompts", json={"text": "build it"})
        pending = (await http.get("/runs/current")).json()

    assert pending == {"running": False, "pending": None}
    assert of(response.text, "result"), "the default declined it and the run finished"


async def test_a_message_can_be_steered_into_the_run_in_progress_and_not_into_an_idle_one():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta(SESSION, "working")], hold=hold)])
    async with serve(client) as (http, app):
        task = asyncio.ensure_future(http.post("/prompts", json={"text": "long"}))
        await until(lambda: client.asked)
        steered = await http.post("/runs/steer", json={"text": "also update the docs", "mentions": True})
        await http.post("/runs/cancel")
        await task
        idle = await http.post("/runs/steer", json={"text": "anyone there?"})

    assert steered.json() == {"steered": True, "text": "also update the docs"}
    assert client.session.steered == ["also update the docs", "anyone there?"]
    assert idle.json()["steered"] is True, "the fake says yes; the SDK says no when nothing runs"


async def test_an_interrupted_request_is_described_and_can_be_continued_as_a_stream():
    client = FakeClient()
    client.session.resume_info = ResumeInfo("error", "the provider dropped the connection")
    async with serve(client) as (http, _app):
        described = (await http.get("/runs/resumable")).json()
        resumed = await http.post("/runs/resume", json={"approvals": {"mode": "deny"}, "timeout": 5})

    assert described == {"resumable": True, "kind": "error", "description": "the provider dropped the connection"}
    assert of(resumed.text, "result")[0]["text"] == "resumed"
    assert client.session.resume_options["timeout"] == 5


async def test_nothing_to_continue_is_said_rather_than_guessed():
    async with serve(FakeClient()) as (http, _app):
        described = (await http.get("/runs/resumable")).json()

    assert described == {"resumable": False, "kind": None, "description": None}


async def test_a_side_question_is_answered_without_joining_the_conversation():
    client = FakeClient()
    async with serve(client) as (http, _app):
        response = await http.post("/sessions/current/ask", json={"question": "what changed?"})

    assert response.json() == {"answer": "about what changed?"}
    assert client.session.asked_side == ["what changed?"]


async def test_a_side_question_is_refused_while_a_run_is_going_as_the_terminal_queues_it_instead():
    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([TextDelta(SESSION, "working")], hold=hold)])
    async with serve(client) as (http, _app):
        task = asyncio.ensure_future(http.post("/prompts", json={"text": "long"}))
        await until(lambda: client.asked)
        refused = await http.post("/sessions/current/ask", json={"question": "why?"})
        await http.post("/runs/cancel")
        await task

    assert refused.status_code == 409 and refused.json()["error"] == "busy"


async def test_a_session_can_be_named_by_the_model():
    client = FakeClient()
    async with serve(client) as (http, _app):
        response = await http.post("/sessions/current/name")

    assert response.json()["title"] == "Named by the model" and response.json()["current"] is True
    assert client.session.named == 1


async def test_the_conversation_exports_as_a_page_to_download():
    async with serve(FakeClient()) as (http, _app):
        response = await http.get("/sessions/current/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    assert "the conversation" in response.text


async def test_the_plugins_and_the_ones_that_failed_are_listed():
    async with serve(FakeClient()) as (http, _app):
        body = (await http.get("/plugins")).json()

    assert body["loaded"] == ["shell", "usage"]
    assert body["failures"] == ["broken: no such module"]
    # Every row a panel shows: what is compiled in, what is installed, what is off, and what failed.
    assert [(entry["origin"], entry["builtin"], entry["enabled"]) for entry in body["entries"]] == [
        ("shell", True, True),
        ("usage", True, True),
        ("zettcode-acme", False, True),
        ("zettcode-quiet", False, False),
        ("broken", False, True),
    ]
    assert body["entries"][-1]["failure"] == "no such module"


async def test_a_plugin_can_be_switched_off_for_the_next_start():
    client = FakeClient()
    async with serve(client) as (http, _app):
        response = await http.put("/plugins/zettcode-acme", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {
        "name": "zettcode-acme",
        "origin": "zettcode-acme",
        "builtin": False,
        "enabled": False,
        "failure": "",
        "setting": "",
        "switchable": True,
        "why": "",
    }
    assert client.switched == [("zettcode-acme", False)]


async def test_a_builtin_cannot_be_switched_off_over_http():
    async with serve(FakeClient()) as (http, _app):
        response = await http.put("/plugins/shell", json={"enabled": False})

    assert response.status_code == 400
    assert "compiled into the program" in response.json()["message"]


async def test_a_switch_needs_the_enabled_field():
    async with serve(FakeClient()) as (http, _app):
        response = await http.put("/plugins/zettcode-acme", json={})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid"


async def test_images_are_decoded_and_mentions_are_on_by_default():
    client = FakeClient()
    picture = base64.b64encode(b"\x89PNG\r\n\x1a\n fake").decode()
    async with serve(client) as (http, _app):
        response = await http.post(
            "/prompts",
            json={"text": "what is in @README.md and this?", "images": [{"data": picture, "media_type": "image/png"}]},
        )

    assert response.status_code == 200
    options = client.prompt_options[0]
    assert options["mentions"] is True
    (image,) = options["images"]
    assert image.data.startswith(b"\x89PNG") and image.media_type == "image/png"


async def test_an_image_that_is_not_base64_is_refused_before_the_stream_opens():
    async with serve(FakeClient()) as (http, _app):
        response = await http.post(
            "/prompts", json={"text": "look", "images": [{"data": "not base64!", "media_type": "image/png"}]}
        )

    assert response.status_code == 400
    assert "base64" in response.json()["message"]


async def test_an_image_of_a_type_no_model_takes_is_refused_too():
    async with serve(FakeClient()) as (http, _app):
        response = await http.post(
            "/prompts", json={"text": "look", "images": [{"data": "aGk=", "media_type": "image/tiff"}]}
        )

    assert response.status_code == 400 and "image/tiff" in response.json()["message"]


async def test_an_idle_server_says_nothing_is_running():
    async with serve(FakeClient()) as (http, _app):
        state = (await http.get("/runs/current")).json()

    assert state == {"running": False, "pending": None}


async def test_the_finished_run_keeps_its_usage_and_its_tools_in_the_result_frame():
    run = FakeRun(
        [],
        result=RunResult(
            text="all done",
            session_id=SESSION,
            usage=__import__("zettcode.sdk.types", fromlist=["Usage"]).Usage(input_tokens=7, output_tokens=3),
        ),
    )
    async with serve(FakeClient(runs=[run])) as (http, _app):
        body = (await http.post("/prompts", json={"text": "go"})).text

    result = of(body, "result")[0]
    assert result["usage"]["input_tokens"] == 7 and result["usage"]["output_tokens"] == 3
    assert result["text"] == "all done"
