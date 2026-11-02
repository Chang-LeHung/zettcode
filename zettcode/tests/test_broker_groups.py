"""Group chats, the persistent history, observers and the timeline: the hub driven by hand, and the store on a file."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from zettcode.broker.hub import Hub, Session
from zettcode.broker.protocol import Refused
from zettcode.broker.store import Store

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"
C = "03c30d97-cccc-7000-8000-000000000003"


class Line:
    """The other end of one session: what the hub pushed to it, and how it answers deliveries."""

    def __init__(self, hub: Hub, session_id: str, title: str) -> None:
        self.hub = hub
        self.session: Session = hub.admit(lambda code: None)
        self.seen: list[dict[str, Any]] = []
        hub.hear(self.session, {"op": "session", "n": 1, "session_id": session_id, "title": title})

    def pushed(self, op: str) -> list[dict[str, Any]]:
        while not self.session.outbox.empty():
            self.seen.append(self.session.outbox.get_nowait())
        return [x for x in self.seen if x["op"] == op]

    async def answer_deliveries(self, disposition: str = "started") -> None:
        """Ack, as the shell would, every delivery that arrives from now on."""
        while True:
            line = await self.session.outbox.get()
            self.seen.append(line)
            if line["op"] == "deliver":
                self.hub.hear(
                    self.session, {"op": "ack", "id": line["id"], "accepted": True, "disposition": disposition}
                )


@pytest.fixture
async def trio():
    hub = Hub(ack_timeout=0.5)
    a, b, c = Line(hub, A, "alpha"), Line(hub, B, "bravo"), Line(hub, C, "charlie")
    tasks = [asyncio.ensure_future(x.answer_deliveries()) for x in (a, b, c)]
    yield hub, a, b, c
    for task in tasks:
        task.cancel()


def group(hub: Hub, line: Line, action: str, name: str, *members: str) -> dict[str, Any]:
    return hub.manage_group(line.session.key, {"action": action, "name": name, "members": list(members)})


async def test_a_group_reaches_every_other_connected_member_and_each_is_told_which_group(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "#Review", "bravo", "charlie")

    reply = await hub.send(a.session.key, {"group": "review", "text": "ship it", "via": "user"})

    assert reply["group"] == "review" and reply["failed"] == []
    assert sorted(d["to"]["handle"] for d in reply["delivered"]) == ["bravo", "charlie"]
    for peer in (b, c):
        delivery = peer.pushed("deliver")[0]
        assert delivery["group"] == "review" and delivery["text"] == "ship it" and delivery["from"]["handle"] == "alpha"
    assert not a.pushed("deliver"), "the sender is not sent its own message"


async def test_only_a_member_may_write_read_or_change_a_group(trio):
    hub, a, b, _ = trio
    group(hub, a, "create", "private", "charlie")

    with pytest.raises(Refused) as written:
        await hub.send(b.session.key, {"group": "private", "text": "hi", "via": "agent"})
    assert written.value.reason == "denied"
    with pytest.raises(Refused) as read:
        hub.history(b.session.key, {"group": "private"})
    assert read.value.reason == "denied"
    with pytest.raises(Refused) as changed:
        group(hub, b, "add", "private", "bravo")
    assert changed.value.reason == "denied"
    with pytest.raises(Refused) as unknown:
        await hub.send(a.session.key, {"group": "nope", "text": "hi", "via": "agent"})
    assert unknown.value.reason == "unknown"


async def test_the_sessions_list_holds_only_the_groups_that_session_is_in(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "alpha-charlie", "charlie")

    assert [g["name"] for g in a.pushed("groups")[-1]["groups"]] == ["alpha-charlie"]
    assert [g["name"] for g in c.pushed("groups")[-1]["groups"]] == ["alpha-charlie"]
    assert b.pushed("groups")[-1]["groups"] == []
    assert [g["name"] for g in hub.listing_groups(b.session.key)["groups"]] == []
    assert [g["name"] for g in hub.listing_groups(None)["groups"]] == ["alpha-charlie"], "the owner sees all"


async def test_members_come_and_go_and_an_empty_group_is_deleted(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "team", "bravo")
    group(hub, b, "add", "team", "charlie")
    assert len(hub.listing_groups(c.session.key)["groups"]) == 1

    group(hub, a, "leave", "team")
    group(hub, b, "remove", "team", C)
    assert hub.listing_groups(a.session.key)["groups"] == []
    assert group(hub, b, "leave", "team") == {"group": None}
    assert hub.store.group("team") is None
    with pytest.raises(Refused) as again:
        group(hub, a, "create", "bad name")
    assert again.value.reason == "invalid"


async def test_a_group_name_is_taken_once(trio):
    hub, a, b, _ = trio
    group(hub, a, "create", "team")

    with pytest.raises(Refused) as taken:
        group(hub, b, "create", "TEAM")
    assert taken.value.reason == "duplicate"


async def test_a_member_that_is_offline_is_skipped_and_nobody_online_is_gone(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "team", "bravo", "charlie")
    hub.release(c.session)

    reply = await hub.send(a.session.key, {"group": "team", "text": "hi", "via": "agent"})
    assert [d["to"]["handle"] for d in reply["delivered"]] == ["bravo"]

    hub.release(b.session)
    with pytest.raises(Refused) as nobody:
        await hub.send(a.session.key, {"group": "team", "text": "hi again", "via": "agent"})
    assert nobody.value.reason == "gone"


async def test_a_member_that_refuses_is_reported_and_the_rest_still_get_it(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "team", "bravo", "charlie")
    b.session.push = lambda line: None  # type: ignore[method-assign]  # bravo never answers
    hub.ack_timeout = 0.05

    reply = await hub.send(a.session.key, {"group": "team", "text": "hi", "via": "agent"})

    assert [d["to"]["handle"] for d in reply["delivered"]] == ["charlie"]
    assert [f["handle"] for f in reply["failed"]] == ["bravo"]
    assert hub.history(a.session.key, {"group": "team"})["messages"][0]["status"] == "partial"


async def test_to_and_group_together_are_refused(trio):
    hub, a, *_ = trio
    group(hub, a, "create", "team", "bravo")

    with pytest.raises(Refused) as both:
        await hub.send(a.session.key, {"group": "team", "to": "bravo", "text": "hi"})
    assert both.value.reason == "invalid"


async def test_an_outsider_without_a_session_cannot_write_to_a_group(trio):
    hub, a, *_ = trio
    group(hub, a, "create", "team", "bravo")

    with pytest.raises(Refused) as outsider:
        await hub.send(None, {"group": "team", "text": "hi", "from": {"name": "ci"}})
    assert outsider.value.reason == "denied"


async def test_the_history_between_two_is_theirs_alone(trio):
    hub, a, b, c = trio
    await hub.send(a.session.key, {"to": "bravo", "text": "one", "via": "user"})
    await hub.send(b.session.key, {"to": "alpha", "text": "two", "via": "agent"})
    await hub.send(a.session.key, {"to": "charlie", "text": "secret", "via": "user"})

    mine = hub.history(a.session.key, {"with": "bravo"})
    assert [m["text"] for m in mine["messages"]] == ["one", "two"] and mine["peer"] == B
    assert [m["text"] for m in hub.history(b.session.key, {"with": "alpha"})["messages"]] == ["one", "two"]
    assert [m["text"] for m in hub.history(c.session.key, {})["messages"]] == ["secret"]
    assert hub.history(c.session.key, {"with": "bravo"})["messages"] == []
    with pytest.raises(Refused) as itself:
        hub.history(a.session.key, {"with": "alpha"})
    assert itself.value.reason == "self"
    assert [m["text"] for m in hub.history(a.session.key, {"with": "bravo", "limit": "1"})["messages"]] == ["two"]


async def test_the_history_of_a_session_that_has_left_is_still_found_by_its_id_or_old_handle(trio):
    hub, a, b, _ = trio
    await hub.send(a.session.key, {"to": "bravo", "text": "remember", "via": "user"})
    hub.release(b.session)

    for name in (B, "bravo"):
        assert [m["text"] for m in hub.history(a.session.key, {"with": name})["messages"]] == ["remember"]
    with pytest.raises(Refused) as nobody:
        hub.history(a.session.key, {"with": "never-existed"})
    assert nobody.value.reason == "unknown"


async def test_paging_back_with_before(trio):
    hub, a, *_ = trio
    for n in range(5):
        await hub.send(a.session.key, {"to": "bravo", "text": f"m{n}", "via": "user"})

    page = hub.history(a.session.key, {"with": "bravo", "limit": "2"})["messages"]
    older = hub.history(a.session.key, {"with": "bravo", "limit": "2", "before": str(page[0]["id"])})["messages"]

    assert [m["text"] for m in page] == ["m3", "m4"] and [m["text"] for m in older] == ["m1", "m2"]


async def test_observers_are_told_of_every_message_and_of_changes_nobody_else_is(trio):
    hub, a, b, c = trio
    hub.hear(c.session, {"op": "observe", "n": 5})
    c.pushed("done")
    c.seen.clear()

    await hub.send(a.session.key, {"to": "bravo", "text": "hello", "via": "user"})
    group(hub, a, "create", "team", "bravo")

    kinds = [(x["kind"], x.get("message", {}).get("text")) for x in c.pushed("traffic")]
    assert ("message", "hello") in kinds and ("graph", None) in kinds
    assert not a.pushed("traffic")

    hub.hear(c.session, {"op": "unobserve"})
    before = len(c.pushed("traffic"))
    await hub.send(a.session.key, {"to": "bravo", "text": "again", "via": "user"})
    assert len(c.pushed("traffic")) == before


async def test_the_timeline_returns_a_window_of_the_past_oldest_first(trio):
    hub, a, *_ = trio
    now = [1000.0]
    hub.store.clock = lambda: now[0]
    for n in range(4):
        now[0] = 1000.0 + n * 100
        await hub.send(a.session.key, {"to": "bravo", "text": f"m{n}", "via": "user"})

    window = hub.timeline(1050, 1250, 100)
    assert [m["text"] for m in window["messages"]] == ["m1", "m2"]
    assert window["span"] == [1000.0, 1300.0]
    assert [m["text"] for m in hub.timeline(0, 9999, 2)["messages"]] == ["m2", "m3"], "the newest when it is too long"
    graph = hub.graph()
    assert graph["edges"][0]["count"] == 4 and len(graph["recent"]) == 4


async def test_a_store_that_fails_loses_the_record_not_the_message(trio):
    hub, a, *_ = trio

    def broken(**_: Any) -> None:
        raise RuntimeError("disk full")

    hub.store.add_message = broken  # type: ignore[method-assign]

    reply = await hub.send(a.session.key, {"to": "bravo", "text": "still sent", "via": "user"})

    assert reply["to"]["handle"] == "bravo" and "id" not in reply


def test_messages_and_groups_survive_the_store_being_reopened(tmp_path: Path):
    path = tmp_path / "broker.db"
    first = Store(path)
    first.create_group("team", A, [A, B])
    first.add_message(
        sender=(A, "alpha", "Alpha"),
        kind="session",
        to=(B, "bravo", "Bravo"),
        recipients=[B],
        text="kept",
        via="user",
        hops=1,
        mode="steer",
        status="delivered",
        disposition="started",
    )
    first.close()

    second = Store(path)

    assert second.group("team")["members"] == [A, B]
    assert [m["text"] for m in second.between(A, B)] == ["kept"]
    assert second.between(A, B)[0]["from"] == {"session_id": A, "handle": "alpha", "title": "Alpha"}
    second.close()


def test_the_oldest_messages_are_pruned_past_the_limit():
    store = Store(keep=10)
    for n in range(400):
        store.add_message(
            sender=(A, "a", ""),
            kind="session",
            to=(B, "b", ""),
            recipients=[B],
            text=str(n),
            via="user",
            hops=1,
            mode="steer",
            status="delivered",
            disposition="",
        )

    kept = store.recent(limit=2000)

    assert 10 <= len(kept) <= 210 and kept[-1]["text"] == "399"


async def test_older_pages_back_from_a_message_id_and_says_when_nothing_is_left(trio):
    hub, a, *_ = trio
    for n in range(5):
        await hub.send(a.session.key, {"to": "bravo", "text": f"m{n}", "via": "user"})
    newest = hub.store.recent(limit=1)[0]["id"]

    page = hub.older(newest, 2)
    assert [m["text"] for m in page["messages"]] == ["m2", "m3"] and page["more"] is True
    last = hub.older(page["messages"][0]["id"], 10)
    assert [m["text"] for m in last["messages"]] == ["m0", "m1"] and last["more"] is False
    assert hub.older(last["messages"][0]["id"], 10) == {"messages": [], "more": False}


async def test_a_session_is_in_a_limited_number_of_groups_and_a_group_holds_a_limited_number_of_sessions(
    trio, monkeypatch
):
    from zettcode.broker import hub as hub_module

    hub, a, b, _ = trio
    monkeypatch.setattr(hub_module, "MAX_GROUPS_PER_SESSION", 2)
    group(hub, a, "create", "one", "bravo")
    group(hub, a, "create", "two", "bravo")

    with pytest.raises(Refused) as creating:
        group(hub, a, "create", "three", "bravo")
    assert creating.value.reason == "busy" and "2 groups" in str(creating.value)
    group(hub, b, "add", "one", "alpha")  # already in it: not counted twice
    assert len(hub.store.groups_of(A)) == 2 and len(hub.store.groups_of(B)) == 2

    monkeypatch.setattr(hub_module, "MAX_GROUP_MEMBERS", 1)
    with pytest.raises(Refused) as crowded:
        group(hub, a, "create", "four")
    assert crowded.value.reason in ("busy", "invalid")


async def test_a_bad_before_is_refused_and_does_not_restart_paging(trio):
    hub, a, *_ = trio
    await hub.send(a.session.key, {"to": "bravo", "text": "one", "via": "user"})

    for bad in ("abc", "0", "-3"):
        with pytest.raises(Refused) as refused:
            hub.history(a.session.key, {"with": "bravo", "before": bad})
        assert refused.value.reason == "invalid"
    assert len(hub.history(a.session.key, {"with": "bravo", "before": ""})["messages"]) == 1


async def test_a_member_that_fails_unexpectedly_is_reported_and_the_send_is_still_written_down(trio):
    hub, a, b, c = trio
    group(hub, a, "create", "team", "bravo", "charlie")
    real = hub._hand_over

    async def broken(recipient, message, handle):
        if handle == "bravo":
            raise RuntimeError("boom")
        return await real(recipient, message, handle)

    hub._hand_over = broken  # type: ignore[method-assign]

    reply = await hub.send(a.session.key, {"group": "team", "text": "hi", "via": "agent"})

    assert [d["to"]["handle"] for d in reply["delivered"]] == ["charlie"]
    assert reply["failed"][0]["handle"] == "bravo" and reply["failed"][0]["reason"] == "internal"
    assert hub.history(a.session.key, {"group": "team"})["messages"][0]["status"] == "partial"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="the scenario needs a second connection holding the file while it is rebuilt; Windows refuses to delete a "
    "file another handle has open (the broker then keeps its history in memory, like any store that fails to open)",
)
def test_an_older_file_in_wal_mode_is_rebuilt_so_inserts_keep_working_and_nothing_old_comes_back(
    tmp_path: Path, monkeypatch
):
    import sqlite3

    from zettcode.broker import store as store_module

    path = tmp_path / "broker.db"
    old = sqlite3.connect(path)
    old.execute("PRAGMA journal_mode=WAL")
    old.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, only_old_column TEXT)")
    old.execute("INSERT INTO messages (only_old_column) VALUES ('stale')")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    assert (tmp_path / "broker.db-wal").exists(), (
        "the old file has a write-ahead log beside it, as a real broker's does"
    )
    monkeypatch.setattr(store_module, "SCHEMA_VERSION", 2)

    store = Store(path)  # `old` is still open, so its -wal is there for the store to deal with
    old.close()
    stored = store.add_message(
        sender=(A, "a", ""),
        kind="session",
        to=(B, "b", ""),
        recipients=[B],
        text="x",
        via="user",
        hops=1,
        mode="steer",
        status="delivered",
        disposition="",
    )

    assert stored["text"] == "x" and [m["text"] for m in store.recent()] == ["x"]
    store.close()
    again = sqlite3.connect(path)
    assert again.execute("PRAGMA user_version").fetchone()[0] == 2
    assert "only_old_column" not in [c[1] for c in again.execute("PRAGMA table_info(messages)")]
    again.close()
    assert [m["text"] for m in Store(path).recent()] == ["x"], "and what is written is kept on the next open"


def test_a_group_created_twice_in_the_store_raises_and_leaves_no_half_group():
    import sqlite3

    store = Store()
    store.create_group("team", A, [A])
    with pytest.raises(sqlite3.IntegrityError):
        store.create_group("team", B, [B])
    assert store.group("team")["members"] == [A]


async def test_a_session_may_observe_and_a_key_less_history_is_the_owners(trio):
    """The boundary as it is decided: the token is the credential, a key narrows a request to its own session."""
    hub, a, b, c = trio
    await hub.send(a.session.key, {"to": "bravo", "text": "private", "via": "user"})
    hub.hear(c.session, {"op": "observe"})
    await hub.send(a.session.key, {"to": "bravo", "text": "watched", "via": "user"})

    assert [x["message"]["text"] for x in c.pushed("traffic") if x["kind"] == "message"] == ["watched"]
    assert [m["text"] for m in hub.history(None, {"a": A, "b": B})["messages"]] == ["private", "watched"]
    assert hub.history(c.session.key, {"with": "alpha"})["messages"] == [], "a session's own key narrows it"


def test_a_file_written_by_a_newer_zettcode_is_refused_and_left_untouched(tmp_path: Path):
    import sqlite3

    from zettcode.broker.store import SCHEMA_VERSION, TooNew

    path = tmp_path / "broker.db"
    newer = sqlite3.connect(path)
    newer.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, future TEXT)")
    newer.execute("INSERT INTO messages (future) VALUES ('kept')")
    newer.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    newer.commit()
    newer.close()

    with pytest.raises(TooNew):
        Store(path)

    check = sqlite3.connect(path)
    assert check.execute("SELECT future FROM messages").fetchall() == [("kept",)]
    check.close()


def test_a_failed_commit_does_not_leave_the_connection_unable_to_make_groups(monkeypatch):
    store = Store()
    real = store._db

    class Wrapper:
        def __init__(self) -> None:
            self.fail = True

        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *args):
            if sql == "COMMIT" and self.fail:
                self.fail = False
                raise OSError("disk full")
            return real.execute(sql, *args)

    store._db = Wrapper()  # type: ignore[assignment]
    with pytest.raises(OSError):
        store.create_group("one", A, [A])
    store.create_group("two", A, [A])

    assert store.group("two") is not None and store.group("one") is None


def _say(store: Store, sender: str, to: str, kind: str = "session") -> None:
    store.add_message(
        sender=(sender, sender, ""),
        kind=kind,
        to=(to, to, ""),
        recipients=[to],
        text="x",
        via="user",
        hops=1,
        mode="steer",
        status="delivered",
        disposition="",
    )


def test_a_full_history_is_a_third_of_a_million_messages():
    from zettcode.broker.store import KEEP

    assert KEEP == 320_000 and Store().keep == KEEP


def test_pair_totals_are_counted_once_and_kept_up_to_date_without_counting_again(tmp_path: Path):
    clock = iter(range(1, 1000))
    store = Store(tmp_path / "broker.db", clock=lambda: float(next(clock)))
    for sender, to in [(A, B), (B, A), (A, B)]:
        _say(store, sender, to)
    _say(store, A, "team", kind="group")
    assert store._pairs is not None and store._pairs[(A, B)][0] == 3, "counted at open, then kept up to date"

    first = store.edges()
    assert first == [{"a": A, "b": B, "count": 3, "last": 3.0}], "a pair is one pair whichever way it was said"
    assert store._pairs is not None

    _say(store, B, A)
    _say(store, B, "03c30d97-cccc-7000-8000-000000000003")
    _say(store, A, "team", kind="group")
    again = store.edges()
    assert {(e["a"], e["b"]): e["count"] for e in again} == {(A, B): 4, (B, "03c30d97-cccc-7000-8000-000000000003"): 1}
    assert [e["last"] for e in again] == sorted((e["last"] for e in again), reverse=True), "newest pair first"

    # What was kept up to date is what a fresh count of the same file says.
    store.close()
    assert Store(tmp_path / "broker.db", clock=lambda: 0.0).edges() == again


def test_the_totals_are_not_taken_back_when_old_messages_are_deleted():
    store = Store(keep=10)
    store.edges()  # counting starts, so that what follows is kept up to date
    for _ in range(400):
        _say(store, A, B)

    assert store.edges()[0]["count"] == 400, "a total is what was handled, not what is still in the file"
    assert len(store.recent(limit=2000)) < 400


def test_a_window_that_holds_more_than_was_asked_for_says_it_is_cut_and_keeps_its_end():
    from zettcode.broker.hub import Hub
    from zettcode.broker.store import MAX_WINDOW

    hub = Hub(store=Store(keep=100_000))
    for _ in range(30):
        _say(hub.store, A, B)

    whole = hub.timeline(0, 1e12, 30)
    assert len(whole["messages"]) == 30 and whole["truncated"] is False, "exactly what was asked for is not cut"
    cut = hub.timeline(0, 1e12, 29)
    assert len(cut["messages"]) == 29 and cut["truncated"] is True
    assert cut["messages"][-1]["id"] == whole["messages"][-1]["id"], "it is the start that is missing, never the end"
    assert [m["id"] for m in cut["messages"]] == sorted(m["id"] for m in cut["messages"]), "still oldest first"
    assert hub.timeline(0, 1e12, 10**9)["truncated"] is False and MAX_WINDOW == 20_000


def test_a_replay_can_read_far_more_than_a_page_of_messages():
    from zettcode.broker.store import MAX_ROWS, MAX_WINDOW

    store = Store(keep=100_000)
    for _ in range(MAX_ROWS + 500):
        _say(store, A, B)

    assert len(store.window(0, 1e12, limit=MAX_WINDOW)) == MAX_ROWS + 500
    assert len(store.window(0, 1e12, limit=10**9)) == MAX_ROWS + 500, "capped at MAX_WINDOW, which is more than this"
    assert len(store.recent(limit=10**9)) == MAX_ROWS, "an ordinary page is still bounded"


def test_a_file_that_is_opened_again_counts_its_pairs_before_anyone_looks():
    path = Path(tempfile.mkdtemp()) / "broker.db"
    first = Store(path)
    for _ in range(3):
        _say(first, A, B)
    first.close()

    second = Store(path)
    assert second._pairs is not None and second._pairs[(A, B)][0] == 3, "so the first look at the graph reads nothing"
    second.close()


def test_a_file_cannot_grow_past_its_byte_budget_however_few_messages_it_holds():
    store = Store(keep=100_000, max_bytes=2 << 20)
    long = "x" * 30_000
    for n in range(400):
        store.add_message(
            sender=(A, "a", ""),
            kind="session",
            to=(B, "b", ""),
            recipients=[B],
            text=f"{n} {long}",
            via="user",
            hops=1,
            mode="steer",
            status="delivered",
            disposition="",
        )

    kept = store.recent(limit=2000)
    assert 0 < len(kept) < 400, "the oldest were dropped though the count is far below the limit"
    assert kept[-1]["text"].startswith("399 "), "and what is kept is the newest"
    assert store._size() <= 2 << 20, "the file is back under its budget when the last check ran (the 400th message)"


def test_a_window_cut_exactly_at_the_cap_still_says_it_was_cut(monkeypatch):
    from zettcode.broker import hub as hub_module
    from zettcode.broker import store as store_module
    from zettcode.broker.hub import Hub

    monkeypatch.setattr(hub_module, "MAX_WINDOW", 10)
    monkeypatch.setattr(store_module, "MAX_WINDOW", 10)
    hub = Hub(store=Store(keep=1000))
    for _ in range(25):
        _say(hub.store, A, B)

    at_cap = hub.timeline(0, 1e12, 10)  # asking for exactly the most a read can return
    assert at_cap["truncated"] is True and len(at_cap["messages"]) == 9, "never claims a stretch of 25 is complete"
    assert [m["id"] for m in at_cap["messages"]][-1] == 25, "and what it holds is the end of the stretch"
    assert hub.timeline(0, 1e12, 10**9)["truncated"] is True
    small = Hub(store=Store(keep=1000))
    for _ in range(5):
        _say(small.store, A, B)
    assert small.timeline(0, 1e12, 10)["truncated"] is False and len(small.timeline(0, 1e12, 10)["messages"]) == 5
