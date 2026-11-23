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
    nodes, links = graph.build(WIRE, me="me", titles={"gone": "old one"}, offline=["dead-1"])

    assert {node.key: node.state for node in nodes} == {
        "me": "working",
        "a": "idle",
        "b": "external",
        "gone": "offline",
    }
    assert [node.label for node in nodes if node.key == "gone"] == ["old one"]
    assert next(node for node in nodes if node.me).key == "me"
    assert [(link.a, link.b) for link in links] == [("me", "a"), ("a", "gone")], "a line to itself is dropped"


def test_the_two_directions_of_a_pair_are_one_line_with_the_counts_added():
    nodes, links = graph.build(
        {
            "sessions": [{"session_id": "a", "handle": "a"}, {"session_id": "b", "handle": "b"}],
            "edges": [{"a": "a", "b": "b", "count": 3}, {"a": "b", "b": "a", "count": 4}],
        },
        me="a",
    )

    assert [(link.count, {link.a, link.b}) for link in links] == [(7, {"a", "b"})]
    picture = graph.layout(nodes, links, 80, 17)
    assert len(picture.routes) == 1 and len(picture.labels) == 1, "one line, one number"


def test_two_entries_for_one_pair_add_their_totals_too_and_a_missing_one_leaves_it_unknown():
    """The stretch and the whole history are added per direction the same way: a total that either side did not say
    stays unknown rather than being reported as the half that was said."""
    both = {
        "sessions": [{"session_id": "a", "handle": "a"}, {"session_id": "b", "handle": "b"}],
        "edges": [
            {"a": "a", "b": "b", "count": 2, "total": 10},
            {"a": "b", "b": "a", "count": 3, "total": 11},
        ],
    }
    half = {
        "sessions": [],
        "edges": [{"a": "a", "b": "b", "count": 2, "total": 10}, {"a": "b", "b": "a", "count": 3}],
    }

    (_, links), (_, partial) = graph.build(both), graph.build(half)

    assert [(link.count, link.total) for link in links] == [(5, 21)], "counts and totals are added alike"
    assert [(link.count, link.total) for link in partial] == [(5, None)], (
        "one silent direction leaves the whole unknown"
    )


def test_a_daemon_whose_process_is_gone_is_offline_even_with_no_messages():
    nodes, _ = graph.build({}, titles={"d-1": "watcher"}, offline=["d-1"])

    assert [(node.label, node.state) for node in nodes] == [("watcher", "offline")]


def test_every_state_has_its_own_colour_and_they_come_from_the_theme():
    theme = Theme()
    colours = graph.colours(theme)

    assert set(colours) == set(graph.STATES)
    assert len(set(colours.values())) == len(graph.STATES), "no two states share a colour"
    assert colours["working"] == theme.accent and colours["offline"] == theme.muted
    assert "stopped" not in graph.STATES, "a daemon that was stopped is offline, the same as a stored session"


# -- which nodes, and where -------------------------------------------------------------------------


def test_the_busiest_are_kept_and_the_readers_own_session_is_never_the_one_cut():
    nodes, links = crowd(40, hub="5", me="39")

    picture = graph.layout(nodes, links, 110, 32)

    assert picture.nodes[0].me, "the reader's own is first and in the picture"
    assert 0 < len(picture.nodes) <= graph.MAX_NODES
    assert picture.hidden_nodes == len(nodes) - len(picture.nodes)
    totals = graph._totals(links)
    assert graph.rank(nodes, links)[0].me, "rank puts the reader's own first whatever it has said"
    by_total = [totals.get(node.key, 0) for node in graph.rank(nodes, links)[1:]]
    assert by_total == sorted(by_total, reverse=True), "and the rest busiest first, so a cut drops the quietest"


