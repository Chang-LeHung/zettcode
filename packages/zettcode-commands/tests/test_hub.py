"""`/hub`: the three tabs, the mark kept per tab, and the two keys that act on a daemon."""

from __future__ import annotations

import dataclasses

from zettcode.commands.hub import TABS, Daemon, Edge, HubData, HubPage, Peer


def data(**changes: object) -> HubData:
    """A reading with one session, one daemon and one exchange."""
    base = HubData(
        peers=(Peer("main", "the parser", "working", "/work"),),
        daemons=(Daemon("d-1", "watcher", "running", model="m", workspace="/work"),),
        offline=("old",),
        edges=(Edge("main", "bob", 7),),
        recent=("main \u2192 bob: hello",),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def page(**changes: object) -> HubPage:
    """A page over :func:`data`, with its actions recorded."""
    return HubPage(data(**changes), on_close=lambda: None)


def test_the_page_opens_on_the_sessions_tab_with_the_roster_and_the_offline_ones():
    opened = page()

    assert "Sessions" in opened.title and "[Sessions]" in opened.title
    labels = [item.label for item in opened.list.items]
    assert labels == ["main", "old"]
    assert "on disk" in opened.list.items[1].description


def test_tab_walks_the_three_and_keeps_a_mark_per_tab():
    opened = page()
    opened.list.selected = 1

    keys = [opened.capture_event(_key("tab"), None) for _ in range(1)]
    assert keys == [True]
    assert opened.tab == 1 and "Daemons" in opened.title
    assert [item.label for item in opened.list.items] == ["watcher"]

    opened.capture_event(_key("tab"), None)
    assert opened.tab == 2 and "Graph" in opened.title
    assert opened.list.items[0].label == "main \u2500\u25007\u2500\u2500\u25b6 bob"

    opened.capture_event(_key("tab"), None)
    assert opened.tab == 0 and opened.list.selected == 1, "the sessions mark came back"


def test_shift_tab_walks_backwards():
    opened = page()

    opened.capture_event(_key("backtab"), None)

    assert opened.tab == len(TABS) - 1


def test_stop_and_start_act_on_the_daemon_under_the_mark():
    stopped: list[str] = []
    started: list[str] = []
    opened = HubPage(
        data(daemons=(Daemon("d-1", "watcher", "running", model="m", workspace="/work"),)),
        on_close=lambda: None,
        on_stop=stopped.append,
        on_start=started.append,
    )
    opened._show(1)
    opened.capture_event(_key("s"), None)

    assert stopped == ["d-1"], "s stops the daemon under the mark"

    dead = HubPage(
        data(daemons=(Daemon("d-2", "old", "dead", workspace="/work"),)),
        on_close=lambda: None,
        on_start=started.append,
    )
    dead._show(1)
    dead.capture_event(_key("enter"), None)

    assert started == ["d-2"], "enter starts a stopped one"


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
