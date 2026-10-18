"""The capabilities around the conversation: `@` candidates, the usage ledger, session stats, self-compaction, doctor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from fakes import FakeClient
from zettcode_server.app import create_app
from zettcode_server.settings import Settings


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


async def test_mentions_lists_the_at_resources_a_prompt_can_carry():
    async with serve(FakeClient()) as http:
        everything = (await http.get("/mentions")).json()
        cli = (await http.get("/mentions", params={"query": "cli"})).json()
        none = (await http.get("/mentions", params={"query": "zzz"})).json()

    assert [item["token"] for item in everything["mentions"]] == ["@src/cli.py", "@code-review"]
    assert everything["mentions"][0] == {
        "token": "@src/cli.py",
        "kind": "file",
        "name": "src/cli.py",
        "description": "4.2 KB",
    }
    assert [item["name"] for item in cli["mentions"]] == ["src/cli.py"]
    assert none == {"mentions": []}


async def test_the_limit_is_validated():
    async with serve(FakeClient()) as http:
        too_many = await http.get("/mentions", params={"limit": 1000})
        zero = await http.get("/mentions", params={"limit": 0})

    assert too_many.status_code == 422 and zero.status_code == 422


async def test_the_workspace_usage_ledger_is_the_usage_pages_data():
    async with serve(FakeClient()) as http:
        body = (await http.get("/usage/ledger")).json()

    assert body["total"]["input_tokens"] == 1800
    assert body["total"]["output_tokens"] == 180
    assert body["total"]["total_tokens"] == 1980
    assert body["total"]["cache_share"] == 700 / 1800
    assert body["sessions"][0]["id"] == "session-1" and body["sessions"][0]["entries"] == 4
    assert body["sessions"][0]["models"] == ["gpt-5"]
    assert body["models"][0]["model"] == "gpt-5"
    assert body["days"][0]["day"] == "2026-10-18"


async def test_session_stats_are_the_resume_panels_columns():
    async with serve(FakeClient()) as http:
        current = (await http.get("/sessions/current/stats")).json()
        named = (await http.get("/sessions/stats", params={"ids": "session-1,session-2"})).json()

    assert current["id"] == "session-1"
    assert (current["entries"], current["requests"]) == (4, 2)
    assert (current["input_tokens"], current["output_tokens"], current["cache_read_tokens"]) == (1300, 130, 600)
    assert current["total_tokens"] == 1430
    assert current["cache_share"] == 600 / 1300
    assert [item["id"] for item in named["stats"]] == ["session-1", "session-2"]


async def test_naming_no_sessions_asks_for_no_stats():
    async with serve(FakeClient()) as http:
        body = (await http.get("/sessions/stats", params={"ids": ""})).json()

    assert body == {"stats": []}


async def test_self_compaction_is_read_and_its_choice_is_saved():
    client = FakeClient()
    async with serve(client) as http:
        before = (await http.get("/sessions/current/self-compaction")).json()
        on = (await http.put("/sessions/current/self-compaction", json={"choice": True})).json()
        back = (await http.put("/sessions/current/self-compaction", json={"choice": None})).json()

    assert before == {"choice": None, "effective": False}
    assert on == {"choice": True, "effective": True}
    assert client.self_choice is None and back == {"choice": None, "effective": False}


async def test_a_choice_that_is_not_a_boolean_or_null_is_refused():
    async with serve(FakeClient()) as http:
        response = await http.put("/sessions/current/self-compaction", json={"choice": "yes"})

    assert response.status_code == 422 and response.json()["error"] == "invalid"


async def test_doctor_reports_every_model_and_takes_the_timeout():
    client = FakeClient()
    async with serve(client) as http:
        body = (await http.post("/doctor", json={"timeout": 7})).json()
        assert client.doctor_timeout == 7
        default = await http.post("/doctor")

    assert default.status_code == 200
    assert body == {
        "checks": [
            {
                "model": "gpt-5",
                "model_id": "gpt-5",
                "ok": True,
                "seconds": 0.4,
                "detail": "ok",
                "input_tokens": 5,
                "output_tokens": 1,
            },
            {
                "model": "fast",
                "model_id": "gpt-5-mini",
                "ok": False,
                "seconds": 2.0,
                "detail": "401 Unauthorized",
                "input_tokens": None,
                "output_tokens": None,
            },
        ]
    }


async def test_a_timeout_outside_the_range_is_refused():
    async with serve(FakeClient()) as http:
        too_long = await http.post("/doctor", json={"timeout": 1000})
        zero = await http.post("/doctor", json={"timeout": 0})

    assert too_long.status_code == 422 and zero.status_code == 422
