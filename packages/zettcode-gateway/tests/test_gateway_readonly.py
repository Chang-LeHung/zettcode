"""A read-only token and the audit log: what the second sign-in may do, and what the log records and never records."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gateway_fakes import FakeBackend
from zettcode.gateway import runfile
from zettcode.gateway.app import Auth, create_app
from zettcode.gateway.audit import MAX_BYTES, Audit
from zettcode.gateway.cli import settings_from
from zettcode.gateway.settings import Settings

TOKEN = "s3cret"
READ = "l00k-only"


def page(tmp_path: Path) -> Path:
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
    settings = Settings(token=TOKEN, read_token=READ, roots=(work,), directory=tmp_path / "gw")
    with TestClient(create_app(settings, backend, static=page(tmp_path)), base_url="http://testserver") as client:
        yield client, settings


def lines(settings: Settings) -> list[dict]:
    return [json.loads(line) for line in settings.audit_path.read_text(encoding="utf-8").splitlines()]


def sign_in(client: TestClient, token: str) -> TestClient:
    response = client.post("/api/login", json={"token": token})
    assert response.status_code == 200, response.text
    return client


# -- settings -------------------------------------------------------------------------------------


def test_settings_refuse_a_read_token_that_means_nothing_or_would_be_the_write_token(tmp_path):
    with pytest.raises(ValueError, match="needs a token"):
        Settings(token="", read_token=READ, directory=tmp_path)
    with pytest.raises(ValueError, match="differ"):
        Settings(token=TOKEN, read_token=TOKEN, directory=tmp_path)
    with pytest.raises(ValueError, match="blank"):
        Settings(token=TOKEN, read_token="   ", directory=tmp_path)
    assert Settings(token=TOKEN, read_token=READ, directory=tmp_path).read_token == READ


def test_the_command_line_takes_the_read_token_from_the_environment_and_refuses_the_same_mistakes(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ZETTCODE_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("ZETTCODE_GATEWAY_READ_TOKEN", READ)
    assert settings_from(["--directory", str(tmp_path)]).read_token == READ
    monkeypatch.setenv("ZETTCODE_GATEWAY_READ_TOKEN", TOKEN)
    with pytest.raises(SystemExit, match="differ"):
        settings_from(["--directory", str(tmp_path)])
    monkeypatch.delenv("ZETTCODE_GATEWAY_TOKEN")
    monkeypatch.setenv("ZETTCODE_GATEWAY_READ_TOKEN", READ)
    with pytest.raises(SystemExit, match="needs a token"):
        settings_from(["--directory", str(tmp_path)])


def test_a_record_written_before_the_read_token_existed_reads_as_no_read_token(tmp_path):
    settings = Settings(token=TOKEN, directory=tmp_path)
    runfile.write(settings)
    path = runfile.path(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("read_token")
    path.write_text(json.dumps(record), encoding="utf-8")

    found = runfile.read(tmp_path)

    assert found is not None and found.settings.read_token == ""


def test_a_record_with_a_read_token_that_is_not_text_or_not_allowed_is_no_record(tmp_path):
    runfile.write(Settings(token=TOKEN, read_token=READ, directory=tmp_path))
    path = runfile.path(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    for bad in (5, TOKEN):
        path.write_text(json.dumps({**record, "read_token": bad}), encoding="utf-8")
        assert runfile.read(tmp_path) is None
    path.write_text(json.dumps({**record, "token": "", "read_token": READ}), encoding="utf-8")
    assert runfile.read(tmp_path) is None


# -- the roles ------------------------------------------------------------------------------------


def test_the_tokens_sign_in_as_their_own_role_and_a_cookie_keeps_it(parts):
    client, _ = parts
    assert client.get("/api/session").json()["role"] is None
    assert sign_in(client, READ).get("/api/session").json()["role"] == "read"
    assert sign_in(client, TOKEN).get("/api/session").json()["role"] == "write"


def test_a_read_only_sign_in_reads_everything_but_changes_nothing(parts):
    client, _ = parts
    sign_in(client, READ)

    assert client.get("/api/threads").status_code == 200
    assert client.get("/api/graph").status_code == 200
    refused = client.post("/api/daemons", json={"name": "x", "directory": "."})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "read_only"
    for method, path in (
        ("POST", "/api/threads/01d/send"),
        ("PATCH", "/api/threads/01d/profile"),
        ("POST", "/api/groups"),
        ("DELETE", "/api/groups/g"),
        ("POST", "/api/models"),
        ("POST", "/api/agents"),
        ("POST", "/api/daemons/01d/stop"),
        ("DELETE", "/api/daemons/01d"),
    ):
        response = client.request(method, path, json={})
        assert response.status_code == 403, (method, path)
        assert response.json()["error"]["code"] == "read_only"


def test_a_reader_may_mark_a_thread_seen_and_sign_out_but_not_list_directories(parts):
    client, _ = parts
    sign_in(client, READ)

    assert client.post("/api/threads/01d/read").status_code == 200
    assert client.get("/api/dirs").status_code == 403
    assert client.post("/api/logout").status_code == 200


def test_the_write_token_still_does_everything_and_a_read_bearer_cannot_write(parts):
    client, _ = parts
    assert client.get("/api/threads", headers={"authorization": f"Bearer {READ}"}).status_code == 200
    refused = client.post("/api/groups", json={"name": "g"}, headers={"authorization": f"Bearer {READ}"})
    assert refused.status_code == 403
    assert client.get("/api/dirs", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_the_event_socket_is_open_to_a_reader_and_closed_to_a_stranger(parts):
    from starlette.websockets import WebSocketDisconnect

    client, settings = parts
    with client.websocket_connect("/api/events", headers={"authorization": f"Bearer {READ}"}):
        pass
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/api/events") as socket:
            socket.receive_text()
    assert refused.value.code == 4401
    kinds = [(e["event"], e.get("role")) for e in lines(settings)]
    assert ("socket", "read") in kinds and ("socket.refused", None) in kinds


def test_with_no_read_token_a_wrong_token_is_still_wrong(tmp_path):
    auth = Auth(TOKEN, read_token="")
    assert auth.token_role("") is None and auth.token_role(READ) is None and auth.token_role(TOKEN) == "write"
    assert Auth(TOKEN, read_token=TOKEN).read_token == ""


# -- the audit log --------------------------------------------------------------------------------


def test_sign_ins_and_changes_are_logged_by_role_and_a_reader_who_tried_to_write_is_found(parts):
    client, settings = parts
    client.post("/api/login", json={"token": "wrong"})
    sign_in(client, READ)
    client.post("/api/groups", json={"name": "g"})
    client.get("/api/threads")
    sign_in(client, TOKEN)
    client.post("/api/threads/01d/read")

    events = lines(settings)
    kinds = [(e["event"], e.get("role"), e.get("path")) for e in events]
    assert ("login.failed", None, None) in kinds
    assert ("login", "read", None) in kinds and ("login", "write", None) in kinds
    assert ("request", "read", "/api/groups") in kinds
    refused = next(e for e in events if e.get("path") == "/api/groups")
    assert refused["status"] == 403
    assert ("request", "write", "/api/threads/01d/read") in kinds
    # A read is not a change, and the page polls: not every GET is a line.
    assert not any(e.get("path") == "/api/threads" for e in events)


def test_the_log_never_holds_a_token_a_cookie_or_what_was_said(parts):
    client, settings = parts
    sign_in(client, TOKEN)
    client.post("/api/threads/01d/send", json={"text": "the launch code is 12345"})

    raw = settings.audit_path.read_text(encoding="utf-8")

    assert TOKEN not in raw and READ not in raw and "12345" not in raw and "launch" not in raw
    assert stat.S_IMODE(os.stat(settings.audit_path).st_mode) == 0o600


def test_the_log_is_rotated_when_it_grows_past_its_bound_and_a_failure_does_not_stop_writing(tmp_path, monkeypatch):
    audit = Audit(tmp_path / "audit.jsonl")
    audit.path.write_text("x" * (MAX_BYTES + 1), encoding="utf-8")
    audit.record("login", role="write")
    assert (tmp_path / "audit.jsonl.1").exists()
    assert len(audit.tail()) == 1

    broken = Audit(tmp_path / "missing" / "audit.jsonl")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    broken.record("login")  # must not raise
    broken.record("login")
