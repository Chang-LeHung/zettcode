"""The picture on ``/hub``'s first tab: sessions as boxes, messages as lines, one colour per state.

Nothing here reads anything. :func:`build` turns the broker's graph (and the daemons' records) into :class:`Node` and
:class:`Link` values, :func:`place` puts the nodes on a ring around the reader's own session, and :func:`draw` paints
both onto a canvas: the lines as box-drawing characters routed at right angles with rounded corners (they join where
they meet, and every font draws them unbroken), and the nodes as rounded boxes laid over the ends of the lines.

A state has one colour, and the legend under the picture says which. The colours are the theme's own (``warning`` for
working, ``accent`` for idle, ``error`` for a daemon that stopped), so a palette change recolours the picture, and the
two lists beside the picture use the same colours for the same words.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zettcode.tui import Canvas
from zettcode.tui.render import Style

__all__ = ["Link", "Node", "build", "colours", "draw", "glyph", "legend", "place", "state_of"]

#: How many nodes the picture draws; a ring of more is a smear, and the rest are counted in the summary.
MAX_NODES = 16

#: The widest a box grows, label included.
MAX_BOX = 24

#: The states a node can be in, in the order the legend lists them.
STATES = ("working", "idle", "external", "offline", "stopped")

#: Message totals at which a line changes colour, and the words the legend uses for them.
TIERS = ((1, "1-4"), (5, "5-19"), (20, "20+"))

# A cell of line is the set of sides it joins: these bits, and the glyph each set is drawn as.
_N, _E, _S, _W = 1, 2, 4, 8
_JOINS = {
    _N: "\u2502",
    _S: "\u2502",
    _N | _S: "\u2502",
    _E: "\u2500",
    _W: "\u2500",
    _E | _W: "\u2500",
    _N | _E: "\u2570",
    _N | _W: "\u256f",
    _S | _E: "\u256d",
    _S | _W: "\u256e",
    _N | _E | _S: "\u251c",
    _N | _S | _W: "\u2524",
    _E | _S | _W: "\u252c",
    _N | _E | _W: "\u2534",
    _N | _E | _S | _W: "\u253c",
}


@dataclass(frozen=True, slots=True)
class Node:
    """One session, daemon or outsider the picture shows."""

    key: str
    label: str
    state: str
    me: bool = False


@dataclass(frozen=True, slots=True)
class Link:
    """Two nodes that exchanged messages, and how many."""

    a: str
    b: str
    count: int


def state_of(status: str, kind: str) -> str:
    """Return the state a roster entry (or a daemon's status) is drawn in."""
    if kind == "external":
        return "external"
    return "working" if status == "working" else "idle"


def glyph(state: str) -> str:
    """Return the mark in front of a state: a diamond for an outsider, a dot for the rest."""
    return "\u25c7" if state == "external" else "\u25cf"


def colours(theme: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return the colour of each state and of each line band, from the theme."""
    states = {
        "working": theme.warning,
        "idle": theme.accent,
        "external": theme.accent_bright,
        "offline": theme.muted,
        "stopped": theme.error,
    }
    return states, (theme.muted, theme.subtle, theme.text)


def build(
    graph: Mapping[str, Any],
    *,
    me: str = "",
    titles: Mapping[str, str] | None = None,
    stopped: Sequence[str] = (),
) -> tuple[tuple[Node, ...], tuple[Link, ...]]:
    """Return the nodes and links of the broker's graph.

    Args:
        graph: What ``Client.traffic_graph`` returned: ``sessions`` and ``edges``.
        me: The reader's own session id, drawn in the middle.
        titles: Names for sessions that are stored but not registered, by id.
        stopped: Ids of daemons whose process is gone.
    """
    names = dict(titles or {})
    gone = set(stopped)
    nodes: dict[str, Node] = {}
    for entry in graph.get("sessions", ()):
        key = str(entry.get("session_id", ""))
        if not key:
            continue
        label = str(entry.get("handle") or entry.get("title") or key[:8])
        nodes[key] = Node(key, label, state_of(str(entry.get("status", "idle")), str(entry.get("kind", ""))), key == me)
    links = []
    for edge in graph.get("edges", ()):
        a, b = str(edge.get("a", "")), str(edge.get("b", ""))
        if not a or not b or a == b:
            continue
        for key in (a, b):
            if key not in nodes:
                state = "stopped" if key in gone else "offline"
                nodes[key] = Node(key, names.get(key) or key[:8], state, key == me)
        links.append(Link(a, b, int(edge.get("count", 1))))
    for key in gone:
        if key not in nodes and key in names:
            nodes[key] = Node(key, names[key], "stopped", key == me)
    return tuple(nodes.values()), tuple(links)


def _text(node: Node) -> str:
    """Return what a box says: the label, and ``(you)`` after the reader's own."""
    return node.label + (" (you)" if node.me else "")


def _box(node: Node) -> int:
    """Return the width of a node's box: its glyph, its label and a column of air on both sides."""
    return min(MAX_BOX, len(_text(node)) + 6)


def _order(nodes: Sequence[Node], links: Sequence[Link]) -> list[Node]:
    """Return the nodes around the ring so that talkers sit next to each other where they can.

    The busiest node goes first, and each next one is the unplaced node with the most messages to the one just
    placed (the busiest of the rest when it has none), which keeps the long lines across the ring few.
    """
    weight: dict[str, dict[str, int]] = {node.key: {} for node in nodes}
    for link in links:
        if link.a in weight and link.b in weight:
            weight[link.a][link.b] = weight[link.a].get(link.b, 0) + link.count
            weight[link.b][link.a] = weight[link.b].get(link.a, 0) + link.count
    left = {node.key: node for node in nodes}
    total = {key: sum(neighbours.values()) for key, neighbours in weight.items()}
    out: list[Node] = []
    current: str | None = None
    while left:
        pool = weight[current] if current else {}
        key = max(left, key=lambda k: (pool.get(k, 0), total[k]))
        out.append(left.pop(key))
        current = key
    return out


def place(nodes: Sequence[Node], links: Sequence[Link], width: int, height: int) -> dict[str, tuple[int, int]]:
    """Return the centre of each node's box inside a ``width`` by ``height`` area.

    The reader's own session is in the middle with the rest on an ellipse round it; two nodes face each other, and
    one sits alone in the centre.
    """
    if not nodes or width <= 0 or height <= 0:
        return {}
    cx, cy = width // 2, height // 2
    if len(nodes) == 1:
        return {nodes[0].key: (cx, cy)}
    if len(nodes) == 2:
        first, second = sorted(nodes, key=lambda node: not node.me)
        return {first.key: (width // 4, cy), second.key: (width - width // 4, cy)}
    centre = next((node for node in nodes if node.me), None)
    ring = _order([node for node in nodes if node is not centre], links)
    widest = max(_box(node) for node in nodes)
    rx = max(1.0, (width - widest) / 2 - 1)
    ry = max(1.0, (height - 3) / 2 - 0.5)
    spots: dict[str, tuple[int, int]] = {}
    if centre is not None:
        spots[centre.key] = (cx, cy)
    for index, node in enumerate(ring):
        angle = -math.pi / 2 + 2 * math.pi * index / len(ring)
        spots[node.key] = (round(cx + rx * math.cos(angle)), round(cy + ry * math.sin(angle)))
    return spots


def _tier(count: int) -> int:
    """Return which colour band a message total falls in: 0, 1 or 2."""
    return sum(1 for floor, _ in TIERS[1:] if count >= floor)


def _route(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """Return the cells of a right-angled path from ``a`` to ``b``, corner to corner of two straight runs.

    A path leaves along the longer side: horizontally when the nodes are wider apart than twice their height apart
    (a cell is about twice as tall as it is wide), vertically otherwise, and turns twice at the half way mark.
    """
    (ax, ay), (bx, by) = a, b
    horizontal = abs(bx - ax) >= 2 * abs(by - ay)
    points = [(ax, ay)]

    def walk(x: int, y: int) -> None:
        while (points[-1][0], points[-1][1]) != (x, y):
            px, py = points[-1]
            points.append((px + (x > px) - (x < px), py) if px != x else (px, py + (y > py) - (y < py)))

    if horizontal:
        mid = (ax + bx) // 2
        walk(mid, ay)
        walk(mid, by)
        walk(bx, by)
    else:
        mid = (ay + by) // 2
        walk(ax, mid)
        walk(bx, mid)
        walk(bx, by)
    return points


def _runs(points: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Return the length and middle cell of each straight stretch of a path, longest first."""
    found: list[tuple[int, int, int]] = []
    start = 0
    for index in range(1, len(points) + 1):
        turned = index == len(points) or (
            index - start >= 2
            and (points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
            != (points[index - 1][0] - points[index - 2][0], points[index - 1][1] - points[index - 2][1])
        )
        if turned:
            length = index - start
            middle = points[start + length // 2]
            found.append((length, middle[0], middle[1]))
            start = index - 1
    return sorted(found, reverse=True)


def _sides(before: tuple[int, int] | None, here: tuple[int, int], after: tuple[int, int] | None) -> int:
    """Return which sides of the cell a path joins, from the cells before and after it."""
    bits = 0
    for other in (before, after):
        if other is None:
            continue
        dx, dy = other[0] - here[0], other[1] - here[1]
        bits |= _E if dx > 0 else _W if dx < 0 else _S if dy > 0 else _N
    return bits


def draw(
    canvas: Canvas,
    theme: Any,
    x: int,
    y: int,
    width: int,
    height: int,
    nodes: Sequence[Node],
    links: Sequence[Link],
) -> None:
    """Paint the graph into the rectangle: lines first, then their counts, then each box over its line ends."""
    shown = list(nodes[:MAX_NODES])
    keep = {node.key for node in shown}
    links = [link for link in links if link.a in keep and link.b in keep]
    spots = place(shown, links, width, height)
    states, bands = colours(theme)
    page = theme.surface_alt

    boxes: dict[str, tuple[int, int, int, int]] = {}
    for node in shown:
        centre_x, centre_y = spots[node.key]
        boxes[node.key] = (centre_x - _box(node) // 2, centre_y - 1, _box(node), 3)

    sides: dict[tuple[int, int], int] = {}
    band: dict[tuple[int, int], int] = {}
    runs: list[tuple[int, list[tuple[int, int, int]]]] = []
    for link in sorted(links, key=lambda item: item.count):
        path = _route(spots[link.a], spots[link.b])
        for index, cell in enumerate(path):
            before = path[index - 1] if index else None
            after = path[index + 1] if index + 1 < len(path) else None
            sides[cell] = sides.get(cell, 0) | _sides(before, cell, after)
            band[cell] = max(band.get(cell, 0), _tier(link.count))
        runs.append((link.count, _runs(path)))
    for (cell_x, cell_y), bits in sides.items():
        if 0 <= cell_x < width and 0 <= cell_y < height and bits in _JOINS:
            canvas.set_cell(
                x + cell_x,
                y + cell_y,
                _JOINS[bits],
                Style(foreground=bands[band[(cell_x, cell_y)]], background=page),
            )

    # The total sits on the longest stretch of its line that is clear of the boxes, with a space either side.
    for count, stretches in runs:
        text = f" {count} "
        for length, mid_x, mid_y in stretches:
            left = mid_x - len(text) // 2
            if length < 4 or left < 0 or left + len(text) > width:
                continue
            if any(
                bx <= left + len(text) and left <= bx + bw and by - 1 <= mid_y <= by + bh
                for bx, by, bw, bh in boxes.values()
            ):
                continue
            canvas.draw_text(
                x + left, y + mid_y, text, Style(foreground=bands[_tier(count)], background=page, bold=True)
            )
            break

    for node in shown:
        left, top, w, _ = boxes[node.key]
        colour = states[node.state]
        edge = Style(foreground=colour, background=theme.surface, bold=node.me or node.state == "working")
        body = Style(foreground=theme.text, background=theme.surface, bold=node.me)
        canvas.fill(x + left, y + top, w, 3, Style(background=theme.surface))
        if node.me:
            tl, tr, bl, br, bar, side = "\u2554", "\u2557", "\u255a", "\u255d", "\u2550", "\u2551"
        else:
            tl, tr, bl, br, bar, side = "\u256d", "\u256e", "\u2570", "\u256f", "\u2500", "\u2502"
        canvas.draw_text(x + left, y + top, tl + bar * (w - 2) + tr, edge)
        canvas.draw_text(x + left, y + top + 2, bl + bar * (w - 2) + br, edge)
        canvas.draw_text(x + left, y + top + 1, side, edge)
        canvas.draw_text(x + left + w - 1, y + top + 1, side, edge)
        canvas.draw_text(
            x + left + 2, y + top + 1, glyph(node.state), Style(foreground=colour, background=theme.surface, bold=True)
        )
        canvas.draw_text(x + left + 4, y + top + 1, _text(node), body, max_width=w - 6)


def legend(theme: Any) -> list[tuple[str, Style]]:
    """Return the legend as text pieces with their styles, in the order they are laid left to right."""
    states, bands = colours(theme)
    muted = Style(foreground=theme.muted, background=theme.surface_alt)
    pieces: list[tuple[str, Style]] = []
    for state in STATES:
        pieces.append((glyph(state) + " ", Style(foreground=states[state], background=theme.surface_alt, bold=True)))
        pieces.append((state + "   ", muted))
    pieces.append(("messages ", muted))
    for index, (_, words) in enumerate(TIERS):
        pieces.append(("\u2500\u2500 ", Style(foreground=bands[index], background=theme.surface_alt, bold=True)))
        pieces.append((words + "  ", muted))
    return pieces
