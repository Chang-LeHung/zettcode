"""`/hub`: the three tabs, the mark kept per tab, the keys that act on a node or a row, and the reading behind them."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from zettcode.commands.hub import (
    DAEMONS,
    GRAPH,
    SESSIONS,
    TABS,
    Daemon,
    HubCommand,
    HubData,
    HubPage,
    Peer,
    StoredSession,
)
from zettcode.commands.hub_graph import Link, Node
from zettcode.tui import KeyEvent, Rect


def data(**changes: object) -> HubData:
    """A reading with one session, one daemon and one stored session."""
    base = HubData(
        peers=(Peer("main", "the parser", "working", "/work"),),
        daemons=(Daemon("d-1", "watcher", "idle", model="m", workspace="/work"),),
        offline=(StoredSession("old-id", "old"),),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def page(**changes: object) -> HubPage:
    """A page over :func:`data`."""
    return HubPage(data(**changes), on_close=lambda: None)


def _key(name: str) -> object:
    """A key event with ``name``, as the page decodes one."""
    return KeyEvent(key=name)


def test_the_tabs_are_named_once_and_the_constants_agree_with_them():
    assert TABS == ("Graph", "Sessions", "Daemons")
    assert (GRAPH, SESSIONS, DAEMONS) == (0, 1, 2)
    assert page().tab == GRAPH


def test_the_sessions_tab_has_the_roster_and_the_offline_ones():
    opened = page()

    opened._show(SESSIONS)

    assert [item.label for item in opened.list.items] == ["main", "old"]
    assert "on disk" in opened.list.items[1].description


def test_tab_walks_the_three_and_keeps_a_mark_per_tab():
    opened = page()
    opened.capture_event(_key("tab"), None)
    opened.list.selected = 1

    opened.capture_event(_key("tab"), None)
    assert opened.tab == DAEMONS
    assert [item.label for item in opened.list.items] == ["watcher"]

    opened.capture_event(_key("tab"), None)
    assert opened.tab == GRAPH
    opened.capture_event(_key("tab"), None)
    assert opened.tab == SESSIONS and opened.list.selected == 1, "the sessions mark came back"


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
    opened._show(DAEMONS)
    opened.capture_event(_key("s"), None)

    assert stopped == ["d-1"], "s stops the daemon under the mark"

    dead = HubPage(
        data(daemons=(Daemon("d-2", "old", "dead", workspace="/work"),)),
        on_close=lambda: None,
        on_start=started.append,
    )
    dead._show(DAEMONS)
    dead.capture_event(_key("enter"), None)

    assert started == ["d-2"], "enter starts a stopped one"


def test_a_session_row_has_no_action_only_a_daemon_can_be_started():
    started: list[str] = []
    opened = HubPage(data(), on_close=lambda: None, on_start=started.append, on_stop=started.append)
    opened._show(SESSIONS)

    for row in (0, 1):  # "main" registered, "old" stored with no process
        opened.list.selected = row
        opened.capture_event(_key("enter"), None)
        opened.capture_event(_key("s"), None)

    assert started == [], "neither Enter nor s does anything on the sessions tab"
    assert "enter" not in opened.footer, "and the footer does not offer it"
    assert "no process" in opened.list.items[1].description


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


def test_a_scheduled_action_is_kept_and_its_failure_reaches_the_page():
    """`r`, `s` and Enter schedule a task; a failure must say so on the page, not at the interpreter."""

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


# -- the rows ---------------------------------------------------------------------------------------


def test_a_daemon_row_says_its_state_once():
    opened = HubPage(
        data(daemons=(Daemon("a", "live", "working"), Daemon("b", "idle one", "idle"), Daemon("c", "gone", "dead"))),
        on_close=lambda: None,
    )
    opened._show(DAEMONS)

    said = [item.description for item in opened.list.items]

    assert said[0].count("working") == 1 and said[1].count("idle") == 1
    assert "stopped" in said[2] and "dead" in said[2], "a dead process keeps the word that explains the red"


def test_an_outsider_row_does_not_say_external_twice():
    opened = HubPage(data(peers=(Peer("bot", "ci", "idle", "/w", "external"),)), on_close=lambda: None)
    opened._show(SESSIONS)

    assert opened.list.items[0].description.count("external") == 1


# -- the graph tab ----------------------------------------------------------------------------------


def _graph_data() -> HubData:
    nodes = (
        Node("me", "main", "working", me=True),
        Node("a", "review", "idle"),
        Node("b", "docs", "idle"),
    )
    return data(nodes=nodes, links=(Link("me", "a", 55), Link("a", "b", 3)))


def crowd_nodes(count: int) -> tuple[tuple[Node, ...], tuple[Link, ...]]:
    """The reader's own session and ``count - 1`` others, all talking to it and some to each other."""
    nodes = (Node("me", "main", "working", me=True), *(Node(f"n{i}", f"node-{i}", "idle") for i in range(1, count)))
    links = tuple(Link("me", f"n{i}", i) for i in range(1, count)) + tuple(
        Link(f"n{i}", f"n{i + 1}", 2) for i in range(1, count - 1, 2)
    )
    return nodes, links