def test_a_session_working_now_keeps_its_box_when_the_picture_is_full():
    """The page promises a box to whatever is working now: a daemon started a moment ago has said nothing, so it must
    come before the quietest talker rather than after it — and the summary counts the working boxes actually drawn."""
    sessions = [{"session_id": str(index), "handle": f"session-{index}", "status": "idle"} for index in range(18)]
    sessions.append({"session_id": "busy", "handle": "builder", "status": "working"})
    edges = [{"a": "0", "b": str(index), "count": index + 1} for index in range(1, 18)]
    nodes, links = graph.build(
        {"sessions": sessions, "edges": edges}, me="0", only={str(index) for index in range(19)} | {"busy"}
    )

    picture = graph.layout(nodes, links, 150, 44)

    drawn = {node.key for node in picture.nodes}
    assert len(drawn) == graph.MAX_NODES, "the picture is full"
    assert "busy" in drawn, "a working session keeps its box: it is ranked before the talkers"
    assert graph.rank(nodes, links)[1].key == "busy", "the reader's own first, the working one next"
    assert "1 working" in graph.summary(nodes, links, picture), "and the count is of the boxes the picture has"
    assert [node.key for node in picture.nodes] == [node.key for node in graph.rank(nodes, links)[: len(picture.nodes)]]


def test_many_working_sessions_take_half_the_seats_and_leave_the_traffic_in_the_picture():
    """Sixteen sessions working at once must not turn the traffic picture into a census of them: half the seats are
    held for the working, the rest goes to traffic, and the summary counts only what the picture holds."""
    sessions = [{"session_id": "me", "handle": "main", "status": "idle"}]
    sessions += [{"session_id": f"w{index}", "handle": f"worker-{index}", "status": "working"} for index in range(17)]
    sessions += [{"session_id": f"t{index}", "handle": f"talker-{index}", "status": "idle"} for index in range(3)]
    edges = [{"a": "t0", "b": "t1", "count": 40}, {"a": "t1", "b": "t2", "count": 40}]
    nodes, links = graph.build({"sessions": sessions, "edges": edges}, me="me")

    picture = graph.layout(nodes, links, 150, 44)

    drawn = [node.key for node in picture.nodes]
    assert {"t0", "t1", "t2", "me"} <= set(drawn), "the traffic and the reader are still there, whatever is working"
    assert picture.routes, "with their lines: a picture of the conversation is what this tab is for"
    assert drawn.index("w0") < drawn.index("t0"), "a session working now is seated before the talkers"
    busy = sum(1 for node in picture.nodes if node.state == "working")
    line = graph.summary(nodes, links, picture)
    assert f"{busy} working" in line, "the count is of the working boxes the picture has"
    assert "80 messages lately" in line, "and only the messages between the boxes it holds"


# (20, 5) and (40, 10) are not here: `layout` draws nothing or one box in them, and the loops below would pass over an
# empty list. `test_a_window_too_small...` in test_hub.py and `test_two_wide_boxes_in_the_narrowest_area...` cover them.
@pytest.mark.parametrize("size", [(76, 17), (56, 13), (110, 32), (200, 50)])
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


@pytest.mark.parametrize(
    ("size", "fits"),
    [((76, 17), 8), ((96, 23), 12), ((106, 25), 12), ((150, 44), 16), ((60, 20), 3)],
)
def test_every_node_is_drawn_when_it_fits_the_area(size, fits):
    """The loops above pass over an empty picture; this says that a picture is not empty when it should not be."""
    for count in range(1, fits + 1):
        nodes, links = crowd(count)

        picture = graph.layout(nodes, links, *size)

        assert len(picture.nodes) == count, f"{count} nodes in {size}: {len(picture.nodes)} drawn"
        assert picture.hidden_nodes == 0


def test_the_ring_is_not_dropped_for_the_half_row_of_an_even_height():
    """150x44: the vertical radius is 19.5 and rounding put a ring box on the edge, so three nodes drew two."""
    nodes, links = crowd(3)

    assert len(graph.layout(nodes, links, 150, 44).nodes) == 3


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
        for cell in route.cells[1:-1]:
            hugging = [
                key
                for key, (left, top, w) in picture.boxes.items()
                if key not in (route.link.a, route.link.b)
                and (
                    (left - 1 <= cell[0] <= left + w and top <= cell[1] < top + graph.BOX_HEIGHT)
                    or (left <= cell[0] < left + w and top - 1 <= cell[1] <= top + graph.BOX_HEIGHT)
                )
            ]
            assert not hugging, f"no cell between the ends touches the side of a box the line does not join: {hugging}"


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
    assert len(picture.labels) + picture.unnumbered == len(picture.routes)
    assert len(picture.labels) >= len(picture.routes) // 2


