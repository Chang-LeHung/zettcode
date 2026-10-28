"""The gateway's web application over a backend in memory: sign-in, origin checks, the endpoints, the event socket."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gateway_fakes import GATEWAY_ID, FakeBackend
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