def _rendered(opened: HubPage, width: int, height: int) -> list[str]:
    from zettcode.tui import Canvas

    opened.layout(Rect(0, 0, width, height))
    canvas = Canvas(width, height)
    opened.render(canvas)
    return ["".join(cell.character or " " for cell in row) for row in canvas.cells]


def _centres(opened: HubPage) -> dict[str, tuple[float, float]]:
    return {key: (left + w / 2, top + 1.5) for key, (left, top, w) in opened._picture.boxes.items()}


def test_an_arrow_goes_to_the_nearest_node_that_way_and_the_first_one_selects_the_readers_own():
    nodes, links = crowd_nodes(9)
    opened = HubPage(data(nodes=nodes, links=links), on_close=lambda: None)
    _rendered(opened, 160, 40)
    centres = _centres(opened)
    assert len(centres) == 9

    opened.capture_event(_key("right"), None)
    assert opened.selected == "me", "nothing was selected, so the first arrow selects the reader's own"

    moved = 0
    for arrow, ahead in (
        ("right", lambda here, there: there[0] > here[0]),
        ("left", lambda here, there: there[0] < here[0]),
        ("down", lambda here, there: there[1] > here[1]),
        ("up", lambda here, there: there[1] < here[1]),
    ):
        for start in centres:
            opened.selected = start
            opened.capture_event(_key(arrow), None)
            if opened.selected != start:
                moved += 1
                assert ahead(centres[start], centres[opened.selected]), f"{arrow} from {start} went the wrong way"
    assert moved >= 12, "most nodes have a neighbour in most directions"


def test_an_arrow_with_nothing_that_way_stays_put():
    nodes, links = crowd_nodes(5)
    opened = HubPage(data(nodes=nodes, links=links), on_close=lambda: None)
    _rendered(opened, 160, 40)
    centres = _centres(opened)
    leftmost = min(centres, key=lambda key: centres[key][0])
    opened.selected = leftmost

    opened.capture_event(_key("left"), None)

    assert opened.selected == leftmost


def test_only_tab_and_shift_tab_change_tab_and_the_sideways_arrows_stay_on_the_graph():
    opened = HubPage(_graph_data(), on_close=lambda: None)
    _rendered(opened, 110, 32)

    opened.capture_event(_key("right"), None)
    opened.capture_event(_key("left"), None)
    assert opened.tab == GRAPH

    opened._show(SESSIONS)
    opened.capture_event(_key("right"), None)
    opened.capture_event(_key("left"), None)
    assert opened.tab == SESSIONS, "on a list the sideways arrows do not change tab either"