@pytest.mark.parametrize("size", [(110, 32), (76, 17), (106, 25), (96, 23)])
@pytest.mark.parametrize("count", [6, 10, 14])
def test_a_number_is_never_over_a_box_a_corner_a_foreign_line_or_against_another_box(size, count):
    nodes, links = crowd(count)
    picture = graph.layout(nodes, links, *size)
    owner = {
        (x, y): key
        for key, (left, top, w) in picture.boxes.items()
        for x in range(left, left + w)
        for y in range(top, top + graph.BOX_HEIGHT)
    }
    assert picture.labels, "something is numbered"

    for left, top, text, index in picture.labels:
        route = picture.routes[index]
        for x in range(left, left + len(text)):
            assert (x, top) not in owner, "never over a box"
            if text.startswith(" "):  # written on its own line: only a straight stretch, never the joining cell
                (_, sides) = next(part for part in picture.cells[(x, top)] if part[0] == index)
                assert len(picture.cells[(x, top)]) == 1, "never on a cell another line also runs through"
                assert sides == 0b1010, "never over a corner or a junction: only a straight east-west stretch"
                assert (x, top) != route.cells[-1], "never the cell that joins the box at the far end"
            else:  # beside a line
                assert (x, top) not in picture.cells, "never over any line"
                for near in ((x - 1, top), (x + 1, top), (x, top - 1), (x, top + 1)):
                    joined = (route.link.a, route.link.b)
                    assert owner.get(near, route.origin) in joined, "never against a box its line does not join"


def test_a_short_ring_numbers_every_line_even_one_between_two_boxes_a_row_apart():
    nodes, links = crowd(6)

    roomy = graph.layout(nodes, links, 76, 17)
    cramped = graph.layout(nodes, links, 56, 13)

    assert roomy.routes and len(roomy.labels) == len(roomy.routes), "every line is numbered when there is room"
    assert cramped.routes and len(cramped.labels) == len(cramped.routes), "and in a short ring too"
    assert cramped.unnumbered == 0
    for _, _, text, index in cramped.labels:
        assert text.strip() == str(cramped.routes[index].link.count)


def test_the_summary_says_when_a_number_found_no_place():
    nodes, links = crowd(4)
    picture = graph.Picture(nodes=tuple(nodes), unnumbered=2)

    assert "2 without a number" in graph.summary(nodes, links, picture)


def test_a_wide_whole_history_is_written_where_there_is_room_rather_than_left_out():
    """Five digits do not fit between a label and the box beside it; the picture has rows to spare, so the number goes
    two or three rows out instead of being dropped as though the picture were full."""
    wire = {
        "sessions": [
            {"session_id": "me", "handle": "main", "status": "working"},
            {"session_id": "a", "handle": "review", "status": "idle"},
        ],
        "edges": [{"a": "me", "b": "a", "count": 3, "total": 32000}],
    }
    nodes, links = graph.build(wire, me="me")

    picture = graph.layout(nodes, links, 110, 32)

    assert [text for _, _, text, _ in picture.totals] == ["32000"], "the room is there, so the number is written"
    left, top, _, index = picture.totals[0]
    first_x, first_y, first_text = next((x, y, t) for x, y, t, at in picture.labels if at == index)
    assert left == first_x + first_text.index("3"), "in its own digit's column"
    assert 1 <= abs(top - first_y) <= 3, "and one to three rows out, where the picture had room"


