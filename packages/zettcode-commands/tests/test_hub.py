"""`/hub`: the three tabs, the mark kept per tab, and the two keys that act on a daemon."""

from __future__ import annotations

import dataclasses

from zettcode.commands.hub import TABS, Daemon, HubData, HubPage, Peer, Stored


def data(**changes: object) -> HubData:
    """A reading with one session, one daemon and one exchange."""
    base = HubData(
        peers=(Peer("main", "the parser", "working", "/work"),),
        daemons=(Daemon("d-1", "watcher", "idle", model="m", workspace="/work"),),
        offline=(Stored("old-id", "old"),),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def page(**changes: object) -> HubPage:
    """A page over :func:`data`, with its actions recorded."""
    return HubPage(data(**changes), on_close=lambda: None)


def test_the_page_opens_on_the_graph_and_the_sessions_tab_has_the_roster_and_the_offline_ones():
    opened = page()
    assert opened.tab == 0 and TABS[0] == "Graph"

    opened._show(1)

    labels = [item.label for item in opened.list.items]
    assert labels == ["main", "old"]
    assert "on disk" in opened.list.items[1].description


def test_tab_walks_the_three_and_keeps_a_mark_per_tab():
    opened = page()
    opened.capture_event(_key("tab"), None)
    opened.list.selected = 1

    opened.capture_event(_key("tab"), None)
    assert opened.tab == 2
    assert [item.label for item in opened.list.items] == ["watcher"]

    opened.capture_event(_key("tab"), None)
    assert opened.tab == 0
    opened.capture_event(_key("tab"), None)
    assert opened.tab == 1 and opened.list.selected == 1, "the sessions mark came back"


def test_shift_tab_walks_backwards():
    opened = page()

    opened.capture_event(_key("backtab"), None)

    assert opened.tab == len(TABS) - 1


def test_stop_and_start_act_on_the_daemon_under_the_mark():
    stopped: list[str] = []
    started: list[str] = []
    opened = HubPage(
        data(daemons=(Daemon("d-1", "watcher", "idle", model="m", workspace="/work"),)),
        on_close=lambda: None,
        on_stop=stopped.append,
        on_start=started.append,
    )
    opened._show(2)
    opened.capture_event(_key("s"), None)

    assert stopped == ["d-1"], "s stops the daemon under the mark"

    dead = HubPage(
        data(daemons=(Daemon("d-2", "old", "dead", workspace="/work"),)),
        on_close=lambda: None,
        on_start=started.append,
    )
    dead._show(2)
    dead.capture_event(_key("enter"), None)

    assert started == ["d-2"], "enter starts a stopped one"


def test_a_reading_replaces_the_note_and_an_action_says_its_own_after_it():
    opened = page()
    opened.note("stopped d-1")

    opened.set_data(data())

    assert opened.subtitle is None, "a plain reading clears what an action said"

    opened.set_data(data(note="the broker cannot be read: offline"))
    assert opened.subtitle == "the broker cannot be read: offline"


def test_a_refresh_is_asked_for_and_a_note_is_shown():
    refreshed: list[bool] = []
    opened = HubPage(data(), on_close=lambda: None, on_refresh=lambda: refreshed.append(True))

    opened.capture_event(_key("r"), None)
    opened.note("stopped d-1")

    assert refreshed == [True]
    assert opened.subtitle == "stopped d-1"


def _key(name: str) -> object:
    """A key event with ``name``, as the page decodes one."""
    from zettcode.tui import KeyEvent

    return KeyEvent(key=name)


def test_a_scheduled_action_is_kept_and_its_failure_reaches_the_page():
    """`r`, `s` and Enter schedule a task; a failure must say so on the page, not at the interpreter."""
    import asyncio

    from zettcode.commands.hub import HubCommand

    async def failing() -> None:
        raise RuntimeError("the daemon refused")

    async def scenario() -> HubPage:
        command = HubCommand()
        opened = page()
        command._page = opened
        command._start(failing())
        for _ in range(10):
            await asyncio.sleep(0)
        assert not command._actions, "a finished action is forgotten"
        return opened

    assert asyncio.run(scenario()).subtitle == "the daemon refused"


def test_a_cancelled_action_is_forgotten_without_complaint():
    import asyncio

    from zettcode.commands.hub import HubCommand

    async def forever() -> None:
        await asyncio.sleep(3600)

    async def scenario() -> HubPage:
        command = HubCommand()
        opened = page()
        command._page = opened
        command._start(forever())
        for _ in range(5):
            await asyncio.sleep(0)
        for task in list(command._actions):
            task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not command._actions
        return opened

    assert asyncio.run(scenario()).subtitle is None


class _FakeSessions:
    """The store as the page reads it: a few records, the reader's own among them."""

    def __init__(self, ids: list[str]) -> None:
        self._ids = ids
        self.limit: int | None = None

    async def list(self, *, limit: int | None = None) -> list[object]:
        self.limit = limit

        class Info:
            def __init__(self, name: str) -> None:
                self.id = name
                self.title = "" if name.startswith("old") else name

        return [Info(name) for name in self._ids]


class _FakeClient:
    """The slice of the SDK the reading uses."""

    def __init__(self) -> None:
        self.session = type("Session", (), {"id": "self-1"})()
        self.sessions = _FakeSessions(["self-1", "p-1", "old-9"])

    def peers(self) -> list[object]:
        return [
            type(
                "Peer",
                (),
                {
                    "handle": "p-1",
                    "title": "the parser",
                    "status": "idle",
                    "workspace": "/work",
                    "kind": "session",
                    "session_id": "p-1",
                },
            )()
        ]


def test_the_reading_lists_only_the_stored_sessions_that_are_not_registered_and_not_self():
    """The reader's own session is stored and never registered, so it must never be called offline."""
    import asyncio

    from zettcode.commands.hub import HubCommand, HubData

    data = asyncio.run(HubCommand()._read(_FakeClient()))

    assert [(s.session_id, s.title) for s in data.offline] == [("old-9", "old-9")]
    assert data.peers[0].session_id == "p-1"
    assert isinstance(data, HubData)


def test_enter_on_an_offline_session_resumes_it_and_on_a_live_one_does_nothing():
    started: list[str] = []
    opened = HubPage(data(), on_close=lambda: None, on_start=started.append)
    opened._show(1)

    opened.list.selected = 0  # "main", registered
    opened.capture_event(_key("enter"), None)
    assert started == []

    opened.list.selected = 1  # "old", stored and not running
    opened.capture_event(_key("enter"), None)
    assert started == ["old-id"], "the id is what resumes it, not the title"
    assert "enter resume" in opened.footer


def test_resuming_a_stored_session_starts_a_daemon_here(monkeypatch):
    import asyncio

    from zettcode.commands.hub import HubCommand
    from zettcode.sdk import daemons

    calls: list[tuple[object, dict[str, object]]] = []

    async def spawn(workspace, **kwargs):
        calls.append((workspace, kwargs))
        return type("Info", (), {"session_id": "abcdef123456"})()

    async def read(self, client):
        return data()

    monkeypatch.setattr(daemons, "spawn_daemon", spawn)
    monkeypatch.setattr(HubCommand, "_read", read)
    opened = page()

    asyncio.run(HubCommand()._resume(opened, object(), "old-id"))
    asyncio.run(HubCommand()._resume(opened, object(), "nobody"))

    assert calls == [(".", {"model": None, "resume": "old-id"})]
    assert opened.subtitle == "started abcdef12"


def test_a_daemon_row_says_its_state_once():
    opened = HubPage(
        data(daemons=(Daemon("a", "live", "working"), Daemon("b", "idle one", "idle"), Daemon("c", "gone", "dead"))),
        on_close=lambda: None,
    )
    opened._show(2)

    said = [item.description for item in opened.list.items]

    assert said[0].count("working") == 1 and said[1].count("idle") == 1
    assert "stopped" in said[2] and "dead" in said[2], "a dead process keeps the word that explains the red"


def test_an_outsider_row_does_not_say_external_twice():
    opened = HubPage(data(peers=(Peer("bot", "ci", "idle", "/w", "external"),)), on_close=lambda: None)
    opened._show(1)

    assert opened.list.items[0].description.count("external") == 1