def test_escape_deselects_a_node_and_only_then_closes():
    closed: list[bool] = []
    opened = HubPage(_graph_data(), on_close=lambda: closed.append(True))
    _rendered(opened, 110, 32)
    opened.capture_event(_key("down"), None)
    assert opened.selected is not None and "esc deselect" in opened.footer

    opened.capture_event(_key("escape"), None)
    assert opened.selected is None and closed == [] and "esc close" in opened.footer

    opened.capture_event(_key("escape"), None)
    assert closed == [True]


def test_selection_is_dropped_when_a_new_reading_no_longer_draws_the_node():
    opened = HubPage(_graph_data(), on_close=lambda: None)
    _rendered(opened, 110, 32)
    opened.selected = "b"

    opened.set_data(data(nodes=(Node("me", "main", "idle", me=True),), links=()))
    _rendered(opened, 110, 32)

    assert opened.selected is None


def test_the_graph_tab_draws_the_summary_the_legend_and_a_picture():
    opened = HubPage(_graph_data(), on_close=lambda: None)

    rows = _rendered(opened, 110, 32)
    text = "\n".join(rows)

    assert "Hub" in rows[1] and "Graph" in rows[1]
    assert "3 nodes" in rows[2] and "58 messages" in rows[2]
    assert "main (you)" in text and "review" in text and "docs" in text
    assert "n = messages" in rows[-2] and "stopped" in rows[-2]
    assert "arrows move to the nearest node" in rows[-1]


def test_selecting_a_node_says_what_it_is_part_of():
    opened = HubPage(_graph_data(), on_close=lambda: None)
    _rendered(opened, 110, 32)
    opened.selected = "a"

    row = _rendered(opened, 110, 32)[2]

    assert "review" in row and "2 lines" in row and "58 messages" in row


@pytest.mark.parametrize(
    "size", [(110, 32), (80, 24), (60, 20), (60, 12), (60, 9), (60, 8), (60, 5), (60, 4), (30, 8), (24, 4), (10, 3)]
)
def test_the_page_renders_at_any_size_and_keeps_its_tab_line_and_footer(size):
    width, height = size
    opened = HubPage(_graph_data(), on_close=lambda: None)
    opened.note("started abcdef12")

    rows = _rendered(opened, width, height)

    if height >= 5:
        assert rows[1].split()[:2] == ["Hub", "Graph"] or width < 20, "nothing is written over the tab line"
        assert rows[-1].lstrip().startswith("arrows") or width < 20
    if height >= 6 and width >= 40:
        assert rows[2].lstrip().startswith("3 nodes"), "nor over the summary"
    if height >= 17 and width >= 44:
        assert "n = messages" in rows[-2], "the legend is its own row, never over the tab line"
    if height < 17 or width < 44:
        assert "n = messages" not in "\n".join(rows), "no legend where no picture is drawn to explain"
    for row in rows[:3]:
        assert "too small" not in row, "the note about the size has a row of its own, below the chrome"


def test_a_page_too_small_for_the_picture_says_so_instead_of_drawing_boxes_over_each_other():
    rows = _rendered(HubPage(_graph_data(), on_close=lambda: None), 30, 12)

    assert "too small for the graph" in "\n".join(rows)
    assert "╭" not in "\n".join(rows)


def test_a_window_too_small_for_the_picture_forgets_the_selection_so_no_arrow_moves_an_unseen_node():
    opened = HubPage(_graph_data(), on_close=lambda: None)
    _rendered(opened, 110, 32)
    opened.capture_event(_key("right"), None)
    assert opened.selected == "me"

    rows = _rendered(opened, 30, 12)

    assert opened.selected is None and not opened._picture.nodes
    assert "·" not in rows[2] or "main" not in rows[2], "the summary does not describe a selected node"
    opened.capture_event(_key("right"), None)
    assert opened.selected is None, "an arrow has nothing to move"
    assert "esc deselect" not in opened.footer and "esc close" in opened.footer, "the footer says what Esc does now"