def test_a_line_whose_two_have_said_more_in_all_writes_the_whole_history_beside_its_own_number():
    """The number on the line is the stretch the page read; the whole history follows it in a plainer style, lined up
    with its digits, and only when the broker said what it was and it is not that same number again."""
    sessions = [{"session_id": str(index), "handle": f"session-{index}", "status": "idle"} for index in range(6)]
    edges = [{"a": "0", "b": str(index), "count": 3, "total": 58} for index in range(1, 5)]
    edges.append({"a": "0", "b": "5", "count": 2, "total": 2})
    nodes, links = graph.build({"sessions": sessions, "edges": edges}, me="0")

    picture = graph.layout(nodes, links, 110, 32)

    assert len(picture.totals) >= 3, "most second numbers find a place in a roomy picture"
    for left, top, text, index in picture.totals:
        route = picture.routes[index]
        assert text == str(route.link.total) == "58", "the pair that said as much in all as lately gets no second one"
        first_x, first_y, first_text = next((x, y, t) for x, y, t, at in picture.labels if at == index)
        digit = first_x + first_text.index(str(route.link.count))
        if top == first_y:
            assert left in (digit + len(first_text), first_x - len(text)), "beside the number, on its row"
        else:
            assert 1 <= abs(top - first_y) <= 3 and left == digit, "one to three rows over its own digits, or under"


def test_the_whole_history_is_written_quieter_than_the_number_on_the_line():
    theme = Theme()
    wire = {
        "sessions": [
            {"session_id": "me", "handle": "main", "status": "working"},
            {"session_id": "a", "handle": "review", "status": "idle"},
        ],
        "edges": [{"a": "me", "b": "a", "count": 3, "total": 58}],
    }
    nodes, links = graph.build(wire, me="me")
    picture = graph.layout(nodes, links, 110, 32)
    canvas = painted(picture)

    assert picture.totals and picture.labels
    for left, top, text, _index in picture.totals:
        for offset in range(len(text)):
            assert canvas.cells[top][left + offset].style.foreground == theme.muted
    for left, top, _text, _index in picture.labels:
        assert canvas.cells[top][left].style.foreground != theme.muted, "the number on the line keeps the line's colour"


@pytest.mark.parametrize("size", [(80, 24), (110, 32), (150, 44), (44, 20)])
@pytest.mark.parametrize("pairs", [5, 8, 12])
def test_a_second_number_never_stacks_on_another_or_loses_its_way_back_to_its_own(size, pairs):
    """Two numbers in one column with a row between them read as one figure, and a total two or three rows out is
    only its own number's when nothing sits between the two — no other number, and no line running across."""
    sessions = [
        {"session_id": str(index), "handle": f"session-{index}", "status": "idle"} for index in range(pairs + 1)
    ]
    edges = [{"a": str(index), "b": str(index + 1), "count": index + 2, "total": 32000} for index in range(pairs)]
    nodes, links = graph.build({"sessions": sessions, "edges": edges}, me="0")

    picture = graph.layout(nodes, links, *size)

    numbers = {(x + i, y): index for x, y, text, index in picture.labels for i in range(len(text))}
    assert picture.totals, "something was written, or there is nothing to check"
    for left, top, text, index in picture.totals:
        own_x, own_y, own_text = next((x, y, t) for x, y, t, at in picture.labels if at == index)
        own = {(own_x + i, own_y) for i in range(len(own_text))}
        foreign = set(numbers) - own
        own_cells = {(left + i, top) for i in range(len(text))}
        assert not own_cells & foreign, "never on another number"
        for x, y in own_cells:
            assert (x, y - 1) not in foreign and (x, y + 1) not in foreign, "nor a row above or below another number"
        step = 1 if top > own_y else -1
        for between in range(own_y + step, top, step):
            assert not {(x, between) for x, _ in own_cells} & (foreign | set(picture.cells)), (
                "nothing between it and its own number: no other number, no line running across"
            )


