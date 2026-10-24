"""A run goes on in its own conversation while the reader looks at another one."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from server_fakes import FakeClient, FakeRun, FakeSession
from zettcode.sdk.events import TextDelta
from zettcode.sdk.types import RunResult
from zettcode.server.app import create_app
from zettcode.server.settings import Settings


class Pool:
    """Hands the runner a client of its own for every conversation it opens, as the real SDK does."""

    def __init__(self, first: FakeClient) -> None:
        self.made = [first]
        self._first = True

    def __call__(self) -> FakeClient:
        if self._first:
            self._first = False
            return self.made[0]
        client = FakeClient()
        client.session = FakeSession(f"session-{len(self.made) + 1}", None)
        self.made.append(client)
        return client


@asynccontextmanager
async def serve(pool: Pool) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    app = create_app(Settings(workspace=Path("/tmp/zettcode-server-test")), client_factory=pool)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10) as http:
            yield http, app.state.runner


async def until(condition, seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("waited for something that did not happen")


def running(listing: httpx.Response) -> dict[str, bool]:
    return {item["id"]: item["running"] for item in listing.json()["sessions"]}


async def test_a_new_session_can_be_started_while_a_run_goes_on_and_the_list_says_which_one_runs():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(Pool(first)) as (http, runner):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)

        created = await http.post("/sessions")
        listing = await http.get("/sessions")

        assert created.status_code == 201
        new_id = created.json()["id"]
        assert new_id != "session-1" and (await http.get("/sessions/current")).json()["id"] == new_id
        flags = running(listing)
        assert flags["session-1"] is True, "the run did not stop because the reader moved on"
        assert flags[new_id] is False
        assert {slot.session_id for slot in runner.slots} == {"session-1", new_id}

        hold.set()
        assert (await long).status_code == 200


async def test_the_new_conversation_can_run_at_the_same_time_as_the_old_one():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "slowly")], hold=hold)])
    pool = Pool(first)
    async with serve(pool) as (http, _):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)
        await http.post("/sessions")

        quick = await http.post("/prompts", json={"text": "meanwhile"})

        assert quick.status_code == 200 and "event: result" in quick.text
        assert pool.made[1].asked == ["meanwhile"] and first.asked == ["the long one"]
        hold.set()
        await long


async def test_opening_the_running_session_again_brings_back_the_same_run_and_not_a_copy():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(Pool(first)) as (http, runner):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)
        await http.post("/sessions")

        back = await http.post("/sessions/session-1/open")

        assert back.status_code == 200 and back.json()["id"] == "session-1"
        assert runner.busy, "it is the run that was going, not a fresh client"
        assert (await http.get("/runs/current")).json()["running"] is True
        refused = await http.post("/prompts", json={"text": "on top of it"})
        assert refused.status_code == 409
        hold.set()
        await long


async def test_a_conversation_put_aside_is_closed_once_its_run_ends_because_everything_it_held_is_stored():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(Pool(first)) as (http, runner):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)
        await http.post("/sessions")
        assert len(runner.slots) == 2 and not first.closed

        hold.set()
        await long
        await until(lambda: first.closed)

        assert len(runner.slots) == 1
        assert running(await http.get("/sessions")).get("session-1") is False


async def test_the_answer_to_an_approval_goes_to_the_conversation_that_is_looked_at():
    """A background run waits for its answer where it is; what the reader approves is what the view shows."""
    from zettcode.sdk.events import ApprovalRequested

    hold = asyncio.Event()
    event = ApprovalRequested("session-1", "c1", "pytest -q", remember_supported=True)
    first = FakeClient(runs=[FakeRun([event], hold=hold)])
    async with serve(Pool(first)) as (http, runner):
        long = asyncio.ensure_future(
            http.post("/prompts", json={"text": "run it", "approvals": {"mode": "ask"}, "answer_timeout": 5})
        )
        await until(lambda: runner.slots[0].pending is not None)
        await http.post("/sessions")

        assert (await http.get("/runs/current")).json() == {"running": False, "pending": None}, "this one is idle"
        wrong = await http.post("/runs/approvals", json={"call_id": "c1", "approve": True})
        assert wrong.json() == {"resolved": False}, "it is not waiting on this conversation"

        await http.post("/sessions/session-1/open")
        waiting = (await http.get("/runs/current")).json()
        assert waiting["running"] is True and waiting["pending"]["call_id"] == "c1"
        right = await http.post("/runs/approvals", json={"call_id": "c1", "approve": True})
        assert right.json() == {"resolved": True}
        hold.set()
        await long


async def test_messages_for_a_conversation_wait_in_that_conversation():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    async with serve(Pool(first)) as (http, runner):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)
        from zettcode.sdk.types import IncomingMessage

        old = runner.slots[0]
        runner._received(old, IncomingMessage("peer", "api", "for the old one"))
        await http.post("/sessions")

        assert (await http.get("/messages")).json() == {"messages": []}, "not this conversation's"
        await http.post("/sessions/session-1/open")
        assert [m["text"] for m in (await http.get("/messages")).json()["messages"]] == ["for the old one"]
        hold.set()
        await long


async def test_opening_a_session_that_does_not_exist_leaves_the_run_and_the_view_where_they_were():
    hold = asyncio.Event()
    first = FakeClient(runs=[FakeRun([TextDelta("session-1", "working")], hold=hold)])
    pool = Pool(first)
    async with serve(pool) as (http, runner):
        long = asyncio.ensure_future(http.post("/prompts", json={"text": "the long one"}))
        await until(lambda: first.asked)

        missing = await http.post("/sessions/nowhere/open")

        assert missing.status_code == 404
        assert (await http.get("/sessions/current")).json()["id"] == "session-1"
        assert len(runner.slots) == 1, "the client made for the attempt was closed again"
        assert pool.made[1].closed
        hold.set()
        await long


async def test_a_finished_run_leaves_the_slot_idle_and_a_second_prompt_is_allowed():
    first = FakeClient(
        runs=[FakeRun([TextDelta("session-1", "one")], result=RunResult(text="one", session_id="session-1"))]
    )
    async with serve(Pool(first)) as (http, runner):
        assert (await http.post("/prompts", json={"text": "first"})).status_code == 200
        assert not runner.busy
        assert (await http.post("/prompts", json={"text": "second"})).status_code == 200
        assert first.asked == ["first", "second"]