def test_the_empty_picture_says_whether_there_was_nothing_or_the_read_failed():
    assert "no session has talked" in "\n".join(_rendered(HubPage(HubData(), on_close=lambda: None), 80, 24))
    failed = HubData(graph_ok=False)
    assert "cannot be read" in "\n".join(_rendered(HubPage(failed, on_close=lambda: None), 80, 24))


def test_a_note_does_not_hide_the_summary_on_the_graph_tab():
    opened = HubPage(_graph_data(), on_close=lambda: None)
    opened.note("started abcdef12")

    rows = _rendered(opened, 110, 32)

    assert "3 nodes" in rows[2] and "started abcdef12" in rows[3]


# -- the reading ------------------------------------------------------------------------------------


class _Info:
    def __init__(self, name: str) -> None:
        self.id = name
        self.title = "" if name.startswith("old") else name


class _FakeSessions:
    """The store as the page reads it: a few records, the reader's own among them."""

    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list(self, *, limit: int | None = None) -> list[object]:
        return [_Info(name) for name in self._ids]


class _FakeClient:
    """The slice of the SDK the reading uses."""

    def __init__(self, workspace: Path, graph: dict[str, object] | Exception | None = None) -> None:
        self.session = type("Session", (), {"id": "self-1"})()
        self.sessions = _FakeSessions(["self-1", "p-1", "old-9", "run-1"])
        self.workspace = workspace
        self._graph = graph if graph is not None else {"sessions": [], "edges": []}

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

    async def traffic_graph(self) -> dict[str, object]:
        if isinstance(self._graph, Exception):
            raise self._graph
        return self._graph


def _daemon_info(session_id: str, status: str, workspace: str, name: str = "") -> object:
    return type(
        "Info",
        (),
        {"session_id": session_id, "status": status, "workspace": workspace, "name": name, "title": "", "model": "m"},
    )()


@pytest.fixture
def daemons_on_disk(monkeypatch, tmp_path):
    """The machine's daemon records: one running here, one dead here, one dead in another project."""
    from zettcode.sdk import daemons

    here = str(tmp_path)
    records = [
        _daemon_info("run-1", "idle", here, "runner"),
        _daemon_info("dead-1", "dead", here, "worker"),
        _daemon_info("dead-9", "dead", "/some/other/project", "elsewhere"),
    ]
    monkeypatch.setattr(daemons, "list_daemons", lambda: records)
    return records


def _read(client: _FakeClient) -> HubData:
    return asyncio.run(HubCommand()._read(client))


def test_the_reading_lists_only_the_stored_sessions_that_nothing_is_running(tmp_path, daemons_on_disk):
    """Not the reader's own, not a registered peer, and not one a live daemon holds."""
    reading = _read(_FakeClient(tmp_path))

    assert [(s.session_id, s.title) for s in reading.offline] == [("old-9", "old-9")]
    assert reading.peers[0].session_id == "p-1"


def test_a_session_in_the_brokers_roster_is_present_even_when_the_cached_peers_do_not_have_it(
    tmp_path, daemons_on_disk
):
    graph = {"sessions": [{"session_id": "old-9", "handle": "old", "status": "idle"}], "edges": []}

    reading = _read(_FakeClient(tmp_path, graph))

    assert reading.offline == (), "the broker's own roster decides who is present"


def test_the_graph_becomes_nodes_and_links_with_the_reader_in_it(tmp_path, daemons_on_disk):
    graph = {
        "sessions": [
            {"session_id": "self-1", "handle": "main", "status": "working"},
            {"session_id": "p-1", "handle": "parser", "status": "idle"},
        ],
        "edges": [{"a": "p-1", "b": "self-1", "count": 7}, {"a": "p-1", "b": "old-9", "count": 2}],
    }

    reading = _read(_FakeClient(tmp_path, graph))

    assert {node.key: (node.label, node.state, node.me) for node in reading.nodes} == {
        "self-1": ("main", "working", True),
        "p-1": ("parser", "idle", False),
        "old-9": ("old-9", "offline", False),
        "dead-1": ("worker", "stopped", False),
    }
    assert [(link.a, link.b, link.count) for link in reading.links] == [("p-1", "self-1", 7), ("p-1", "old-9", 2)]
    assert reading.graph_ok


