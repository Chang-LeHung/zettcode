"""The gateway's web application over a backend in memory: sign-in, origin checks, the endpoints, the event socket."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gateway_fakes import GATEWAY_ID, FakeBackend
from zettcode.gateway import runfile
from zettcode.gateway.app import COOKIE, create_app
from zettcode.gateway.settings import Settings

TOKEN = "s3cret"


def page(tmp_path):
    """A folder with a page in it: the real one is built from clients/gateway and is not in a checkout."""
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "index.html").write_text("<!doctype html><title>page</title>", encoding="utf-8")
    (folder / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    return folder


@pytest.fixture
def parts(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    backend = FakeBackend()
    backend.add_daemon("01d", str(work), name="d")
    settings = Settings(token=TOKEN, roots=(work,), directory=tmp_path / "gw")
    with TestClient(create_app(settings, backend, static=page(tmp_path)), base_url="http://testserver") as client:
        yield client, backend, work


def signed_in(client: TestClient) -> TestClient:
    assert client.post("/api/login", json={"token": TOKEN}).status_code == 200
    return client


def test_a_serving_gateway_records_itself_for_stop_and_clears_the_record_when_it_leaves(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(token=TOKEN, roots=(work,), directory=tmp_path / "gw")

    with TestClient(create_app(settings, FakeBackend(), static=page(tmp_path)), base_url="http://testserver"):
        record = runfile.read(settings.directory)
        assert record is not None and record.pid == os.getpid()
        assert record.settings.port == settings.port and record.settings.token == TOKEN

    assert runfile.read(settings.directory) is None


def test_nothing_but_the_page_and_sign_in_answers_before_sign_in(parts):
    client, _, _ = parts

    assert client.get("/").status_code == 200
    assert client.get("/api/session").json() == {"authenticated": False, "open": False}
    for path in ("/api/threads", "/api/status", "/api/config", "/api/dirs", "/api/threads/01d"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/threads/01d/send", json={"text": "x"}).status_code == 401
    assert client.post("/api/daemons", json={}).status_code == 401


def test_a_wrong_token_is_refused_and_too_many_lock_sign_in_out(parts):
    client, _, _ = parts

    for _ in range(8):
        assert client.post("/api/login", json={"token": "nope"}).status_code == 401
    assert client.post("/api/login", json={"token": TOKEN}).status_code == 429


def test_the_cookie_is_not_readable_by_scripts_or_sent_across_sites_and_signing_out_ends_it(parts):
    client, _, _ = parts

    response = client.post("/api/login", json={"token": TOKEN})
    header = response.headers["set-cookie"].lower()
    assert COOKIE in header and "httponly" in header and "samesite=strict" in header
    assert client.get("/api/threads").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/threads").status_code == 401


def test_the_token_works_as_a_bearer_for_a_program(parts):
    client, _, _ = parts

    assert client.get("/api/threads", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert client.get("/api/threads", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_a_request_from_another_site_is_refused_even_when_signed_in(parts):
    client, backend, _ = parts
    signed_in(client)

    refused = client.post("/api/threads/01d/send", json={"text": "hi"}, headers={"origin": "http://evil.example"})
    allowed = client.post("/api/threads/01d/send", json={"text": "hi"}, headers={"origin": "http://testserver"})

    assert refused.status_code == 403 and allowed.status_code == 200
    assert len(backend.sent) == 1


def test_every_answer_carries_the_headers_that_keep_a_message_from_running(parts):
    client, _, _ = parts

    headers = client.get("/").headers

    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"


def test_threads_a_thread_and_sending_round_trip(parts):
    client, backend, _ = parts
    signed_in(client)

    listed = client.get("/api/threads").json()
    sent = client.post("/api/threads/01d/send", json={"text": "run it"}).json()
    opened = client.get("/api/threads/01d").json()

    assert [t["id"] for t in listed["threads"]] == ["01d"] and listed["status"]["gateway"]["id"] == GATEWAY_ID
    assert sent["disposition"] == "started" and sent["status"]["limits"]["used"] == 1
    assert opened["items"] == [{"kind": "out", "text": "run it"}]
    assert client.post("/api/threads/01d/read").json() == {"ok": True}


def test_a_refusal_has_one_shape_and_the_status_of_its_reason(parts):
    client, _, _ = parts
    signed_in(client)

    missing = client.get("/api/threads/01none")
    empty = client.post("/api/threads/01d/send", json={"text": " "})
    malformed = client.post("/api/threads/01d/send", json={"text": 5})
    not_json = client.post("/api/threads/01d/send", content=b"{", headers={"content-type": "application/json"})

    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    assert (empty.status_code, empty.json()["error"]["code"]) == (400, "empty")
    assert malformed.status_code == 400 and not_json.status_code == 400


def test_a_body_over_the_limit_is_refused(parts):
    client, _, _ = parts
    signed_in(client)

    response = client.post("/api/threads/01d/send", content=b'{"text":"' + b"x" * 300_000 + b'"}')

    assert response.status_code == 413


def test_a_daemon_is_started_listed_and_stopped_through_the_endpoints_inside_the_roots_only(parts):
    client, backend, work = parts
    signed_in(client)

    made = client.post("/api/daemons", json={"workspace": str(work), "name": "new"})
    outside = client.post("/api/daemons", json={"workspace": "/"})
    full = client.post("/api/daemons", json={"workspace": str(work), "permission": "full"})
    stopped = client.delete("/api/daemons/01d")

    assert made.status_code == 200 and made.json()["thread"]["name"] == "new"
    assert outside.status_code == 403 and full.status_code == 403
    assert stopped.json() == {"result": "stopped"} and backend.stopped == ["01d"]
    assert client.delete("/api/daemons/01d").status_code == 404


def test_the_folder_picker_and_the_configuration_answer(parts):
    client, _, work = parts
    signed_in(client)

    assert client.get("/api/dirs").json()["dirs"][0]["path"] == str(work.resolve())
    assert client.get("/api/dirs", params={"path": "/"}).status_code == 403
    config = client.get("/api/config").json()
    assert config["allow_full"] is False and config["models"][0]["default"] is True


def test_the_log_is_read(parts):
    client, backend, _ = parts
    signed_in(client)
    backend.logs["01d"] = "tool grep"

    assert client.get("/api/daemons/01d/log").json() == {"text": "tool grep"}


def test_the_event_socket_needs_a_sign_in_and_the_same_site_then_starts_with_everything(parts):
    from starlette.websockets import WebSocketDisconnect

    client, backend, _ = parts

    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect("/api/events"):
        pass
    assert refused.value.code == 4401
    signed_in(client)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/events", headers={"origin": "http://evil.example"}),
    ):
        pass
    with client.websocket_connect("/api/events") as socket:
        first = socket.receive_json()
        assert first["type"] == "threads" and first["threads"][0]["id"] == "01d"


def test_with_no_token_a_browser_on_this_machine_is_in_and_one_reaching_it_by_another_name_is_not(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(roots=(work,), directory=tmp_path / "gw")
    with TestClient(
        create_app(settings, FakeBackend(), static=page(tmp_path)), base_url="http://localhost:8765"
    ) as client:
        assert client.get("/api/session").json() == {"authenticated": True, "open": True}
        assert client.get("/api/threads").status_code == 200
        rebound = client.get("/api/threads", headers={"host": "evil.example:8765"})
        assert rebound.status_code == 401
        assert client.get("/api/threads", headers={"host": "[::1]:8765"}).status_code == 200


def test_with_no_token_a_write_must_say_where_it_is_from_and_say_this_host(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(roots=(work,), directory=tmp_path / "gw")
    with TestClient(
        create_app(settings, FakeBackend(), static=page(tmp_path)), base_url="http://localhost:8765"
    ) as client:
        silent = client.post("/api/threads/01d/read")
        foreign = client.post("/api/threads/01d/read", headers={"origin": "http://evil.example"})
        ours = client.post("/api/threads/01d/read", headers={"origin": "http://localhost:8765"})

    assert (silent.status_code, foreign.status_code) == (403, 403) and ours.status_code != 403


def test_a_page_that_fell_behind_has_its_socket_closed_so_that_it_reconnects(parts):
    from starlette.websockets import WebSocketDisconnect

    client, _, _ = parts
    signed_in(client)
    with client.websocket_connect("/api/events") as socket:
        socket.receive_json()  # everything, as it connects
        gateway = client.app.state.gateway  # type: ignore[attr-defined]
        (queue,) = gateway._subscribers
        while not queue.full():
            queue.put_nowait({"type": "thread", "id": "x"})
        gateway._publish({"type": "thread", "id": "y"})

        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(400):
                socket.receive_json()
    assert closed.value.code == 1013


def test_a_checkout_that_has_not_built_the_page_still_starts_and_says_so_instead_of_answering_404(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(roots=(work,), directory=tmp_path / "gw")
    with TestClient(
        create_app(settings, FakeBackend(), static=tmp_path / "nothing"), base_url="http://localhost"
    ) as client:
        index = client.get("/")
        api = client.get("/api/session")

    assert index.status_code == 503 and "make gateway-ui" in index.text
    assert api.status_code == 200, "the API does not need the page"


def test_the_page_is_built_into_the_wheel_and_not_kept_in_git():
    root = Path(__file__).resolve().parents[2]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    project = (root / "zettcode" / "pyproject.toml").read_text(encoding="utf-8")

    assert "zettcode/src/zettcode/gateway/static/" in ignored
    assert 'artifacts = ["src/zettcode/gateway/static/**"]' in project, "hatchling skips what git ignores unless named"


# -- the graph: who talks to whom, live and as a replay of the past ----------------------------------------------


def a_message(number: int, at: float) -> dict:
    return {
        "id": number,
        "ts": at,
        "from": {"session_id": "a", "handle": "alpha", "title": ""},
        "to": {"kind": "session", "session_id": "b", "handle": "bravo", "title": ""},
        "recipients": ["b"],
        "text": f"m{number}",
        "via": "agent",
        "hops": 1,
        "mode": "steer",
        "status": "delivered",
        "disposition": "started",
    }


def test_the_graph_needs_a_sign_in_and_is_what_the_broker_reported(parts):
    client, backend, _ = parts
    backend.graph_data = {"sessions": [], "groups": [], "edges": [], "recent": [a_message(1, 10.0)]}
    assert client.get("/api/graph").status_code == 401

    body = signed_in(client).get("/api/graph").json()

    assert body["recent"][0]["text"] == "m1"


def test_the_timeline_passes_a_window_to_the_broker_and_never_sends_anything(parts):
    client, backend, _ = parts
    backend.graph_data = {
        "sessions": [],
        "groups": [],
        "edges": [],
        "recent": [a_message(n, n * 100.0) for n in (1, 2, 3)],
    }
    signed_in(client)

    body = client.get("/api/graph/timeline?since=150&until=350&limit=99999").json()

    assert [m["text"] for m in body["messages"]] == ["m2", "m3"]
    assert backend.timeline_asked == [(150.0, 350.0, 2000)], "the count is capped"
    assert backend.sent == []
    assert client.get("/api/graph/timeline?since=9&until=1").status_code == 400
    assert client.get("/api/graph/timeline?since=abc").status_code == 400


def test_a_message_the_broker_saw_reaches_the_page_as_traffic_and_a_change_as_graph(parts):
    client, backend, _ = parts
    signed_in(client)
    with client.websocket_connect("/api/events") as socket:
        socket.receive_json()  # the threads
        backend.traffic({"kind": "message", "message": a_message(7, 1.0)})
        backend.traffic({"kind": "graph"})
        backend.traffic({"kind": "something-else"})

        seen = []
        while len(seen) < 2:
            event = socket.receive_json()
            if event["type"] in ("traffic", "graph"):
                seen.append(event)

    assert seen[0]["type"] == "traffic" and seen[0]["message"]["id"] == 7
    assert seen[1] == {"type": "graph"}


def test_older_returns_the_messages_before_an_id_and_refuses_a_bad_one(parts):
    client, backend, _ = parts
    backend.graph_data = {
        "sessions": [],
        "groups": [],
        "edges": [],
        "recent": [a_message(n, n * 10.0) for n in (1, 2, 3, 4)],
    }
    signed_in(client)

    body = client.get("/api/graph/older?before=4&limit=2").json()

    assert [m["id"] for m in body["messages"]] == [2, 3] and body["more"] is True
    assert client.get("/api/graph/older").status_code == 400
    assert client.get("/api/graph/older?before=abc").status_code == 400


def test_a_model_is_added_changed_and_removed_through_the_page(parts):
    client, backend, _ = parts
    signed_in(client)

    added = client.post(
        "/api/models",
        json={"model": "gpt-x", "token": " sk-1 ", "base_url": "", "multimodal": False, "context_window": 64000},
    )
    assert added.status_code == 200 and [item["name"] for item in added.json()["models"]][-1] == "gpt-x"
    assert backend.model_edits[-1] == ("add", {"model": "gpt-x", "token": "sk-1", "context_window": 64000})

    changed = client.patch("/api/models/gpt-x", json={"temperature": None, "token": "", "web_search": True})
    assert changed.status_code == 200
    assert backend.model_edits[-1] == ("update", "gpt-x", {"temperature": None, "web_search": True})

    gone = client.delete("/api/models/gpt-x")
    assert gone.status_code == 200 and "gpt-x" not in [item["name"] for item in gone.json()["models"]]


def test_a_model_the_file_cannot_hold_is_refused_in_the_files_words(parts):
    client, backend, _ = parts
    signed_in(client)

    assert client.post("/api/models", json={"token": "x"}).status_code == 400
    assert (
        client.post("/api/models", json={"model": "a", "colour": "red"}).json()["error"]["message"].startswith("colour")
    )
    assert client.post("/api/models", json={"model": "a", "context_window": "big"}).status_code == 400
    assert client.post("/api/models", json={"model": "a", "context_window": True}).status_code == 400
    assert client.patch("/api/models/fast", json={}).status_code == 400
    assert client.patch("/api/models/fast", json={"model": ""}).status_code == 400
    missing = client.patch("/api/models/ghost", json={"multimodal": True})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "invalid"
    only = client.delete("/api/models/fast")
    assert only.status_code == 200
    assert client.delete("/api/models/deep").json()["error"]["message"] == "The last model cannot be removed"
    assert client.post("/api/models", json={"model": "deep"}).status_code == 400, "a duplicate is the file's refusal"
    assert client.post("/api/models", json={"model": "other"}).status_code == 200
    assert all(edit[0] != "add" or edit[1].get("colour") is None for edit in backend.model_edits), "never written"


def test_no_response_carries_a_token_and_a_change_needs_the_same_site(parts):
    client, backend, _ = parts
    signed_in(client)

    assert "token" not in json.dumps(client.get("/api/config").json())
    forged = client.post("/api/models", json={"model": "z"}, headers={"origin": "https://elsewhere.example"})
    assert forged.status_code == 403
    assert client.post("/api/models", json={"model": "z"}).status_code == 200


def test_the_real_editor_writes_the_file_keeps_its_comments_and_reports_a_bad_entry(tmp_path, monkeypatch):
    from zettcode.gateway.backend import SdkBackend
    from zettcode.gateway.service import model_view

    config = tmp_path / "config.toml"
    config.write_text('# my models\n[[models]]\nmodel = "first"\ntoken = "k1"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    backend = SdkBackend.__new__(SdkBackend)

    listed = backend.add_model({"model": "second", "token": "k2", "temperature": 0.5})
    assert [item.name for item in listed] == ["first", "second"]
    assert "# my models" in config.read_text(encoding="utf-8")
    backend.update_model("second", {"temperature": None, "context_window": 32000})
    assert backend.models()[1].context_window == 32000 and backend.models()[1].temperature is None
    assert "k1" not in json.dumps([model_view(item, i) for i, item in enumerate(backend.models())])
    before = config.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        backend.add_model({"model": "bad", "anthropic": True, "responses_api": True})
    assert config.read_text(encoding="utf-8") == before, "a refused entry leaves the file as it was"
    assert [item.name for item in backend.remove_model("first")] == ["second"]
    with pytest.raises(ValueError):
        backend.remove_model("second")


def test_a_model_id_with_a_slash_is_addressed_encoded_or_not(parts):
    client, backend, _ = parts
    signed_in(client)

    assert client.post("/api/models", json={"model": "vendor/model"}).status_code == 200
    assert client.patch("/api/models/vendor%2Fmodel", json={"multimodal": True}).status_code == 200
    assert backend.model_edits[-1] == ("update", "vendor/model", {"multimodal": True})
    assert client.patch("/api/models/vendor/model", json={"multimodal": False}).status_code == 200
    assert client.delete("/api/models/vendor%2Fmodel").status_code == 200
    assert backend.model_edits[-1] == ("remove", "vendor/model")


def test_model_edits_run_one_at_a_time(parts):
    import asyncio
    import threading

    client, backend, _ = parts
    signed_in(client)
    inside = 0
    most = 0
    guard = threading.Lock()
    original = backend.update_model

    def slow(name, changes):
        nonlocal inside, most
        with guard:
            inside += 1
            most = max(most, inside)
        time.sleep(0.05)
        with guard:
            inside -= 1
        return original(name, changes)

    backend.update_model = slow  # type: ignore[method-assign]
    gateway = client.app.state.gateway  # type: ignore[attr-defined]

    async def both():
        await asyncio.gather(*(gateway.change_model("fast", {"multimodal": True}) for _ in range(4)))

    asyncio.run(both())
    assert most == 1
