"""The JSON API, driven through the application without a model or a provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from fakes import FakeClient
from zettcode_server.app import create_app
from zettcode_server.settings import Settings


@asynccontextmanager
async def serve(client: FakeClient, *, token: str | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """Run the application's lifespan and hand back a client that speaks to it in-process."""
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test"), token=token), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


async def test_health_says_which_session_and_workspace_it_serves_and_that_nothing_runs():
    async with serve(FakeClient()) as http:
        response = await http.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["busy"] is False
    assert body["session"] == "session-1" and body["workspace"] == "/tmp/zettcode-server-test"
    assert body["version"]


async def test_a_configured_token_is_required_everywhere_but_on_health():
    async with serve(FakeClient(), token="s3cret") as http:
        assert (await http.get("/health")).status_code == 200

        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic s3cret"}):
            refused = await http.get("/models", headers=headers)
            assert refused.status_code == 401, headers
            assert refused.json()["error"] == "unauthorized"
            assert refused.headers["www-authenticate"] == "Bearer"

        accepted = await http.get("/models", headers={"Authorization": "Bearer s3cret"})
        assert accepted.status_code == 200

        lower = await http.get("/models", headers={"authorization": "bearer s3cret"})
        assert lower.status_code == 200, "the scheme is case-insensitive"


async def test_without_a_configured_token_nothing_is_asked_for():
    async with serve(FakeClient()) as http:
        assert (await http.get("/models")).status_code == 200


async def test_the_models_endpoint_lists_them_and_marks_the_active_one():
    async with serve(FakeClient()) as http:
        body = (await http.get("/models")).json()

    assert [model["name"] for model in body["models"]] == ["gpt-5", "fast"]
    assert body["current"] == "gpt-5"
    assert body["models"][0]["active"] is True and body["models"][1]["active"] is False
    assert body["models"][0]["efforts"] == ["low", "medium", "high"]


async def test_settings_can_be_read_and_changed():
    async with serve(FakeClient()) as http:
        before = (await http.get("/settings")).json()
        assert before["model"]["name"] == "gpt-5" and before["effort"] == "medium"
        assert before["permission"] == "deny"
        assert set(before["permissions"]) == {"deny", "ask", "safe", "auto"}

        changed = await http.patch("/settings", json={"model": "fast", "effort": "low", "permission": "safe"})

    assert changed.status_code == 200
    body = changed.json()
    assert body["model"]["name"] == "fast" and body["effort"] == "low" and body["permission"] == "safe"
    assert body["model"]["active"] is True


async def test_a_setting_that_changes_nothing_is_a_client_error_and_so_is_an_unknown_value():
    async with serve(FakeClient()) as http:
        empty = await http.patch("/settings", json={})
        unknown = await http.patch("/settings", json={"model": "no-such-model"})
        wrong = await http.patch("/settings", json={"effort": "galaxy"})

    assert empty.status_code == 400 and empty.json()["error"] == "invalid"
    assert "at least one" in empty.json()["message"]
    assert unknown.status_code == 400 and "no-such-model" in unknown.json()["message"]
    assert wrong.status_code == 400 and "galaxy" in wrong.json()["message"]


