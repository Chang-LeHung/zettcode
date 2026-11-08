"""The picture on ``/hub``'s first tab: sessions as boxes, messages as lines, one colour per state.

Nothing here reads anything. :func:`build` turns the broker's graph (and the daemons' records) into :class:`Node` and
:class:`Link` values, :func:`place` puts the nodes on a ring around the reader's own session, and :func:`draw` paints
both onto a canvas: the lines as braille dots, which are two dots wide and four high inside one cell and so bend like
lines instead of stepping like blocks, and the nodes as rounded boxes laid over the ends of the lines.

A state has one colour, and the legend under the picture says which. The colours are the theme's own (``warning`` for
working, ``accent`` for idle, ``error`` for a daemon that stopped), so a palette change recolours the picture.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zettcode.tui import Canvas
from zettcode.tui.render import Style

__all__ = ["Link", "Node", "build", "draw", "legend", "place"]

#: How many nodes the picture draws; a ring of more is a smear, and the rest are counted in the summary.
MAX_NODES = 16

#: The widest a box grows, label included.
MAX_BOX = 24

#: The states a node can be in, in the order the legend lists them.
STATES = ("working", "idle", "external", "offline", "stopped")

#: Message totals at which a line changes colour, and the words the legend uses for them.
TIERS = ((1, "1-4"), (5, "5-19"), (20, "20+"))

# The dot of a braille cell at (column, row) is this bit of the code point offset from U+2800.
_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


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


def _state(status: str, kind: str) -> str:
    """Return the state a roster entry is drawn in."""
    if kind == "external":
        return "external"
    return "working" if status == "working" else "idle"


def build(
    graph: Mapping[str, Any],
    *,
    me: str = "",
    titles: Mapping[str, str] | None = None,
    stopped: Iterable[str] = (),
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
        nodes[key] = Node(key, label, _state(str(entry.get("status", "idle")), str(entry.get("kind", ""))), key == me)
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


def _line(x0: int, y0: int, x1: int, y1: int) -> Iterable[tuple[int, int]]:
    """Yield the dots of a straight line between two dots (Bresenham)."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    step_x, step_y = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += step_x
        if doubled <= dx:
            error += dx
            y0 += step_y


def _tier(count: int) -> int:
    """Return which colour band a message total falls in: 0, 1 or 2."""
    return sum(1 for floor, _ in TIERS[1:] if count >= floor)


def _colours(theme: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return the colour of each state and of each line band, from the theme."""
    states = {
        "working": theme.warning,
        "idle": theme.accent,
        "external": theme.accent_bright,
        "offline": theme.muted,
        "stopped": theme.error,
    }
    return states, (theme.muted, theme.subtle, theme.accent_bright)


def draw(
    canvas: Canvas, theme: Any, x: int, y: int, width: int, height: int, nodes: Sequence[Node], links: Sequence[Link]
) -> None:
    """Paint the graph into the rectangle: lines first, then each box over its line ends, then the counts."""
    shown = list(nodes[:MAX_NODES])
    keep = {node.key for node in shown}
    links = [link for link in links if link.a in keep and link.b in keep]
    spots = place(shown, links, width, height)
    states, bands = _colours(theme)
    page = theme.surface_alt

    # The lines: one braille cell per 2x4 dots, the strongest band winning where lines cross.
    dots: dict[tuple[int, int], int] = {}
    band: dict[tuple[int, int], int] = {}
    for link in sorted(links, key=lambda item: item.count):
        (ax, ay), (bx, by) = spots[link.a], spots[link.b]
        for dot_x, dot_y in _line(ax * 2 + 1, ay * 4 + 2, bx * 2 + 1, by * 4 + 2):
            cell = (dot_x // 2, dot_y // 4)
            dots[cell] = dots.get(cell, 0) | _DOTS[dot_y % 4][dot_x % 2]
            band[cell] = max(band.get(cell, 0), _tier(link.count))
    for (cell_x, cell_y), bits in dots.items():
        if 0 <= cell_x < width and 0 <= cell_y < height:
            style = Style(foreground=bands[band[(cell_x, cell_y)]], background=page)
            canvas.set_cell(x + cell_x, y + cell_y, chr(0x2800 + bits), style)

    # The counts, on the middle of each line, unless a box is there.
    boxes = {}
    for node in shown:
        if node.key in spots:
            centre_x, centre_y = spots[node.key]
            w = _box(node)
            boxes[node.key] = (centre_x - w // 2, centre_y - 1, w, 3)
    for link in links:
        (ax, ay), (bx, by) = spots[link.a], spots[link.b]
        mid_x, mid_y = (ax + bx) // 2, (ay + by) // 2
        text = f" {link.count} "
        left = mid_x - len(text) // 2
        if any(
            bx0 - 1 <= left + len(text) and left <= bx0 + bw and by0 - 1 <= mid_y <= by0 + bh
            for bx0, by0, bw, bh in boxes.values()
        ):
            continue
        canvas.draw_text(
            x + left, y + mid_y, text, Style(foreground=bands[_tier(link.count)], background=page, bold=True)
        )

    # The boxes.
    for node in shown:
        left, top, w, _ = boxes[node.key]
        colour = states[node.state]
        edge = Style(foreground=colour, background=theme.surface, bold=node.me or node.state == "working")
        body = Style(foreground=theme.text, background=theme.surface, bold=node.me)
        canvas.fill(x + left, y + top, w, 3, Style(background=theme.surface))
        top_left, top_right, bottom_left, bottom_right, bar = (
            ("\u2554", "\u2557", "\u255a", "\u255d", "\u2550")
            if node.me
            else ("\u256d", "\u256e", "\u2570", "\u256f", "\u2500")
        )
        side = "\u2551" if node.me else "\u2502"
        canvas.draw_text(x + left, y + top, top_left + bar * (w - 2) + top_right, edge)
        canvas.draw_text(x + left, y + top + 2, bottom_left + bar * (w - 2) + bottom_right, edge)
        canvas.draw_text(x + left, y + top + 1, side, edge)
        canvas.draw_text(x + left + w - 1, y + top + 1, side, edge)
        glyph = "\u25c7" if node.state == "external" else "\u25cf"
        canvas.draw_text(
            x + left + 2, y + top + 1, glyph, Style(foreground=colour, background=theme.surface, bold=True)
        )
        label = _text(node)
        canvas.draw_text(x + left + 4, y + top + 1, label, body, max_width=w - 6)


def legend(theme: Any) -> list[tuple[str, Style]]:
    """Return the legend as text pieces with their styles, in the order they are laid left to right."""
    states, bands = _colours(theme)
    muted = Style(foreground=theme.muted, background=theme.surface_alt)
    pieces: list[tuple[str, Style]] = []
    for state in STATES:
        glyph = "\u25c7" if state == "external" else "\u25cf"
        pieces.append((glyph + " ", Style(foreground=states[state], background=theme.surface_alt, bold=True)))
        pieces.append((state + "   ", muted))
    pieces.append(("messages ", muted))
    for index, (_, words) in enumerate(TIERS):
        pieces.append(("\u2501\u2501 ", Style(foreground=bands[index], background=theme.surface_alt, bold=True)))
        pieces.append((words + "  ", muted))
    return pieces
