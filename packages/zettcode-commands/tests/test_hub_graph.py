"""`/hub`'s picture: what becomes a node, which nodes are kept and where, where lines run, and what is painted."""

from __future__ import annotations

import pytest

from zettcode.commands import hub_graph as graph
from zettcode.tui import Canvas, Theme

WIRE = {
    "sessions": [
        {"session_id": "me", "handle": "main", "status": "working", "kind": "zettcode"},
        {"session_id": "a", "handle": "review", "status": "idle", "kind": "zettcode"},
        {"session_id": "b", "handle": "ci-bot", "status": "idle", "kind": "external"},
    ],
    "edges": [
        {"a": "me", "b": "a", "count": 55},
        {"a": "a", "b": "gone", "count": 2},
        {"a": "me", "b": "me", "count": 9},
    ],
}


def crowd(count: int, *, hub: str = "0", me: str = "0"):
    """``count`` sessions that all talk to ``hub``, a few of them to each other too."""
    sessions = [{"session_id": str(i), "handle": f"session-{i}", "status": "idle"} for i in range(count)]
    edges = [{"a": hub, "b": str(i), "count": i + 1} for i in range(count) if str(i) != hub]
    edges += [{"a": str(i), "b": str(i + 1), "count": 3} for i in range(1, count - 1, 3)]
    return graph.build({"sessions": sessions, "edges": edges}, me=me)


def text_of(canvas: Canvas) -> str:
    return "\n".join("".join(cell.character for cell in row) for row in canvas.cells)


# -- the data ---------------------------------------------------------------------------------------


def test_every_state_is_told_apart_and_an_unknown_end_of_a_line_is_a_node_of_its_own():
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"}, stopped=["dead-1"])

    assert {node.key: node.state for node in nodes} == {
        "me": "working",
        "a": "idle",
        "b": "external",
        "gone": "offline",
    }
    assert [node.label for node in nodes if node.key == "gone"] == ["old one"]
    assert next(node for node in nodes if node.me).key == "me"
    assert [(link.a, link.b) for link in links] == [("me", "a"), ("a", "gone")], "a line to itself is dropped"


def test_a_daemon_whose_process_is_gone_is_stopped_even_with_no_messages():
    nodes, _ = graph.build({}, titles={"d-1": "watcher"}, stopped=["d-1"])

    assert [(node.label, node.state) for node in nodes] == [("watcher", "stopped")]


def test_every_state_has_its_own_colour_and_they_come_from_the_theme():
    theme = Theme()
    colours = graph.colours(theme)

    assert set(colours) == set(graph.STATES)
    assert len(set(colours.values())) == len(graph.STATES), "no two states share a colour"
    assert colours["working"] == theme.accent and colours["stopped"] == theme.error


# -- which nodes, and where -------------------------------------------------------------------------


def test_the_busiest_are_kept_and_the_readers_own_session_is_never_the_one_cut():
    nodes, links = crowd(40, hub="5", me="39")

    picture = graph.layout(nodes, links, 110, 32)

    assert picture.nodes[0].me, "the reader's own is first and in the picture"
    assert 0 < len(picture.nodes) <= graph.MAX_NODES
    assert picture.hidden_nodes == len(nodes) - len(picture.nodes)
    quiet = {node.key for node in nodes} - {node.key for node in picture.nodes}
    busy = {link.a for link in links} | {link.b for link in links}
    totals = graph._totals(links)
    kept = [totals.get(node.key, 0) for node in picture.nodes[1:]]
    cut = [totals.get(key, 0) for key in quiet]
    assert min(kept) >= max(cut), f"every node kept talks at least as much as any left out ({busy and 'ok'})"


@pytest.mark.parametrize("size", [(20, 5), (40, 10), (76, 17), (56, 13), (110, 32), (200, 50)])
@pytest.mark.parametrize("count", [3, 8, 16, 30])
def test_boxes_never_touch_and_stay_inside_the_area_at_any_size(size, count):
    width, height = size
    nodes, links = crowd(count)

    picture = graph.layout(nodes, links, width, height)

    boxes = list(picture.boxes.values())
    for left, top, w in boxes:
        assert 1 <= left and left + w <= width - 1 and 1 <= top and top + graph.BOX_HEIGHT <= height - 1
    for index, (al, at, aw) in enumerate(boxes):
        for bl, bt, bw in boxes[index + 1 :]:
            apart = al + aw < bl or bl + bw < al or at + graph.BOX_HEIGHT < bt or bt + graph.BOX_HEIGHT < at
            assert apart, "at least one free cell between any two boxes"
    assert len(picture.nodes) + picture.hidden_nodes == len(nodes)