async def test_the_settings_body_is_validated_with_the_field_that_was_wrong():
    async with serve(FakeClient()) as http:
        response = await http.patch("/settings", json={"permission": "whatever"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid" and "permission" in body["message"]


async def test_sessions_are_listed_most_recent_first_and_the_current_one_is_marked():
    async with serve(FakeClient()) as http:
        body = (await http.get("/sessions")).json()

    assert [item["id"] for item in body["sessions"]] == ["session-1", "session-2"]
    assert body["sessions"][0]["current"] is True and body["sessions"][1]["current"] is False
    assert body["sessions"][0]["title"] == "A conversation"


async def test_the_list_takes_a_limit_and_refuses_a_nonsense_one():
    async with serve(FakeClient()) as http:
        limited = await http.get("/sessions", params={"limit": 1})
        too_many = await http.get("/sessions", params={"limit": 10_000})

    assert [item["id"] for item in limited.json()["sessions"]] == ["session-1"]
    assert too_many.status_code == 422


async def test_a_new_session_answers_201_and_becomes_the_current_one():
    async with serve(FakeClient()) as http:
        created = await http.post("/sessions", json={"title": "Fresh"})
        current = await http.get("/sessions/current")

    assert created.status_code == 201
    assert created.json()["title"] == "Fresh" and created.json()["current"] is True
    assert current.json()["id"] == created.json()["id"]


async def test_a_new_session_needs_no_body():
    async with serve(FakeClient()) as http:
        created = await http.post("/sessions")

    assert created.status_code == 201 and created.json()["title"] is None


async def test_opening_a_stored_session_continues_it_and_an_unknown_one_is_a_404():
    async with serve(FakeClient()) as http:
        opened = await http.post("/sessions/session-2/open")
        missing = await http.post("/sessions/nope/open")

    assert opened.status_code == 200 and opened.json()["id"] == "session-2"
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found" and "nope" in missing.json()["message"]


async def test_the_current_session_can_be_read_renamed_forked_and_compacted():
    client = FakeClient()
    async with serve(client) as http:
        current = (await http.get("/sessions/current")).json()
        renamed = (await http.post("/sessions/current/rename", json={"title": "Renamed"})).json()
        forked = (await http.post("/sessions/current/fork")).json()
        compacted = (await http.post("/sessions/current/compact")).json()

    assert current["id"] == "session-1" and current["usage"]["input_tokens"] == 10
    assert current["locked"] is False
    assert renamed["id"] == "session-1" and renamed["title"] == "Renamed" and renamed["current"] is True
    assert forked["id"] == "session-fork"
    assert compacted == {"applied": False, "summary": "", "compressed": 0, "kept": 0}


async def test_a_rename_needs_a_name():
    async with serve(FakeClient()) as http:
        empty = await http.post("/sessions/current/rename", json={"title": ""})
        missing = await http.post("/sessions/current/rename", json={})

    assert empty.status_code == 422 and missing.status_code == 422


async def test_the_context_report_and_the_history_of_the_current_session():
    async with serve(FakeClient()) as http:
        context = (await http.get("/sessions/current/context")).json()
        history = (await http.get("/sessions/current/history")).json()

    assert context["window"] == 200_000 and context["shares"][0]["name"] == "System"
    assert history["messages"][0]["role"] == "user" and history["messages"][0]["text"] == "hello"


async def test_before_anything_was_measured_the_context_report_is_null_and_not_an_error():
    client = FakeClient()
    client.session.report = None
    async with serve(client) as http:
        response = await http.get("/sessions/current/context")

    assert response.status_code == 200 and response.json() is None


async def test_usage_reports_the_session_totals():
    async with serve(FakeClient()) as http:
        body = (await http.get("/usage")).json()

    assert body["input_tokens"] == 100 and body["output_tokens"] == 20 and body["requests"] == 2


async def test_an_unexpected_failure_is_a_500_in_the_same_shape(monkeypatch):
    client = FakeClient()

    async def explode(*args, **kwargs):
        raise RuntimeError("the store is on fire")

    client.sessions.list = explode  # type: ignore[method-assign]
    async with serve(client) as http:
        response = await http.get("/sessions")

    assert response.status_code == 500
    assert response.json() == {"error": "internal", "message": "the store is on fire"}


async def test_the_openapi_schema_lists_the_endpoints():
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=FakeClient)
    schema = app.openapi()

    assert {"/health", "/models", "/settings", "/sessions", "/prompts", "/runs/cancel"} <= set(schema["paths"])
    assert schema["info"]["title"] == "ZettCode server"


@pytest.mark.parametrize("path", ["/", "/openapi.json", "/docs"])
async def test_the_usual_fastapi_surface_is_there(path: str):
    async with serve(FakeClient()) as http:
        response = await http.get(path)

    assert response.status_code == 200