def test_build_keeps_only_the_sessions_the_page_read_out_of_the_broker():
    """A roster entry the stretch of messages did not touch gets no box, and a line with an end outside the set is
    dropped, so the picture never holds a line to a box it does not draw."""
    wire = {
        "sessions": [
            {"session_id": "me", "handle": "main", "status": "working"},
            {"session_id": "quiet", "handle": "asleep", "status": "idle"},
        ],
        "edges": [{"a": "me", "b": "a", "count": 4, "total": 9}, {"a": "quiet", "b": "b", "count": 2}],
    }

    nodes, links = graph.build(wire, me="me", only={"me", "a"})

    assert [node.key for node in nodes] == ["me", "a"], "the quiet entry and the unnamed end are both gone"
    assert [(link.a, link.b, link.count, link.total) for link in links] == [("me", "a", 4, 9)]


def test_the_summary_says_how_many_of_the_sessions_the_broker_knows_the_picture_shows():
    nodes, links = crowd(4)
    picture = graph.layout(nodes, links, 110, 32)

    assert "4 nodes" in graph.summary(nodes, links, picture), "nothing to compare against: every one of them"
    assert "4 of 209 nodes" in graph.summary(nodes, links, picture, total=209)


def test_a_picture_that_holds_more_nodes_than_the_history_names_is_not_a_slice_of_it():
    """A session working now, or the reader's own, is in the picture without being in the message file's history:
    ``of N`` would then describe a slice smaller than the picture, so the line says only what it holds."""
    nodes, links = crowd(4)
    picture = graph.layout(nodes, links, 110, 32)

    assert graph.summary(nodes, links, picture, total=2).startswith("4 nodes")


def test_two_wide_boxes_in_the_narrowest_area_the_page_draws_both_and_the_line():
    nodes, links = graph.build(
        {
            "sessions": [
                {"session_id": "me", "handle": "session-0", "status": "idle"},
                {"session_id": "b", "handle": "session-1", "status": "idle"},
            ],
            "edges": [{"a": "me", "b": "b", "count": 7}],
        },
        me="me",
    )

    picture = graph.layout(nodes, links, 40, 10)

    assert len(picture.nodes) == 2, "two boxes fit at the page's own minimum width"
    assert picture.routes and picture.labels, "with a line between them and its number"
    (al, _, aw), (bl, _, bw) = picture.boxes.values()
    assert al == 1 and bl > al + aw and bl + bw <= 39, "the first against the edge, a free lane, the second inside"


def test_a_summary_cut_by_a_narrow_page_loses_the_working_count_and_not_what_was_left_out():
    nodes, links = crowd(40)
    picture = graph.layout(nodes, links, 110, 32)

    line = graph.summary(nodes, links, picture)

    assert line.index("not drawn") < line.index("working"), "what is left out comes first"
    assert line.endswith("working")


def test_lines_that_are_not_drawn_between_drawn_nodes_are_counted_and_the_summary_says_so():
    everyone = [{"session_id": str(i), "handle": f"s{i}", "status": "idle"} for i in range(16)]
    pairs = [{"a": str(i), "b": str(j), "count": 1 + i + j} for i in range(16) for j in range(i + 1, 16)]
    nodes, links = graph.build({"sessions": everyone, "edges": pairs}, me="0")

    picture = graph.layout(nodes, links, 150, 44)

    assert len(picture.nodes) == 16 and len(links) == 120
    assert len(picture.routes) <= graph.MAX_LINKS
    assert picture.undrawn == 120 - len(picture.routes) > 0, "the lines lost between two drawn boxes are counted"
    assert f"{picture.undrawn} lines not drawn" in graph.summary(nodes, links, picture)


