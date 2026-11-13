"""The /metrics endpoint and the counters behind it: what is counted, what is never a label, and who may scrape."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gateway_fakes import FakeBackend
from zettcode.gateway.app import create_app
from zettcode.gateway.metrics import Metrics
from zettcode.gateway.settings import Settings

TOKEN = "s3cret"
READ = "l00k-only"


def page(tmp_path: Path) -> Path:
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (folder / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    return folder


@pytest.fixture
def client(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    backend = FakeBackend()
    backend.add_daemon("01d", str(work), name="d")
    settings = Settings(token=TOKEN, read_token=READ, roots=(work,), directory=tmp_path / "gw")
    with TestClient(create_app(settings, backend, static=page(tmp_path)), base_url="http://testserver") as c:
        yield c


def scrape(client: TestClient, token: str = TOKEN) -> str:
    answer = client.get("/metrics", headers={"authorization": f"Bearer {token}"})
    assert answer.status_code == 200, answer.text
    return answer.text


def test_the_endpoint_needs_a_sign_in_and_a_reader_may_scrape_it(client):
    assert client.get("/metrics").status_code == 401
    assert "zettcode_gateway_uptime_seconds" in scrape(client, READ)


def test_requests_logins_and_sockets_are_counted_by_what_the_code_named_not_what_the_client_sent(client):
    client.post("/api/login", json={"token": "wrong"})
    client.post("/api/login", json={"token": READ})
    client.get("/api/threads", headers={"authorization": f"Bearer {TOKEN}"})
    client.get("/api/threads/does-not-exist", headers={"authorization": f"Bearer {TOKEN}"})
    client.get("/api/never-a-route-" + "x" * 50, headers={"authorization": f"Bearer {TOKEN}"})
    with client.websocket_connect("/api/events", headers={"authorization": f"Bearer {TOKEN}"}):
        during = scrape(client)
    after = scrape(client)

    assert 'zettcode_gateway_logins_total{outcome="failed"} 1' in after
    assert 'zettcode_gateway_logins_total{outcome="read"} 1' in after
    assert 'route="threads",method="GET",status="2xx"} 1' in after
    assert 'route="thread",method="GET",status="4xx"} 1' in after
    assert "never-a-route" not in after and "does-not-exist" not in after
    assert "zettcode_gateway_event_sockets 1" in during
    # Not asserted here: that the gauge falls back to 0. Starlette's TestClient runs a socket's cleanup only when it is
    # torn down, so it cannot show it; ``test_the_socket_gauge_falls_and_never_goes_below_zero`` covers the counter, and
    # a real uvicorn server was checked by hand (1 while open, 0 after the client closed).
    assert "zettcode_gateway_event_sockets_opened_total 1" in after
    assert "zettcode_gateway_threads_online" in after
    assert TOKEN not in after and READ not in after


def test_the_histogram_is_cumulative_and_its_count_matches_the_requests():
    metrics = Metrics(clock=lambda: 0.0)
    metrics.request("threads", "GET", 200, 0.004)
    metrics.request("threads", "GET", 200, 0.2)
    metrics.request("threads", "GET", 500, 30.0)
    text = metrics.render()

    assert 'request_seconds_bucket{route="threads",le="0.005"} 1' in text
    assert 'request_seconds_bucket{route="threads",le="0.25"} 2' in text
    assert 'request_seconds_bucket{route="threads",le="10.0"} 2' in text
    assert 'request_seconds_bucket{route="threads",le="+Inf"} 3' in text
    assert 'request_seconds_count{route="threads"} 3' in text
    assert 'requests_total{route="threads",method="GET",status="5xx"} 1' in text


def test_a_label_value_is_escaped():
    metrics = Metrics()
    text = metrics.render(info={"version": 'a"b\\c\nd'})
    assert 'version="a\\"b\\\\c\\nd"' in text