def test_only_this_workspaces_dead_daemons_are_in_the_picture_and_a_title_beats_a_daemons_name(
    tmp_path, daemons_on_disk
):
    graph = {"sessions": [], "edges": [{"a": "dead-1", "b": "dead-9", "count": 1}]}
    client = _FakeClient(tmp_path, graph)
    client.sessions = _FakeSessions(["dead-1"])
    client.sessions.list = _titled  # type: ignore[method-assign]

    reading = _read(client)

    states = {node.key: (node.label, node.state) for node in reading.nodes}
    assert states["dead-1"] == ("the stored title", "stopped"), "the session's title wins over the daemon's name"
    assert states["dead-9"][1] == "offline", "another project's dead daemon is not drawn as ours"
    assert [daemon.session_id for daemon in reading.daemons] == ["run-1", "dead-1", "dead-9"], "the list shows all"


async def _titled(*, limit: int | None = None) -> list[object]:
    info = _Info("dead-1")
    info.title = "the stored title"
    return [info]


def test_a_graph_that_cannot_be_read_leaves_the_lists_and_says_why(tmp_path, daemons_on_disk):
    reading = _read(_FakeClient(tmp_path, RuntimeError("no broker")))

    assert not reading.graph_ok and reading.nodes == () and reading.links == (), "no lone stopped box"
    assert reading.note.startswith("the message graph cannot be read") and "no broker" in reading.note
    assert reading.peers, "the roster is still there"


def test_a_client_with_no_current_session_still_shows_the_roster(tmp_path, daemons_on_disk):
    client = _FakeClient(tmp_path)
    del client.session

    reading = _read(client)

    assert reading.peers and all(not node.me for node in reading.nodes)


# -- resuming ---------------------------------------------------------------------------------------


def _fake_spawn(monkeypatch, calls, release=None):
    from zettcode.sdk import daemons

    async def spawn(workspace, **kwargs):
        calls.append((workspace, kwargs))
        if release is not None:
            await release.wait()
        return type("Info", (), {"session_id": "abcdef123456"})()

    async def read(self, client):
        return data()

    monkeypatch.setattr(daemons, "spawn_daemon", spawn)
    monkeypatch.setattr(HubCommand, "_read", read)


def _stopped(**changes: object) -> HubPage:
    """A page whose one daemon is dead: the thing Enter starts."""
    return page(daemons=(Daemon("d-2", "gone", "dead", model="m", workspace="/work"),), **changes)


def test_starting_a_dead_daemon_resumes_its_session_on_the_workspace_and_model_it_had(monkeypatch, tmp_path):
    calls: list[tuple[object, dict[str, object]]] = []
    _fake_spawn(monkeypatch, calls)
    client = type("Client", (), {"workspace": tmp_path / "project"})()
    opened = _stopped()

    asyncio.run(HubCommand()._resume(opened, client, "d-2"))
    asyncio.run(HubCommand()._resume(opened, client, "nobody"))

    assert calls == [("/work", {"model": "m", "resume": "d-2"})], "its own workspace and model, nothing else"
    assert opened.subtitle == "started abcdef12"


def test_a_daemon_with_no_recorded_workspace_resumes_in_the_clients(monkeypatch, tmp_path):
    calls: list[tuple[object, dict[str, object]]] = []
    _fake_spawn(monkeypatch, calls)
    client = type("Client", (), {"workspace": tmp_path / "project"})()
    opened = page(daemons=(Daemon("d-2", "gone", "dead"),))

    asyncio.run(HubCommand()._resume(opened, client, "d-2"))

    assert calls == [(str(tmp_path / "project"), {"model": None, "resume": "d-2"})]