def test_a_selected_node_reports_the_lines_drawn_out_of_those_it_has():
    everyone = [{"session_id": str(i), "handle": f"s{i}", "status": "idle"} for i in range(16)]
    pairs = [{"a": str(i), "b": str(j), "count": 1 + i + j} for i in range(16) for j in range(i + 1, 16)]
    nodes, links = graph.build({"sessions": everyone, "edges": pairs}, me="0")
    picture = graph.layout(nodes, links, 150, 44)

    quiet = next(
        node.key
        for node in picture.nodes
        if sum(1 for route in picture.routes if node.key in (route.link.a, route.link.b)) < 15
    )

    said = graph.summary(nodes, links, picture, quiet)

    assert " of 15 lines" in said, said


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
    checked = 0
    for route in picture.routes:
        x, y = route.cells[len(route.cells) // 2]
        if len(picture.cells[(x, y)]) == 1:
            checked += 1
            assert canvas.cells[y][x].style.foreground == graph.colours(theme)[by_key[route.origin].state]
    assert checked == len(picture.routes) >= 2, "every line was looked at"
    text = text_of(canvas)
    assert "main (you)" in text and "review" in text and "ci-bot" in text, "all three nodes are drawn"
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


def test_selecting_a_node_does_not_cut_a_dimmed_line_where_a_bright_one_crosses_it():
    nodes, links = crowd(12)
    picture = graph.layout(nodes, links, 110, 32)
    normal = painted(picture)
    crossings = 0

    for chosen in (node.key for node in picture.nodes):
        selected = painted(picture, chosen)
        for (x, y), parts in picture.cells.items():
            lit = [i for i, _ in parts if chosen in (picture.routes[i].link.a, picture.routes[i].link.b)]
            if len(parts) > 1 and lit and len(lit) < len(parts):
                crossings += 1
                assert selected.cells[y][x].character == normal.cells[y][x].character, "the glyph keeps its shape"
    assert crossings > 5, "the picture has crossings to check"


def test_arrows_are_the_same_in_every_direction_a_row_counting_as_two_columns():
    def box(x: int, y: int) -> tuple[int, int, int]:
        return (x - 3, y - 1, 6)

    nodes = tuple(graph.Node(key, key, "idle", key == "mid") for key in ("mid", "r", "l", "d", "u"))
    boxes = {"mid": box(50, 20), "r": box(70, 20), "l": box(30, 20), "d": box(50, 30), "u": box(50, 10)}
    picture = graph.Picture(nodes=nodes, boxes=boxes)

    # 20 columns across and 10 rows down are the same distance on screen.
    assert [graph.nearest(picture, "mid", arrow) for arrow in ("right", "left", "down", "up")] == ["r", "l", "d", "u"]
    assert graph.nearest(picture, None, "left") == "mid", "the first arrow selects the reader's own"
    assert graph.nearest(picture, "r", "right") is None, "nothing further that way"
    assert graph.nearest(picture, "u", "up") is None, "nothing above the top one"
    assert graph.nearest(picture, "r", "up") == "u", "up and to the left, 45 degrees, is still up"
    assert graph.nearest(graph.Picture(), None, "left") is None


def test_an_arrow_prefers_the_node_in_line_over_a_closer_one_off_to_the_side():
    def box(x: int, y: int) -> tuple[int, int, int]:
        return (x - 3, y - 1, 6)

    nodes = tuple(graph.Node(key, key, "idle", key == "mid") for key in ("mid", "inline", "aside"))
    boxes = {"mid": box(50, 20), "inline": box(80, 20), "aside": box(66, 30)}
    picture = graph.Picture(nodes=nodes, boxes=boxes)

    assert graph.nearest(picture, "mid", "right") == "inline", "the one in line beats the closer one off to the side"


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
    assert "not drawn" in graph.summary(many, many_links, graph.layout(many, many_links, 110, 32))


def test_the_legend_names_every_state_with_its_own_colour_and_starts_with_what_a_number_means():
    pieces = [piece for group in graph.legend(Theme()) for piece in group]
    text = "".join(piece for piece, _ in pieces)

    assert text.startswith("n = messages")
    for state in graph.STATES:
        assert state in text
    colours = [style.foreground for piece, style in pieces if piece.startswith(("\u25cf", "\u25c7"))]
    assert len(set(colours)) == len(graph.STATES)


def test_the_lists_colour_a_state_the_way_the_graph_does():
    from zettcode.commands.hub import SESSIONS, Daemon, HubData, HubPage, Peer

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
    ]
    page._show(SESSIONS + 1)
    assert [head(item) for item in page.list.items] == [states["offline"], states["working"]]