def test_two_nodes_with_long_names_in_a_narrow_area_do_not_touch():
    nodes, links = graph.build(
        {
            "sessions": [
                {"session_id": "me", "handle": "a-very-long-handle", "status": "idle"},
                {"session_id": "b", "handle": "another-long-handle", "status": "idle"},
            ],
            "edges": [{"a": "me", "b": "b", "count": 7}],
        },
        me="me",
    )

    for width in (30, 40, 56, 80):
        picture = graph.layout(nodes, links, width, 12)
        assert len(picture.nodes) in (1, 2)
        if len(picture.nodes) == 2:
            (al, _, aw), (bl, _, bw) = picture.boxes.values()
            assert al + aw < bl or bl + bw < al


# -- the lines --------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(110, 32), (80, 24), (60, 20)])
def test_a_line_never_runs_through_a_box_and_ends_at_the_two_it_joins(size):
    nodes, links = crowd(10)
    picture = graph.layout(nodes, links, *size)

    inside = {
        (x, y)
        for key, (left, top, w) in picture.boxes.items()
        for x in range(left, left + w)
        for y in range(top, top + graph.BOX_HEIGHT)
    }
    assert picture.routes, "something is drawn"
    for route in picture.routes:
        assert not inside & set(route.cells), "no cell of a line is inside any box"
        for cell, other in zip(route.cells, route.cells[1:], strict=False):
            assert abs(cell[0] - other[0]) + abs(cell[1] - other[1]) == 1, "unit steps, right angles"
        for end in (route.cells[0], route.cells[-1]):
            touching = [
                key
                for key, (left, top, w) in picture.boxes.items()
                if (left - 1 <= end[0] <= left + w and top <= end[1] < top + graph.BOX_HEIGHT)
                or (left <= end[0] < left + w and top - 1 <= end[1] <= top + graph.BOX_HEIGHT)
            ]
            assert set(touching) & {route.link.a, route.link.b}, "a line ends beside one of its own boxes"


def test_a_line_is_numbered_at_the_end_that_is_not_the_reader_and_the_numbers_do_not_overlap():
    nodes, links = crowd(12)
    picture = graph.layout(nodes, links, 110, 32)
    me = next(node.key for node in nodes if node.me)

    written: set[tuple[int, int]] = set()
    for left, top, text, index in picture.labels:
        cells = {(left + i, top) for i in range(len(text))}
        assert not written & cells, "two numbers are never on the same cells"
        written |= cells
        route = picture.routes[index]
        assert text.strip() == str(route.link.count)
        if me in (route.link.a, route.link.b):
            assert route.origin != me, "a line to the reader is numbered at the other end"
        first = route.cells[0]
        assert abs(left - first[0]) + abs(top - first[1]) <= 14, "the number sits near the end it belongs to"
    assert len(picture.labels) >= len(picture.routes) // 2


def test_the_route_with_most_messages_is_routed_first():
    nodes, links = crowd(8)
    picture = graph.layout(nodes, links, 110, 32)

    counts = [route.link.count for route in picture.routes]
    assert counts == sorted(counts, reverse=True)


# -- painting ---------------------------------------------------------------------------------------


def painted(picture, selected=None, size=(110, 32)):
    canvas = Canvas(*size)
    graph.paint(canvas, Theme(), 0, 0, picture, selected)
    return canvas


