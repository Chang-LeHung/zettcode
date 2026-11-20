"""The capabilities around the conversation: `@` candidates, the usage ledger, session stats, self-compaction, doctor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from server_fakes import FakeClient
from zettcode.sdk.types import Usage
from zettcode.server.app import create_app
from zettcode.server.serialize import usage_out
from zettcode.server.settings import Settings


@asynccontextmanager
async def serve(client: FakeClient) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=lambda: client)
    async with app.router.lifespan_context(app):
        app.state.runner._harnesses = client.harnesses  # the library the fake keeps, in place of the real one
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


def test_a_usage_carries_whether_its_cache_was_measured():
    """The HTTP face keeps the flag the terminal and the webview decide a dash by."""
    assert usage_out(Usage(input_tokens=10, cache_read_tokens=4)).cache_reported is True
    assert usage_out(Usage(input_tokens=10, cache_read_tokens=4, cache_reported=False)).cache_reported is False


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


@asynccontextmanager
async def serve_with_app(client: FakeClient | None, tmp_path: Path):
    settings = Settings(workspace=tmp_path, config_path=tmp_path / "config.toml")
    app = create_app(settings, client_factory=lambda: client)  # type: ignore[arg-type,return-value]
    async with app.router.lifespan_context(app):
        if client is not None:
            app.state.runner._harnesses = client.harnesses  # the library the fake keeps, in place of the real one
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, app


async def test_the_library_is_listed_with_its_manifests_and_one_harness_with_its_files():
    async with serve(FakeClient()) as http:
        listed = (await http.get("/harnesses")).json()["harnesses"]
        one = (await http.get("/harnesses/todos")).json()
        missing = await http.get("/harnesses/nothing")

    assert [item["name"] for item in listed] == ["todos"]
    assert listed[0]["state"] == "" and listed[0]["repositories"][0]["files"] == [], "the list is the cheap form"
    assert listed[0]["repositories"][0]["file_count"] == 2
    assert one["in_use"] is True and one["state"] == "ok" and one["commit"] == "a" * 40
    assert "MANIFEST" in one["repositories"][0]["files"]
    assert one["repositories"][0]["tools"] == ["list_todos"] and one["repositories"][0]["file_count"] == 2
    assert missing.status_code == 400 and missing.json()["error"] == "invalid"


async def test_a_preview_carries_the_files_and_where_each_link_points():
    async with serve(FakeClient()) as http:
        preview = (await http.post("/harnesses/preview", json={"source": "acme/fresh", "name": "fresh"})).json()

    assert preview["action"] == "add" and preview["caution"] and preview["files"] == ["__init__.py"]
    assert preview["links"] == {"key": "/etc/hosts"}


async def test_what_the_library_refuses_is_a_400_with_its_words_and_the_commit_and_digest_go_back_as_sent():
    client = FakeClient()
    client.harnesses.refuse = "What was downloaded is not what was shown. Preview it again."
    async with serve(client) as http:
        stale = await http.post("/harnesses", json={"source": "acme/fresh", "commit": "b" * 40, "digest": "0" * 64})
        refused = await http.put("/harnesses/todos", json={"commit": "b" * 40, "digest": "0" * 64})

    assert stale.status_code == 400 and "not what was shown" in stale.json()["message"]
    assert refused.status_code == 400
    assert client.harnesses.calls == [
        ("add", ("acme/fresh", "b" * 40, "0" * 64, None)),
        ("update", ("todos", "b" * 40, "0" * 64, False)),
    ]


async def test_an_update_is_previewed_with_its_changes_then_kept_and_a_harness_can_be_forked_and_removed():
    client = FakeClient()
    async with serve(client) as http:
        preview = (await http.post("/harnesses/todos/preview", json={"force": True})).json()
        updated = await http.put(
            "/harnesses/todos", json={"commit": preview["commit"], "digest": preview["digest"], "force": True}
        )
        forked = await http.post("/harnesses/todos/fork", json={"name": "mine"})
        left = await http.delete("/harnesses/todos")

    assert preview["action"] == "update" and preview["changes"] == ["version: 1.0.0 -> 2.0.0"]
    assert updated.status_code == 200 and forked.status_code == 201 and forked.json()["origin"] == "fork of todos"
    assert [item["name"] for item in left.json()["harnesses"]] == ["mine"]
    assert [call[0] for call in client.harnesses.calls] == ["preview_update", "update", "fork", "remove"]
    assert client.harnesses.calls[1][1] == ("todos", "b" * 40, "c" * 64, True)


async def test_a_request_with_a_field_the_endpoint_does_not_take_is_refused_not_ignored():
    async with serve(FakeClient()) as http:
        preview = await http.post("/harnesses/todos/preview", json={"source": "acme/x"})
        add = await http.post(
            "/harnesses", json={"source": "acme/x", "commit": "b" * 40, "digest": "c" * 64, "force": True}
        )
        update = await http.put("/harnesses/todos", json={"commit": "b" * 40, "digest": "c" * 64, "name": "x"})
        fork = await http.post("/harnesses/todos/fork", json={"name": "y", "force": True})

    assert [response.status_code for response in (preview, add, update, fork)] == [422, 422, 422, 422]


async def test_a_harness_is_not_replaced_or_removed_while_a_run_holds_the_conversation(tmp_path: Path):
    client = FakeClient()
    async with serve_with_app(client, tmp_path) as (http, app):
        await app.state.runner.slot.lock.acquire()
        try:
            update = await http.put("/harnesses/todos", json={"commit": "b" * 40, "digest": "c" * 64})
            removed = await http.delete("/harnesses/todos")
            listed = await http.get("/harnesses")
        finally:
            app.state.runner.slot.lock.release()

    assert update.status_code == 409 and update.json()["error"] == "busy"
    assert removed.status_code == 409 and listed.status_code == 200
    assert client.harnesses.calls == [], "nothing was changed"


async def test_the_library_answers_before_a_model_is_configured(tmp_path: Path, monkeypatch):
    import zettcode.config as config_module
    from zettcode.config import ModelConfig, ZettCodeConfig

    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "config.toml"))
    (tmp_path / "work").mkdir()
    configured = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    monkeypatch.setattr(config_module, "load_config", lambda *a, **k: configured)
    async with serve_with_app(None, tmp_path) as (http, app):
        response = await http.get("/harnesses")
        missing = await http.get("/harnesses/none")

    assert app.state.runner.maybe_client is None
    assert response.status_code == 200 and response.json() == {"harnesses": []}
    assert missing.status_code == 400 and missing.json()["error"] == "invalid", "not 409 no_model"


def test_the_wire_types_say_every_field_the_sdk_returns():
    """A field added to the SDK's value is added to the endpoint's answer, or this says which one was left out."""
    from zettcode.engine.harness_library import EntryInfo, RepositoryInfo
    from zettcode.sdk.types import HarnessEntry, HarnessPreview, HarnessRepository
    from zettcode.server.schemas import HarnessOut, HarnessPreviewOut, HarnessRepositoryOut

    assert set(HarnessPreviewOut.model_fields) == set(HarnessPreview.__dataclass_fields__)
    assert set(HarnessOut.model_fields) == set(HarnessEntry.__dataclass_fields__) == set(EntryInfo.__dataclass_fields__)
    assert set(HarnessRepositoryOut.model_fields) == set(HarnessRepository.__dataclass_fields__)
    assert set(HarnessRepository.__dataclass_fields__) == set(RepositoryInfo.__dataclass_fields__)


async def test_a_harness_is_not_replaced_or_removed_while_a_conversation_running_aside_holds_it(tmp_path: Path):
    from zettcode.server.runner import Slot

    client = FakeClient()
    async with serve_with_app(client, tmp_path) as (http, app):
        aside = Slot(FakeClient())
        app.state.runner._aside.append(aside)
        await aside.lock.acquire()
        try:
            update = await http.put("/harnesses/todos", json={"commit": "b" * 40, "digest": "c" * 64})
            removed = await http.delete("/harnesses/todos")
        finally:
            aside.lock.release()

    assert update.status_code == 409 and removed.status_code == 409
    assert client.harnesses.calls == []


def test_the_state_a_harness_can_have_is_the_set_the_engine_answers_with():
    from typing import get_args

    from zettcode.engine.harness_library import UPDATE_STATES
    from zettcode.server.schemas import HarnessOut

    allowed = set(get_args(HarnessOut.model_fields["state"].annotation))

    assert allowed == {"", *UPDATE_STATES}, "a new state is a new word in the schema and in types.ts"


async def test_the_servers_library_is_one_for_all_conversations_and_reads_use_from_the_file_it_was_given(
    tmp_path: Path, monkeypatch
):
    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.server.runner import Runner

    (tmp_path / "work").mkdir()
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    folder = tmp_path / "harness" / "library" / "todos" / "todos"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (folder / "MANIFEST").write_text(
        'name = "todos"\nversion = "1.0.0"\ndescription = "d"\ntools = ["t"]\n', encoding="utf-8"
    )
    default_file, given = tmp_path / "default.toml", tmp_path / "given.toml"
    default_file.write_text('[harness]\nuse = "other"\n', encoding="utf-8")
    given.write_text('[harness]\nuse = "todos"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(default_file))

    class Stub(FakeClient):
        pass

    stub = Stub()
    stub.config = config  # type: ignore[attr-defined]
    runner = Runner(Settings(workspace=tmp_path / "work", config_path=given), factory=lambda: stub)
    await runner.start()
    try:
        library = runner.harnesses
        entry = await library.entry("todos")
        listed = await library.entries()
        assert runner.harnesses is library, "one library for the process"
        assert entry.in_use is True and [item.in_use for item in listed] == [True]
        given.write_text('[harness]\nuse = ""\n', encoding="utf-8")
        assert (await library.entry("todos")).in_use is False, "the file the server was given decides"
    finally:
        await runner.close()