def test_a_stored_session_is_not_something_resume_accepts(monkeypatch, tmp_path):
    calls: list[tuple[object, dict[str, object]]] = []
    _fake_spawn(monkeypatch, calls)
    client = type("Client", (), {"workspace": tmp_path})()

    asyncio.run(HubCommand()._resume(page(), client, "old-id"))

    assert calls == [], "old-id is on disk with no daemon record, so there is nothing to start"


def test_a_second_enter_while_the_page_is_still_being_read_again_is_told_so_and_starts_nothing(monkeypatch, tmp_path):
    """The window after the spawn: the daemon is up but the page still lists it as dead until the read is done."""
    calls: list[tuple[object, dict[str, object]]] = []
    client = type("Client", (), {"workspace": tmp_path})()

    async def scenario() -> list[str]:
        _fake_spawn(monkeypatch, calls)
        reading = asyncio.Event()

        async def slow_read(self, client):
            await reading.wait()
            return data()

        monkeypatch.setattr(HubCommand, "_read", slow_read)
        command, opened = HubCommand(), _stopped()
        first = asyncio.ensure_future(command._resume(opened, client, "d-2"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(calls) == 1, "the spawn is done and the read is being waited for"
        await command._resume(opened, client, "d-2")
        said = [opened.subtitle or ""]
        reading.set()
        await first
        assert not command._starting, "the id is forgotten once the page shows the result"
        return said

    assert asyncio.run(scenario()) == ["already starting that one"]
    assert len(calls) == 1


def test_a_client_with_no_workspace_still_shows_the_roster(tmp_path, daemons_on_disk):
    client = _FakeClient(tmp_path)
    del client.workspace

    reading = _read(client)

    assert reading.peers


def test_a_second_enter_while_the_first_is_starting_is_told_so_and_starts_nothing(monkeypatch, tmp_path):
    calls: list[tuple[object, dict[str, object]]] = []
    client = type("Client", (), {"workspace": tmp_path})()

    async def scenario() -> list[str]:
        release = asyncio.Event()
        _fake_spawn(monkeypatch, calls, release)
        command, opened = HubCommand(), _stopped()
        first = asyncio.ensure_future(command._resume(opened, client, "d-2"))
        await asyncio.sleep(0)
        await command._resume(opened, client, "d-2")
        said = [opened.subtitle or ""]
        release.set()
        await first
        assert not command._starting, "the id is forgotten once the start has finished"
        return said

    assert asyncio.run(scenario()) == ["already starting that one"]
    assert len(calls) == 1


def test_a_daemon_that_is_running_is_not_started_again(monkeypatch, tmp_path):
    calls: list[tuple[object, dict[str, object]]] = []
    _fake_spawn(monkeypatch, calls)
    client = type("Client", (), {"workspace": tmp_path})()
    opened = page(daemons=(Daemon("d-1", "watcher", "idle", workspace="/work"),))

    asyncio.run(HubCommand()._resume(opened, client, "d-1"))

    assert calls == [] and "running" in (opened.subtitle or "")


def test_every_key_that_acts_says_so_on_the_page_at_once():
    asked: list[str] = []
    opened = HubPage(
        data(daemons=(Daemon("d-1", "watcher", "idle"), Daemon("d-2", "gone", "dead"))),
        on_close=lambda: None,
        on_refresh=lambda: asked.append("r"),
        on_stop=lambda session_id: asked.append(f"s {session_id}"),
        on_start=lambda session_id: asked.append(f"enter {session_id}"),
    )

    opened.capture_event(_key("r"), None)
    assert opened.subtitle == "refreshing\u2026"

    opened._show(DAEMONS)
    opened.capture_event(_key("s"), None)
    assert opened.subtitle == "stopping\u2026"

    opened.list.selected = 0
    opened.capture_event(_key("enter"), None)
    assert "is running" in opened.subtitle and "enter" not in " ".join(asked), "a live daemon is not restarted"

    opened.list.selected = 1
    opened.capture_event(_key("enter"), None)
    assert opened.subtitle == "starting\u2026"
    assert asked == ["r", "s d-1", "enter d-2"]


STEPS = (("peers", 0), ("daemons", 3), ("sessions", 1), ("graph", 19), ("picture", 0))


def test_a_refresh_replaces_refreshing_with_the_new_readings_time_and_keeps_a_failure(monkeypatch):
    async def read_ok(self, client):
        return data(began="12:34:56", took=23, steps=STEPS)

    async def read_bad(self, client):
        return data(note="the message graph cannot be read: no broker")

    opened = page()
    opened.note("refreshing\u2026")

    monkeypatch.setattr(HubCommand, "_read", read_ok)
    asyncio.run(HubCommand()._reload(opened, object()))
    assert opened.subtitle is None, "refreshing is gone once the read is done"
    assert "read 12:34:56 \u00b7 23 ms" in _rendered(opened, 110, 32)[1], "and the time is at the top right"

    monkeypatch.setattr(HubCommand, "_read", read_bad)
    asyncio.run(HubCommand()._reload(opened, object()))
    assert opened.subtitle == "the message graph cannot be read: no broker"


def test_the_stamp_is_the_fullest_account_that_fits_and_an_80_column_page_shows_where_the_time_went():
    opened = HubPage(data(began="12:34:56", took=23, steps=STEPS), on_close=lambda: None)

    def tab_line(width: int) -> str:
        return _rendered(opened, width, 32)[1].rstrip()

    full = tab_line(130)
    assert full.endswith("graph 19, picture 0 ms)") and "peers 0" in full, "with the unit after the steps"
    assert "12:34:56" in full and full.index("read") > full.index("Daemons")
    assert tab_line(86).endswith("read 12:34:56 \u00b7 23 ms (p0 d3 s1 g19 pic0)"), "initials where names do not fit"
    assert tab_line(80).endswith("read 23 ms (p0 d3 s1 g19 pic0)"), "an 80-column page sees the steps, not the clock"
    assert tab_line(66).endswith("read 12:34:56 \u00b7 23 ms"), "narrower: the clock and the total"
    assert tab_line(55).endswith("read 23 ms"), "narrower still: the total alone"
    assert "read" not in tab_line(44) and "Daemons" in tab_line(44), "too narrow for any: left out, not cut"


def test_a_page_drops_steps_it_has_no_letter_for_to_three_characters_and_a_total_without_steps_is_still_shown():
    from zettcode.commands.hub import STEP_LETTERS

    opened = HubPage(data(began="12:34:56", took=9, steps=(("tail", 4), ("peers", 5))), on_close=lambda: None)

    assert "tail" not in STEP_LETTERS
    assert _rendered(opened, 70, 32)[1].rstrip().endswith("read 9 ms (tai4 p5)")
    assert _rendered(HubPage(data(took=9), on_close=lambda: None), 80, 32)[1].rstrip().endswith("read 9 ms")


def test_a_real_reading_says_when_it_began_and_where_the_time_went_and_the_steps_add_up(tmp_path, daemons_on_disk):
    reading = _read(_FakeClient(tmp_path))

    assert [name for name, _ in reading.steps] == ["peers", "daemons", "sessions", "graph", "picture"]
    assert len(reading.began) == 8 and reading.began.count(":") == 2
    assert abs(sum(ms for _, ms in reading.steps) - reading.took) <= len(reading.steps), "no part of it is untimed"


def test_a_slow_roster_is_blamed_on_the_roster_not_on_the_daemons(tmp_path, daemons_on_disk):
    import time

    client = _FakeClient(tmp_path)
    cached = client.peers

    def slow() -> list[object]:
        time.sleep(0.06)
        return cached()

    client.peers = slow  # type: ignore[method-assign]

    reading = _read(client)

    steps = dict(reading.steps)
    assert steps["peers"] >= 55 and steps["peers"] > steps["daemons"], steps


def test_the_tables_have_titles_lined_up_with_their_columns():
    opened = HubPage(
        data(
            peers=(Peer("main", "the parser", "working", "/work"), Peer("a-longer-handle", "t", "idle", "/elsewhere")),
            daemons=(Daemon("d-1", "watcher", "idle", model="the-model", workspace="/work"),),
        ),
        on_close=lambda: None,
    )

    opened._show(SESSIONS)
    rows = _rendered(opened, 110, 24)
    head, first = rows[3], rows[4]
    assert head.split() == ["NAME", "STATE", "TITLE", "WORKSPACE"]
    assert head.index("STATE") == first.index("\u25cf"), "STATE sits over the dot"
    assert head.index("TITLE") == first.index("the parser")
    assert head.index("WORKSPACE") == first.index("/work")
    assert head.index("NAME") == first.index("main")

    opened._show(DAEMONS)
    rows = _rendered(opened, 110, 24)
    assert rows[3].split() == ["NAME", "STATE", "MODEL", "WORKSPACE"]
    assert rows[3].index("MODEL") == rows[4].index("the-model")


def test_a_note_does_not_overwrite_the_titles_and_the_graph_has_none():
    opened = page()
    opened.note("started abcdef12")
    opened._show(SESSIONS)

    rows = _rendered(opened, 110, 24)

    assert "started abcdef12" in rows[2] and "NAME" in rows[3]
    opened._show(GRAPH)
    assert "NAME" not in "\n".join(_rendered(opened, 110, 24))


def test_a_daemon_status_is_written_once_inside_the_state_column():
    opened = HubPage(
        data(daemons=(Daemon("a", "live", "working"), Daemon("b", "gone", "dead"), Daemon("c", "new", "starting"))),
        on_close=lambda: None,
    )
    opened._show(DAEMONS)

    said = [item.description for item in opened.list.items]

    assert said[0].count("working") == 1
    assert "stopped (dead)" in said[1], "a dead process keeps the word that explains the red"
    assert "idle (starting)" in said[2]


# -- a change that arrives from a task must reach the screen ------------------------------------------


def _mounted() -> tuple[HubPage, object]:
    from zettcode.tui.testing import Harness

    opened = HubPage(_graph_data(), on_close=lambda: None)
    harness = Harness(opened, width=110, height=32)
    harness.render()
    harness.app.scheduler.poll()  # the frame that was just drawn: nothing is pending now
    assert not harness.app.scheduler.pending
    return opened, harness


def test_a_note_written_by_a_task_asks_for_a_frame_or_it_stays_on_screen_until_the_next_key():
    """The bug: `r` showed "refreshing…", the read finished in 10 ms, and the screen kept the old line, because a task
    that changes the page is not an input event and nothing asked the loop for another frame."""
    opened, harness = _mounted()
    assert "refreshing" not in harness.text()

    opened.note("refreshing\u2026")  # what `r` writes, in the key handler

    assert harness.app.scheduler.pending, "the page asked the app for a frame"
    assert "refreshing\u2026" in harness.text()
    harness.app.scheduler.poll()

    opened.set_data(data())  # what the task writes when the read is done, with no key involved

    assert harness.app.scheduler.pending, "and again when the task finished, or the line above would stay"
    assert "refreshing" not in harness.text(), "the next frame no longer has it"


def test_a_reading_that_arrives_from_a_task_asks_for_a_frame():
    opened, harness = _mounted()

    opened.set_data(data(note="", nodes=(), links=()))

    assert harness.app.scheduler.pending


def test_the_page_off_screen_or_not_yet_mounted_can_still_be_changed_without_an_app():
    opened = page()

    opened.note("a note")
    opened.set_data(data())

    assert opened.app is None and opened.subtitle is None