def test_a_line_is_drawn_in_the_colour_of_the_end_it_is_numbered_at():
    theme = Theme()
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"})
    picture = graph.layout(nodes, links, 110, 32)
    canvas = painted(picture)

    by_key = {node.key: node for node in nodes}
    for route in picture.routes:
        x, y = route.cells[len(route.cells) // 2]
        cell = canvas.cells[y][x]
        if len(picture.cells[(x, y)]) == 1:
            assert cell.style.foreground == graph.colours(theme)[by_key[route.origin].state]
    text = text_of(canvas)
    assert "main (you)" in text and "review" in text and "ci-bot" in text or "ci-bot" not in text
    assert "55" in text, "the count is written beside its line"
    assert any(char in "\u2500\u2502\u256d\u256e\u256f\u2570" for char in text)
    assert not any(0x2800 <= ord(char) < 0x2900 for char in text), "no braille: a font draws it as loose dots"


def test_selecting_a_node_keeps_its_lines_and_dims_the_others():
    theme = Theme()
    nodes, links = crowd(8)
    picture = graph.layout(nodes, links, 110, 32)
    chosen = picture.nodes[1].key
    lit = [route for route in picture.routes if chosen in (route.link.a, route.link.b)]
    other = [route for route in picture.routes if chosen not in (route.link.a, route.link.b)]
    assert lit and other

    normal, selected = painted(picture), painted(picture, chosen)

    def only(route):
        return next(c for c in route.cells[1:-1] if len(picture.cells[c]) == 1)

    x, y = only(lit[0])
    assert selected.cells[y][x].style.foreground == normal.cells[y][x].style.foreground, "its lines are unchanged"
    x, y = only(other[0])
    assert selected.cells[y][x].style.foreground == theme.border, "the rest are dimmed"
    assert normal.cells[y][x].style.foreground != theme.border


def test_a_label_wider_than_its_box_is_cut_by_columns_not_characters():
    nodes, links = graph.build(
        {
            "sessions": [
                {"session_id": "me", "handle": "主会话", "status": "idle"},
                {"session_id": "b", "handle": "评审机器人评审机器人评审机器人", "status": "idle"},
            ],
            "edges": [{"a": "me", "b": "b", "count": 4}],
        },
        me="me",
    )
    picture = graph.layout(nodes, links, 110, 12)
    canvas = painted(picture, size=(110, 12))

    text = text_of(canvas)
    assert "主会话 (you)" in text, "a short wide label shows whole"
    left, top, w = picture.boxes["b"]
    assert w == graph.MAX_BOX
    assert "\u2026" in text, "a long one is cut with an ellipsis the reader can see"
    row = canvas.cells[top + 1]
    assert row[left + w - 1].character == "\u2502", "and never runs through the box's side"


def test_the_summary_says_what_the_graph_holds_and_what_a_selected_node_is_part_of():
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"})
    picture = graph.layout(nodes, links, 110, 32)

    overall = graph.summary(nodes, links, picture)
    chosen = graph.summary(nodes, links, picture, "a")

    assert "4 nodes" in overall and "1 working" in overall and "57 messages" in overall
    assert "review" in chosen and "2 lines" in chosen and "57 messages" in chosen
    many, many_links = crowd(40)
    assert "quieter not drawn" in graph.summary(many, many_links, graph.layout(many, many_links, 110, 32))


def test_the_legend_names_every_state_with_its_own_colour_and_starts_with_what_a_number_means():
    pieces = [piece for group in graph.legend(Theme()) for piece in group]
    text = "".join(piece for piece, _ in pieces)

    assert text.startswith("n = messages")
    for state in graph.STATES:
        assert state in text
    colours = [style.foreground for piece, style in pieces if piece.startswith(("\u25cf", "\u25c7"))]
    assert len(set(colours)) == len(graph.STATES)


def test_the_lists_colour_a_state_the_way_the_graph_does():
    from zettcode.commands.hub import SESSIONS, Daemon, HubData, HubPage, Peer, StoredSession

    theme = Theme()
    states = graph.colours(theme)
    page = HubPage(
        HubData(
            peers=(
                Peer("a", "t", "working", "/w"),
                Peer("b", "t", "idle", "/w"),
                Peer("c", "t", "idle", "/w", "external"),
            ),
            daemons=(Daemon("d", "dead one", "dead"), Daemon("e", "live", "working")),
            offline=(StoredSession("o", "old"),),
        ),
        on_close=lambda: None,
    )

    def head(item):
        first = item.parts(theme)[0]
        assert "".join(text for text, _ in item.parts(theme)) == item.description
        return first[1]

    page._show(SESSIONS)
    assert [head(item) for item in page.list.items] == [
        states["working"],
        states["idle"],
        states["external"],
        states["offline"],
    ]
    page._show(SESSIONS + 1)
    assert [head(item) for item in page.list.items] == [states["stopped"], states["working"]]
