"""The gateway's web application over a backend in memory: sign-in, origin checks, the endpoints, the event socket."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gateway_fakes import GATEWAY_ID, FakeBackend
from zettcode.gateway import app as app_module
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


def test_the_external_backend_reads_conversations_from_the_configured_store(tmp_path, monkeypatch):
    seen = {}

    class Backend:
        def __init__(self, directory, store):
            seen.update(directory=directory, store=store)

    monkeypatch.setattr(app_module, "ExternalBackend", Backend)
    settings = Settings(token=TOKEN, roots=(tmp_path,), directory=tmp_path / "gw", store=tmp_path / "sessions")

    create_app(settings, static=page(tmp_path))

    assert seen == {"directory": settings.directory, "store": settings.store}


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


# -- native clients: an origin of their own, and a token where a header cannot go --------------------------------


def native(tmp_path, **changes):
    """An app whose native clients are let in, with a backend that records what happened."""
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(token=TOKEN, roots=(work,), directory=tmp_path / "gw", **changes)
    backend = FakeBackend()
    backend.add_daemon("01d", str(work), name="d")
    return TestClient(create_app(settings, backend, static=page(tmp_path)), base_url="http://testserver")


def subprotocol(token: str) -> str:
    """The protocol a native client offers its token under, as ``clients/gateway`` writes it."""
    return "zettcode.token." + base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def test_a_native_client_origin_may_read_and_write_with_the_token_and_is_told_so(tmp_path):
    with native(tmp_path) as client:
        read = client.get("/api/threads", headers={"origin": "app://-", "authorization": f"Bearer {TOKEN}"})
        written = client.post(
            "/api/threads/01d/send",
            json={"text": "from the app"},
            headers={"origin": "app://-", "authorization": f"Bearer {TOKEN}"},
        )

    assert read.status_code == 200 and written.status_code == 200
    assert read.headers["access-control-allow-origin"] == "app://-"
    assert "origin" in read.headers["vary"].lower()


def test_a_native_client_without_the_token_is_refused_and_a_foreign_origin_is_refused(tmp_path):
    with native(tmp_path) as client:
        anonymous = client.get("/api/threads", headers={"origin": "app://-"})
        anonymous_write = client.post("/api/threads/01d/send", json={"text": "x"}, headers={"origin": "app://-"})
        foreign = client.post(
            "/api/threads/01d/send",
            json={"text": "x"},
            headers={"origin": "https://elsewhere.example", "authorization": f"Bearer {TOKEN}"},
        )

    assert anonymous.status_code == 401
    assert anonymous_write.status_code == 401, "an allowed origin is not a credential"
    assert foreign.status_code == 403
    assert "access-control-allow-origin" not in foreign.headers, "a foreign page is not told what it may read"


def test_a_preflight_is_answered_without_the_token_and_names_only_the_native_origin(tmp_path):
    with native(tmp_path) as client:
        asked = client.options(
            "/api/threads/01d/send",
            headers={
                "origin": "app://-",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization,content-type",
            },
        )
        foreign = client.options(
            "/api/threads/01d/send",
            headers={"origin": "https://elsewhere.example", "access-control-request-method": "POST"},
        )
        private = client.options(
            "/api/threads/01d/send",
            headers={
                "origin": "app://-",
                "access-control-request-method": "POST",
                "access-control-request-private-network": "true",
            },
        )

    assert asked.status_code == 200
    assert asked.headers["access-control-allow-origin"] == "app://-"
    assert "authorization" in asked.headers["access-control-allow-headers"].lower()
    assert private.headers["access-control-allow-private-network"] == "true"
    assert "access-control-allow-origin" not in foreign.headers


def test_an_origin_configured_for_another_client_is_let_in(tmp_path):
    with native(tmp_path, client_origins=("https://client.example",)) as client:
        answer = client.get(
            "/api/threads", headers={"origin": "https://client.example", "authorization": f"Bearer {TOKEN}"}
        )

    assert answer.status_code == 200
    assert answer.headers["access-control-allow-origin"] == "https://client.example"


def test_with_no_token_a_native_origin_is_not_let_in(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    settings = Settings(roots=(work,), directory=tmp_path / "gw", client_origins=("https://client.example",))
    with TestClient(create_app(settings, FakeBackend(), static=page(tmp_path)), base_url="http://localhost") as client:
        answer = client.post("/api/threads/01d/read", headers={"origin": "app://-"})
        asked = client.options(
            "/api/threads/01d/read",
            headers={"origin": "app://-", "access-control-request-method": "POST"},
        )

    assert answer.status_code == 403
    assert "access-control-allow-origin" not in asked.headers
    assert settings.allowed_origins == ()


def test_the_event_socket_takes_the_token_as_a_subprotocol_from_a_native_origin(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    with native(tmp_path) as client:
        with client.websocket_connect(
            "/api/events",
            subprotocols=["zettcode", subprotocol(TOKEN)],
            headers={"origin": "app://-"},
        ) as socket:
            assert socket.accepted_subprotocol == "zettcode"
            assert socket.receive_json()["type"] == "threads"
        with client.websocket_connect(
            "/api/events",
            subprotocols=["zettcode", subprotocol("wrong")],
            headers={"origin": "app://-"},
        ) as socket:
            assert socket.accepted_subprotocol == "zettcode"
            with pytest.raises(WebSocketDisconnect) as refused:
                socket.receive_json()

    assert refused.value.code == 4401


def test_the_event_socket_from_a_foreign_origin_still_needs_the_gateway_itself(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    with native(tmp_path) as client:
        with client.websocket_connect(
            "/api/events",
            subprotocols=["zettcode", subprotocol(TOKEN)],
            headers={"origin": "https://elsewhere.example"},
        ) as socket:
            with pytest.raises(WebSocketDisconnect) as refused:
                socket.receive_json()

    assert refused.value.code == 4401


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
    stopped = client.post("/api/daemons/01d/stop", json={})
    busy_delete = client.delete("/api/daemons/01d")

    assert made.status_code == 200 and made.json()["thread"]["name"] == "new"
    assert outside.status_code == 403 and full.status_code == 403
    assert stopped.json() == {"result": "stopped; its record was kept"} and backend.stopped == ["01d"]
    assert busy_delete.status_code == 200 and backend.deleted == ["01d"]
    assert client.delete("/api/daemons/01d").status_code == 404


def test_external_agent_endpoints_list_types_and_refuse_an_unknown_one(parts):
    client, _, _ = parts
    signed_in(client)

    agents = client.get("/api/agents").json()["agents"]
    assert all({"name", "title", "description", "avatar"} <= set(agent) for agent in agents)
    unknown = client.post("/api/agents", json={"kind": "missing"})
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "agent"
    assert client.delete("/api/agents/missing").status_code == 404


def test_a_group_can_be_joined_without_writing(parts):
    client, backend, _ = parts
    signed_in(client)
    backend.graph_data["groups"] = [{"name": "review", "created": 1.0, "members": [], "last": None}]

    joined = client.post("/api/groups/review/join", json={})

    assert joined.status_code == 200 and joined.json() == {"group": "review"}
    assert backend.joined == ["review"]
    assert client.post("/api/groups/missing/join", json={}).status_code == 404


def test_a_group_member_can_be_invited(parts):
    client, backend, _ = parts
    signed_in(client)
    backend.graph_data["groups"] = [{"name": "review", "created": 1.0, "members": [], "last": None}]

    invited = client.post("/api/groups/review/members", json={"member": "01d"})
    unknown = client.post("/api/groups/review/members", json={"member": "not-listed"})

    assert invited.status_code == 200 and invited.json() == {"group": "review", "member": "01d"}
    assert unknown.status_code == 404
    assert backend.invited == [("review", "01d")]


def test_the_person_can_leave_a_group_and_a_member_can_be_removed(parts):
    client, backend, _ = parts
    signed_in(client)
    mine = backend.gateway_id
    backend.graph_data["groups"] = [{"name": "review", "created": 1.0, "members": [mine, "01d"], "last": None}]

    left = client.post("/api/groups/review/leave", json={})
    removed = client.delete("/api/groups/review/members/01d")
    missing = client.post("/api/groups/nowhere/leave", json={})

    assert left.status_code == 200 and left.json() == {"group": "review", "member": mine}
    assert removed.status_code == 200 and removed.json() == {"group": "review", "member": "01d"}
    assert missing.status_code == 404
    assert backend.graph_data["groups"][0]["members"] == []
    assert backend.removed_members == [("review", mine), ("review", "01d")]


def test_a_group_can_be_created_with_the_person_in_it_and_deleted(parts):
    client, backend, _ = parts
    signed_in(client)
    backend.graph_data["groups"] = []
    mine = backend.gateway_id

    made = client.post("/api/groups", json={"name": " #Review ", "members": ["01d"]})
    again = client.post("/api/groups", json={"name": "review", "members": []})
    unknown = client.post("/api/groups", json={"name": "other", "members": ["not-listed"]})
    blank = client.post("/api/groups", json={"name": "  ", "members": []})
    bad = client.post("/api/groups", json={"name": "other", "members": "01d"})

    assert made.status_code == 200 and made.json() == {"group": "review", "members": [mine, "01d"]}
    assert backend.created_groups == [("review", [mine, "01d"])]
    assert again.status_code == 409
    assert unknown.status_code == 404
    assert blank.status_code == 400 and bad.status_code == 400

    gone = client.delete("/api/groups/%23Review")
    missing = client.delete("/api/groups/review")

    assert gone.status_code == 200 and gone.json() == {"group": "review"}
    assert missing.status_code == 404
    assert backend.deleted_groups == ["review"]


def test_the_folder_picker_and_the_configuration_answer(parts):
    client, _, work = parts
    signed_in(client)

    assert client.get("/api/dirs").json()["dirs"][0]["path"] == str(work.resolve())
    assert client.get("/api/dirs", params={"path": "/"}).status_code == 403
    config = client.get("/api/config").json()
    assert config["allow_full"] is False and config["models"][0]["default"] is True


def test_a_thread_profile_sets_a_name_and_picture(parts):
    client, _, _ = parts
    signed_in(client)

    updated = client.patch(
        "/api/threads/01d/profile", json={"name": "Build bot", "avatar": "data:image/png;base64,AA=="}
    )
    assert updated.status_code == 200
    thread = updated.json()["thread"]
    assert (thread["name"], thread["avatar"]) == ("Build bot", "data:image/png;base64,AA==")

    cleared = client.patch("/api/threads/01d/profile", json={"name": "", "avatar": ""})
    assert cleared.json()["thread"]["name"] == "d"
    assert cleared.json()["thread"]["avatar"] == ""


def test_a_thread_can_be_pinned_and_archived(parts):
    client, backend, work = parts
    signed_in(client)
    backend.add_daemon("02d", str(work), name="newer", started_at=5_000_000_000.0)

    # Newest first, until one is pinned (the patch also makes the gateway look at the new daemon).
    archived = client.patch("/api/threads/02d/profile", json={"archived": True})
    assert [thread["id"] for thread in client.get("/api/threads").json()["threads"]] == ["02d", "01d"]
    pinned = client.patch("/api/threads/01d/profile", json={"pinned": True})

    assert pinned.json()["thread"]["pinned"] is True and pinned.json()["thread"]["archived"] is False
    assert archived.json()["thread"]["archived"] is True
    assert [thread["id"] for thread in client.get("/api/threads").json()["threads"]] == ["01d", "02d"]
    assert client.patch("/api/threads/01d/profile", json={"pinned": "yes"}).status_code == 400

    undone = client.patch("/api/threads/01d/profile", json={"pinned": False})
    assert undone.json()["thread"]["pinned"] is False


def test_the_log_is_read(parts):
    client, backend, _ = parts
    signed_in(client)
    backend.logs["01d"] = "tool grep"

    assert client.get("/api/daemons/01d/log").json() == {"text": "tool grep"}


def test_the_event_socket_needs_a_sign_in_and_the_same_site_then_starts_with_everything(parts):
    from starlette.websockets import WebSocketDisconnect

    client, backend, _ = parts

    with client.websocket_connect("/api/events") as socket:
        with pytest.raises(WebSocketDisconnect) as refused:
            socket.receive_json()
    assert refused.value.code == 4401
    signed_in(client)
    with client.websocket_connect("/api/events", headers={"origin": "http://evil.example"}) as socket:
        with pytest.raises(WebSocketDisconnect) as foreign:
            socket.receive_json()
    assert foreign.value.code == 4401
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
    root = Path(__file__).resolve().parents[3]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    project = (root / "packages" / "zettcode-gateway" / "pyproject.toml").read_text(encoding="utf-8")

    assert "packages/zettcode-gateway/src/zettcode/gateway/static/" in ignored
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


def test_a_message_to_a_group_goes_through_its_own_route(parts):
    client, backend, _ = parts
    backend.graph_data = {
        "sessions": [],
        "groups": [{"name": "team", "members": [GATEWAY_ID, "peer"], "created_at": 0.0, "updated_at": 0.0}],
        "edges": [],
        "recent": [],
    }
    signed_in(client)

    answer = client.post("/api/groups/team/send", json={"text": "hello all"})

    assert answer.status_code == 200
    assert backend.group_sent == [("team", "hello all")]
    assert answer.json()["delivered"][0]["to"] == "peer"


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
    assert backend.timeline_asked == [(150.0, 350.0, 20_000)], "the count is capped"
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


def test_a_picture_is_sent_and_served_over_http_and_a_big_body_is_still_bounded(tmp_path):
    import base64

    work = tmp_path / "work"
    work.mkdir()
    backend = FakeBackend()
    backend.add_daemon("01d", str(work), name="d")
    backend.add_daemon("01p", str(work), name="p", model_name="deep", direct=True)
    settings = Settings(token=TOKEN, roots=(work,), directory=tmp_path / "gw")
    with TestClient(create_app(settings, backend, static=page(tmp_path)), base_url="http://testserver") as client:
        signed_in(client)
        png = b"\x89PNG\r\n\x1a\n" + b"\x01" * 40
        body = {
            "text": "what is this?",
            "images": [{"media_type": "image/png", "data": base64.b64encode(png).decode()}],
        }

        sent = client.post("/api/threads/01p/send", json=body)
        assert sent.status_code == 200 and sent.json()["direct"] is True
        assert backend.pictures_sent[-1][0].data == png

        item = next(i for i in client.get("/api/threads/01p").json()["items"] if i.get("images"))
        served = client.get(f"/api/threads/01p/pictures/{item['images'][0]['id']}")
        assert served.status_code == 200 and served.content == png and served.headers["content-type"] == "image/png"
        assert served.headers["x-content-type-options"] == "nosniff"
        assert "immutable" in served.headers["cache-control"]
        assert client.get("/api/threads/01p/pictures/nothing").status_code == 404

        forged = client.post("/api/threads/01p/send", json=body, headers={"origin": "https://elsewhere.example"})
        assert forged.status_code == 403
        huge = client.post(
            "/api/threads/01p/send", content=b"x" * (13 << 20), headers={"content-type": "application/json"}
        )
        assert huge.status_code == 413
        other = client.post("/api/daemons", content=b"x" * (300 << 10), headers={"content-type": "application/json"})
        assert other.status_code == 413, "only a send may be that large; every other body keeps its small limit"
        assert client.get("/api/threads/01p/pictures/x", headers={}).status_code in (404,)
