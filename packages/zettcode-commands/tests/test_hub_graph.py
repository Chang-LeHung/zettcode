"""`/hub`'s picture: what becomes a node, where it is put, and that the drawing keeps to its rectangle."""

from __future__ import annotations

from zettcode.commands import hub_graph as graph
from zettcode.commands.hub import HubData, HubPage, Stored
from zettcode.tui import Canvas
from zettcode.tui.core.theme import Theme

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


def test_every_state_is_told_apart_and_an_unknown_end_of_a_line_is_a_node_of_its_own():
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"}, stopped=["dead-1"])

    states = {node.key: node.state for node in nodes}
    assert states == {"me": "working", "a": "idle", "b": "external", "gone": "offline"}
    assert [node.label for node in nodes if node.key == "gone"] == ["old one"]
    assert next(node for node in nodes if node.me).key == "me"
    assert [(link.a, link.b) for link in links] == [("me", "a"), ("a", "gone")], "a line to itself is dropped"


def test_a_daemon_whose_process_is_gone_is_stopped_even_with_no_messages():
    nodes, _ = graph.build({}, titles={"d-1": "watcher"}, stopped=["d-1"])

    assert [(node.label, node.state) for node in nodes] == [("watcher", "stopped")]


def test_boxes_do_not_overlap_and_stay_inside_the_area():
    nodes, links = graph.build(
        {
            "sessions": [{"session_id": str(i), "handle": f"session-{i}", "status": "idle"} for i in range(12)],
            "edges": [{"a": "0", "b": str(i), "count": i} for i in range(1, 12)],
        },
        me="0",
    )
    width, height = 100, 28

    spots = graph.place(nodes, links, width, height)

    assert set(spots) == {node.key for node in nodes}
    taken = []
    for node in nodes:
        x, y = spots[node.key]
        half = graph._box(node) // 2
        assert half <= x <= width - half and 1 <= y <= height - 2
        taken.append((x - half, y - 1, x - half + graph._box(node), y + 2))
    for index, one in enumerate(taken):
        for other in taken[index + 1 :]:
            assert one[2] <= other[0] or other[2] <= one[0] or one[3] <= other[1] or other[3] <= one[1]


def test_drawing_paints_lines_boxes_and_counts_and_nothing_outside_the_rectangle():
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"})
    canvas = Canvas(110, 24)

    graph.draw(canvas, Theme(), 5, 2, 100, 20, nodes, links)

    text = "\n".join("".join(cell.character or " " for cell in row) for row in canvas.cells)
    assert "main (you)" in text and "review" in text and "ci-bot" in text and "old one" in text
    assert "55" in text, "the count is written on the line"
    assert any(char in "\u2500\u2502\u256d\u256e\u256f\u2570" for char in text), "lines are box-drawing characters"
    assert not any(0x2800 <= ord(char) < 0x2900 for char in text), "no braille: a font draws it as loose dots"
    assert all(
        cell.character in ("", " ") for cell in canvas.cells[0] + canvas.cells[1] + canvas.cells[22] + canvas.cells[23]
    )
    assert all(row[4].character == " " for row in canvas.cells)


def test_the_legend_names_every_state_with_its_own_colour():
    pieces = graph.legend(Theme())
    text = "".join(piece for piece, _ in pieces)

    for state in graph.STATES:
        assert state in text
    colours = [style.foreground for piece, style in pieces if piece.startswith(("\u25cf", "\u25c7"))]
    assert len(set(colours)) == len(graph.STATES)


def test_an_empty_picture_says_so_and_the_page_renders_at_every_size():
    page = HubPage(HubData(), on_close=lambda: None)
    for width, height in ((120, 40), (30, 8), (10, 3)):
        page.layout(__import__("zettcode.tui", fromlist=["Rect"]).Rect(0, 0, width, height))
        canvas = Canvas(width, height)
        page.render(canvas)

    page.layout(__import__("zettcode.tui", fromlist=["Rect"]).Rect(0, 0, 80, 24))
    canvas = Canvas(80, 24)
    page.render(canvas)
    assert "no session has talked" in "".join(cell.character or " " for row in canvas.cells for cell in row)


def test_the_lists_colour_a_state_the_way_the_graph_does():
    from zettcode.commands.hub import Daemon, Peer

    theme = Theme()
    states, _ = graph.colours(theme)
    page = HubPage(
        HubData(
            peers=(
                Peer("a", "t", "working", "/w"),
                Peer("b", "t", "idle", "/w"),
                Peer("c", "t", "idle", "/w", "external"),
            ),
            daemons=(Daemon("d", "dead one", "dead"), Daemon("e", "live", "working")),
            offline=(Stored("old-id", "old"),),
        ),
        on_close=lambda: None,
    )

    def head(item):
        first = item.parts(theme)[0]
        assert "".join(text for text, _ in item.parts(theme)) == item.description
        return first[1]

    page._show(1)
    assert [head(item) for item in page.list.items] == [
        states["working"],
        states["idle"],
        states["external"],
        states["offline"],
    ]
    page._show(2)
    assert [head(item) for item in page.list.items] == [states["stopped"], states["working"]]
