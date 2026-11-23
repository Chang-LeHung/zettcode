"""Groups, history, the graph and the timeline over a real broker: HTTP for the routes, a file for what it remembers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from broker_helpers import http, started
from zettcode.broker.store import Store

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"


async def test_a_group_is_made_written_to_and_read_back_over_http(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        alpha = await run.peer(A, "alpha")
        bravo = await run.peer(B, "bravo")

        made = await http(
            run.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": alpha.key},
            json={"action": "create", "name": "Team", "members": ["bravo"]},
        )
        assert made.status_code == 200 and made.json()["group"]["members"] == [A, B]

        sent = http(
            run.port,
            "POST",
            "/messages",
            headers={"X-Session-Key": alpha.key},
            json={"group": "team", "text": "hello all", "via": "user"},
        )
        task = asyncio.ensure_future(sent)
        delivery = await bravo.accept("queued")
        reply = (await task).json()
        assert delivery["group"] == "team" and delivery["text"] == "hello all"
        assert reply["delivered"][0]["disposition"] == "queued" and reply["failed"] == []

        history = await http(run.port, "GET", "/history?group=team", headers={"X-Session-Key": bravo.key})
        assert [m["text"] for m in history.json()["messages"]] == ["hello all"]

        outsider = await http(run.port, "GET", "/history?group=team", headers={"X-Session-Key": "bogus"})
        assert outsider.status_code == 401

        graph = (await http(run.port, "GET", "/graph")).json()
        assert [g["name"] for g in graph["groups"]] == ["team"] and graph["recent"][0]["to"]["name"] == "team"

        window = (await http(run.port, "GET", "/timeline?since=0&until=99999999999")).json()
        assert [m["text"] for m in window["messages"]] == ["hello all"] and window["span"] is not None
        assert (await http(run.port, "GET", "/timeline?since=5&until=1")).status_code == 400
        assert (await http(run.port, "GET", "/graph", token=None)).status_code == 401
    finally:
        await run.aclose()


async def test_what_a_broker_remembers_is_there_after_it_restarts(tmp_path: Path):
    path = tmp_path / "broker.db"
    first = await started(store=Store(path))
    try:
        alpha = await first.peer(A, "alpha")
        await first.peer(B, "bravo")
        made = await http(
            first.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": alpha.key},
            json={"action": "create", "name": "team", "members": ["bravo"]},
        )
        assert made.status_code == 200
    finally:
        await first.aclose()

    second = await started(store=Store(path))
    try:
        alpha = await second.peer(A, "alpha")
        listed = await http(second.port, "GET", "/groups", headers={"X-Session-Key": alpha.key})
        assert [g["name"] for g in listed.json()["groups"]] == ["team"]
    finally:
        await second.aclose()


async def test_the_graph_can_be_asked_for_a_stretch_of_the_newest_messages(tmp_path: Path):
    """``?window=`` counts what the two said in the newest that many messages and keeps their whole history beside it,
    saying whether older messages are stored: how a page fills a picture from the recent past without reading it all.
    """
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        alpha = await run.peer(A, "alpha")
        bravo = await run.peer(B, "bravo")
        for text in ("one", "two", "three"):
            task = asyncio.ensure_future(alpha.post(to=B, text=text))
            await bravo.accept("queued")
            await task

        whole = (await http(run.port, "GET", "/graph")).json()
        assert [e["count"] for e in whole["edges"]] == [3], "no window: one count, the stretch is the history"
        assert "total" not in whole["edges"][0], "and no second number to tell it apart from"
        assert "window" not in whole, "and nothing is said about a stretch nobody asked for"
        assert "last" not in whole, "nor a map the stretch makes unnecessary"

        narrow = (await http(run.port, "GET", "/graph", params={"window": 2})).json()
        assert [(e["count"], e["total"]) for e in narrow["edges"]] == [(2, 3)]
        assert narrow["window"] == {"asked": 2, "more": True, "sessions": 2}
        assert set(narrow["last"]) == {A, B}, "the whole history's own times, which a slice must not lose"

        all_of_it = (await http(run.port, "GET", "/graph", params={"window": 8})).json()
        assert [(e["count"], e["total"]) for e in all_of_it["edges"]] == [(3, 3)]
        assert all_of_it["window"] == {"asked": 8, "more": False, "sessions": 2}, (
            "the beginning of the file, not a made-up count"
        )

        assert (await http(run.port, "GET", "/graph", params={"window": 0})).json()["edges"] == whole["edges"], (
            "a window of none is the answer an older reader expects"
        )
        assert (await http(run.port, "GET", "/graph", params={"window": "soon"})).status_code == 400
        assert (await http(run.port, "GET", "/graph", params={"window": -2})).status_code == 400
    finally:
        await run.aclose()


async def test_a_groups_own_messages_are_read_for_a_chat_window_and_the_graph_shows_the_last_one(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        alpha = await run.peer(A, "alpha")
        bravo = await run.peer(B, "bravo")
        await http(
            run.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": alpha.key},
            json={"action": "create", "name": "team", "members": ["bravo"]},
        )
        for text in ("one", "two", "three"):
            task = asyncio.ensure_future(
                http(
                    run.port,
                    "POST",
                    "/messages",
                    headers={"X-Session-Key": alpha.key},
                    json={"group": "team", "text": text},
                )
            )
            await bravo.accept("queued")
            await task

        newest = (await http(run.port, "GET", "/older", params={"group": "team", "before": 0, "limit": 2})).json()
        assert [m["text"] for m in newest["messages"]] == ["two", "three"] and newest["more"] is True
        before = newest["messages"][0]["id"]
        rest = (await http(run.port, "GET", "/older", params={"group": "team", "before": before, "limit": 5})).json()
        assert [m["text"] for m in rest["messages"]] == ["one"] and rest["more"] is False

        graph = (await http(run.port, "GET", "/graph")).json()
        assert graph["groups"][0]["last"]["text"] == "three"
        missing = await http(run.port, "GET", "/older", params={"group": "nope", "before": 0})
        assert missing.status_code == 404
        assert (await http(run.port, "GET", "/older", params={"before": 0})).status_code == 400
    finally:
        await run.aclose()


async def test_the_owner_may_put_a_session_in_a_group_it_is_not_in_but_a_session_may_not(tmp_path: Path):
    run = await started(store=Store(tmp_path / "broker.db"))
    try:
        alpha = await run.peer(A, "alpha")
        bravo = await run.peer(B, "bravo")
        await http(
            run.port,
            "POST",
            "/groups",
            headers={"X-Session-Key": alpha.key},
            json={"action": "create", "name": "team", "members": []},
        )
        own = {"action": "add", "name": "team", "members": [B]}

        refused = await http(run.port, "POST", "/groups", headers={"X-Session-Key": bravo.key}, json=own)
        joined = await http(run.port, "POST", "/groups", headers={"X-Session-Key": ""}, json=own)

        assert refused.status_code == 403
        assert joined.status_code == 200 and B in joined.json()["group"]["members"]
    finally:
        await run.aclose()
