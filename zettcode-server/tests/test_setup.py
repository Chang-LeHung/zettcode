"""A server on a fresh machine: it starts with no model, and the editor sets one up over HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from fakes import FakeClient, FakeRun
from zettcode_server.app import create_app
from zettcode_server.settings import Settings


def settings_for(tmp_path: Path) -> Settings:
    return Settings(workspace=tmp_path, config_path=tmp_path / "config.toml")


@asynccontextmanager
async def serve(tmp_path: Path, factory: Callable[[], object] | None = None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for(tmp_path), client_factory=factory or (lambda: None))  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


def write_config(tmp_path: Path, *models: str) -> Path:
    path = tmp_path / "config.toml"
    blocks = "\n\n".join(f'[[models]]\nmodel = "{name}"\ntoken = "t-{name}"' for name in models)
    path.write_text(blocks + "\n", encoding="utf-8")
    return path


async def test_a_fresh_machine_starts_and_says_it_has_no_model(tmp_path: Path):
    async with serve(tmp_path) as http:
        health = (await http.get("/health")).json()
        models = (await http.get("/models")).json()

    assert health["status"] == "ok" and health["ready"] is False
    assert health["session"] is None and health["models"] == 0
    assert models == {"models": [], "current": None}


async def test_what_needs_a_model_says_so_with_a_status_a_client_can_branch_on(tmp_path: Path):
    async with serve(tmp_path) as http:
        prompt = await http.post("/prompts", json={"text": "hello"})
        settings = await http.patch("/settings", json={"effort": "low"})
        sessions = await http.get("/sessions")

    for response in (prompt, settings, sessions):
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "no_model"
        assert "POST /models" in response.json()["message"]


async def test_the_first_model_is_written_to_the_config_file(tmp_path: Path):
    async with serve(tmp_path) as http:
        response = await http.post("/models", json={"model": "gpt-5", "token": "sk-1", "display_model": "Fast"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["current"] is None, "the fake factory still gives no client"
    assert body["models"][0]["name"] == "Fast" and body["models"][0]["active"] is False
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-5"' in text and 'token = "sk-1"' in text


async def test_adding_the_first_model_makes_the_server_ready(tmp_path: Path):
    clients = iter([None, FakeClient()])

    async with serve(tmp_path, factory=lambda: next(clients)) as http:
        before = (await http.get("/health")).json()
        added = await http.post("/models", json={"model": "gpt-5", "token": "sk-1"})
        after = (await http.get("/health")).json()

    assert before["ready"] is False
    assert added.status_code == 201 and added.json()["current"] == "gpt-5"
    assert after["ready"] is True and after["session"] == "session-1" and after["models"] == 2


async def test_a_model_is_changed_and_its_token_kept_unless_a_new_one_is_given(tmp_path: Path):
    path = write_config(tmp_path, "a")
    async with serve(tmp_path) as http:
        response = await http.patch("/models/a", json={"context_window": 200000, "multimodal": True})
        empty = await http.patch("/models/a", json={})

    assert response.status_code == 200
    assert response.json()["models"][0]["context_window"] == 200_000
    text = path.read_text(encoding="utf-8")
    assert 'token = "t-a"' in text and "context_window = 200000" in text
    assert empty.status_code == 400 and "at least one field" in empty.json()["message"]


async def test_chat_and_temperature_are_taken_and_a_null_removes_a_key(tmp_path: Path):
    path = write_config(tmp_path, "a")
    async with serve(tmp_path) as http:
        added = await http.post(
            "/models",
            json={"model": "local", "chat": True, "temperature": 0.3, "base_url": "http://localhost:11434/v1"},
        )
        too_hot = await http.post("/models", json={"model": "x", "temperature": 3})
        cleared = await http.patch("/models/local", json={"temperature": None, "chat": None, "anthropic": True})
        empty = await http.patch("/models/local", json={"token": None})

    assert added.status_code == 201
    assert too_hot.status_code == 422 and "temperature" in too_hot.json()["message"]
    text = path.read_text(encoding="utf-8")
    assert cleared.status_code == 200
    local = text.split('model = "local"')[1]
    assert "temperature" not in local and "chat" not in local and "anthropic = true" in local
    assert empty.status_code == 400, "a null token or model id is not a change"


async def test_a_model_that_is_not_configured_is_a_400_with_the_ones_that_are(tmp_path: Path):
    write_config(tmp_path, "a")
    async with serve(tmp_path) as http:
        response = await http.patch("/models/nope", json={"multimodal": True})

    assert response.status_code == 400
    assert "No model called 'nope'" in response.json()["message"] and "a" in response.json()["message"]


async def test_the_last_model_cannot_be_removed_and_the_others_can(tmp_path: Path):
    write_config(tmp_path, "a", "b")
    async with serve(tmp_path) as http:
        removed = await http.delete("/models/a")
        last = await http.delete("/models/b")

    assert removed.status_code == 200
    assert [model["model"] for model in removed.json()["models"]] == ["b"]
    assert last.status_code == 400 and "only model" in last.json()["message"]


async def test_a_body_with_an_unknown_key_is_refused_rather_than_ignored(tmp_path: Path):
    async with serve(tmp_path) as http:
        response = await http.post("/models", json={"model": "m", "token": "t", "tokn": "typo"})

    assert response.status_code == 422
    assert "tokn" in response.json()["message"]


async def test_editing_models_while_a_run_is_going_is_refused(tmp_path: Path):
    import asyncio

    hold = asyncio.Event()
    client = FakeClient(runs=[FakeRun([], hold=hold)])

    async with serve(tmp_path, factory=lambda: client) as http:
        write_config(tmp_path, "a")
        task = asyncio.ensure_future(http.post("/prompts", json={"text": "long"}))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if client.asked:
                break
        refused = await http.post("/models", json={"model": "b", "token": "t"})
        await http.post("/runs/cancel")
        await task

    assert refused.status_code == 409 and refused.json()["error"] == "busy"


async def test_a_config_file_that_does_not_parse_is_reported_not_fatal(tmp_path: Path):
    (tmp_path / "config.toml").write_text("[[models]\nmodel = ", encoding="utf-8")

    async with serve(tmp_path) as http:
        listed = await http.get("/models")
        added = await http.post("/models", json={"model": "m", "token": "t"})

    assert listed.status_code == 400 and "Invalid config" in listed.json()["message"]
    assert added.status_code == 400


@pytest.mark.parametrize("body", [{"model": ""}, {"token": "t"}, {"model": "m", "compact_percent": 0}])
async def test_a_model_body_is_validated(body):
    async with serve(Path.cwd()) as http:
        response = await http.post("/models", json=body)

    assert response.status_code == 422
