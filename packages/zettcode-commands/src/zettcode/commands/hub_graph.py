"""The picture on ``/hub``'s first tab: sessions as boxes, messages as lines, one colour per state.

Nothing here reads anything. :func:`build` turns the broker's graph into :class:`Node` and :class:`Link` values;
:func:`layout` ranks the nodes by how much they talk, keeps as many of the busiest as fit the rectangle without
touching, puts the reader's own session in the middle with the rest on a ring, and routes every line around the boxes
it does not belong to; :func:`paint` draws the result, and may be called again with another node selected without
routing anything again.

How a line is drawn:

* It leaves one box at the middle of a side and enters the other the same way, in right angles with rounded corners,
  and joins the lines it meets (``├ ┬ ┼ ...``). It is found by A* over the character grid: a step down costs twice a
  step across (a cell is about twice as tall as it is wide), a turn costs, and a cell another line already uses costs
  more, so lines keep apart where they can.
* Its number is the messages the two exchanged, both ways, written beside the end it is drawn from: the other end
  than the reader's own session, otherwise the busier one. The line has the colour of that end's state, so the number
  and the colour say whose line it is.
* With a node selected its lines stay as they are and everything else is dimmed.

A state has one colour; the legend says which. They are the theme's own, so a palette change recolours the picture, and
the two lists use the same colours for the same words.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from zettcode.tui import Canvas, Theme
from zettcode.tui.render import Style, display_width, truncate

__all__ = [
    "BOX_HEIGHT",
    "MAX_NODES",
    "STATES",
    "Link",
    "Node",
    "Picture",
    "State",
    "build",
    "colours",
    "glyph",
    "layout",
    "legend",
    "nearest",
    "paint",
    "state_of",
    "summary",
]

State = Literal["working", "idle", "external", "offline", "stopped"]

#: The states a node can be in, in the order the legend lists them.
STATES: tuple[State, ...] = ("working", "idle", "external", "offline", "stopped")

#: How many nodes the picture draws at most, and how many lines; more is a smear.
MAX_NODES = 16
MAX_LINKS = 40

#: A box is this many rows tall, and at most this many columns wide, label included.
BOX_HEIGHT = 3
MAX_BOX = 24

# A cell of line is the set of sides it joins: these bits, and the glyph each set is drawn as.
_N, _E, _S, _W = 1, 2, 4, 8
_DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))
_BITS = (_N, _E, _S, _W)
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

Cell = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Node:
    """One session, daemon or outsider the picture shows."""

    key: str
    label: str
    state: State
    me: bool = False


@dataclass(frozen=True, slots=True)
class Link:
    """Two nodes that exchanged messages, and how many."""

    a: str
    b: str
    count: int


@dataclass(frozen=True, slots=True)
class Route:
    """One line: its link, the end it is numbered at, and the cells it runs through."""

    link: Link
    origin: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Picture:
    """A laid-out graph: what is drawn, where, and what was left out.

    Attributes:
        nodes: The nodes drawn, busiest first and the reader's own at the head.
        boxes: Each drawn node's box as ``(left, top, width)``.
        routes: The lines, strongest first.
        cells: For each cell a line runs through, which routes and which sides of the cell each joins.
        labels: ``(x, y, text, route index)`` for each number that found a place.
        hidden_nodes: How many nodes did not fit.
        hidden_links: How many lines were left out, because an end is hidden or there were too many.
        undrawn: How many of those join two drawn nodes: only the strongest :data:`MAX_LINKS` are routed, and a line
            with no way round the boxes is not drawn either.
        unnumbered: How many drawn lines found no place to write their number.
        width: The rectangle's size, which the picture is valid for.
        height: The rectangle's height.
    """

    nodes: tuple[Node, ...] = ()
    boxes: Mapping[str, tuple[int, int, int]] = field(default_factory=dict)
    routes: tuple[Route, ...] = ()
    cells: Mapping[Cell, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    labels: tuple[tuple[int, int, str, int], ...] = ()
    hidden_nodes: int = 0
    hidden_links: int = 0
    undrawn: int = 0
    unnumbered: int = 0
    width: int = 0
    height: int = 0


def state_of(status: str, kind: str) -> State:
    """Return the state a roster entry (or a daemon's status) is drawn in."""
    if kind == "external":
        return "external"
    return "working" if status == "working" else "idle"


def glyph(state: str) -> str:
    """Return the mark in front of a state: a diamond for an outsider, a dot for the rest."""
    return "\u25c7" if state == "external" else "\u25cf"


def colours(theme: Theme) -> dict[str, str]:
    """Return the colour of each state, from the theme: working is the accent, a stopped one the error colour."""
    return {
        "working": theme.accent,
        "idle": theme.subtle,
        "external": theme.warning,
        "offline": theme.muted,
        "stopped": theme.error,
    }


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
        stopped: Ids of daemons of this workspace whose process is gone.
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
                state: State = "stopped" if key in gone else "offline"
                nodes[key] = Node(key, names.get(key) or key[:8], state, key == me)
        links.append(Link(a, b, int(edge.get("count", 1))))
    for key in gone:
        if key not in nodes and key in names:
            nodes[key] = Node(key, names[key], "stopped", key == me)
    return tuple(nodes.values()), tuple(links)


# -- ranking and placing ----------------------------------------------------------------------------


def _text(node: Node) -> str:
    """Return what a box says: the label, and ``(you)`` after the reader's own."""
    return node.label + (" (you)" if node.me else "")


def _box(node: Node) -> int:
    """Return the width of a node's box: its glyph, its label and a column of air on both sides."""
    return min(MAX_BOX, display_width(_text(node)) + 6)


def _totals(links: Sequence[Link]) -> dict[str, int]:
    """Return the messages each node is part of."""
    total: dict[str, int] = {}
    for link in links:
        total[link.a] = total.get(link.a, 0) + link.count
        total[link.b] = total.get(link.b, 0) + link.count
    return total


def rank(nodes: Sequence[Node], links: Sequence[Link]) -> list[Node]:
    """Return the nodes busiest first, the reader's own at the head whatever it has said."""
    total = _totals(links)
    order = sorted(range(len(nodes)), key=lambda i: (not nodes[i].me, -total.get(nodes[i].key, 0), i))
    return [nodes[i] for i in order]


def _ring_order(nodes: Sequence[Node], links: Sequence[Link]) -> list[Node]:
    """Return the nodes around the ring so that talkers sit next to each other where they can."""
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


def _spots(
    shown: Sequence[Node], links: Sequence[Link], width: int, height: int, *, whole_rows: bool = False
) -> dict[str, Cell]:
    """Return the centre of each node's box: the reader's own in the middle, the rest on an ellipse round it.

    The ellipse's vertical radius is half a row when the height is even, and rounding a ring box onto a half row can
    push its last row onto the edge; ``whole_rows`` takes the radius down to a whole number of rows instead.
    """
    cx, cy = width // 2, height // 2
    if len(shown) == 1:
        return {shown[0].key: (cx, cy)}
    if len(shown) == 2:
        first, second = shown
        w1, w2 = _box(first), _box(second)
        return {
            first.key: (max(width // 4, 1 + (w1 + 1) // 2), cy),
            second.key: (min(width - width // 4, width - 1 - (w2 + 1) // 2), cy),
        }
    centre = next((node for node in shown if node.me), None)
    ring = _ring_order([node for node in shown if node is not centre], links)
    widest = max(_box(node) for node in shown)
    rx = max(1.0, (width - widest) / 2 - 1)
    ry = max(1.0, (height - BOX_HEIGHT) / 2 - 1)
    if whole_rows:
        ry = float(max(1, int(ry)))
    spots: dict[str, Cell] = {}
    if centre is not None:
        spots[centre.key] = (cx, cy)
    for index, node in enumerate(ring):
        angle = -math.pi / 2 + 2 * math.pi * index / len(ring)
        spots[node.key] = (round(cx + rx * math.cos(angle)), round(cy + ry * math.sin(angle)))
    return spots


def _rects(shown: Sequence[Node], spots: Mapping[str, Cell]) -> dict[str, tuple[int, int, int]]:
    """Return each box as ``(left, top, width)`` from its centre."""
    return {
        node.key: (spots[node.key][0] - _box(node) // 2, spots[node.key][1] - BOX_HEIGHT // 2, _box(node))
        for node in shown
    }


def _clear(boxes: Mapping[str, tuple[int, int, int]], width: int, height: int) -> bool:
    """Return whether every box is inside the rectangle with a cell to spare and a free lane to the next one."""
    rects = list(boxes.values())
    for left, top, w in rects:
        if left < 1 or top < 1 or left + w > width - 1 or top + BOX_HEIGHT > height - 1:
            return False
    for index, (al, at, aw) in enumerate(rects):
        for bl, bt, bw in rects[index + 1 :]:
            if al - 1 < bl + bw and bl < al + aw + 1 and at - 1 < bt + BOX_HEIGHT and bt < at + BOX_HEIGHT + 1:
                return False
    return True


# -- routing ----------------------------------------------------------------------------------------


def _ports(box: tuple[int, int, int], toward: Cell) -> list[tuple[Cell, int, int]]:
    """Return the cells a line may start from or end in: the cell, the side that points into the box, and a penalty.

    A side that faces away from ``toward`` costs extra, so a line leaves by the side nearest the box it goes to and
    only goes round when that side is taken.
    """
    left, top, w = box
    middle = top + BOX_HEIGHT // 2
    centre = left + w // 2
    dx, dy = toward[0] - centre, toward[1] - middle
    # A cell is about twice as tall as wide, so a vertical offset counts double.
    horizontal = abs(dx) >= 2 * abs(dy)
    return [
        ((left - 1, middle), _E, 0 if dx < 0 and horizontal else 6 if dx < 0 else 14),
        ((left + w, middle), _W, 0 if dx > 0 and horizontal else 6 if dx > 0 else 14),
        ((centre, top - 1), _S, 0 if dy < 0 and not horizontal else 6 if dy < 0 else 14),
        ((centre, top + BOX_HEIGHT), _N, 0 if dy > 0 and not horizontal else 6 if dy > 0 else 14),
    ]


def _search(
    starts: list[tuple[Cell, int, int]],
    ends: list[tuple[Cell, int, int]],
    blocked: set[Cell],
    used: Mapping[Cell, int],
    halo: Mapping[Cell, frozenset[str]],
    allowed: frozenset[str],
    width: int,
    height: int,
) -> tuple[list[Cell], int, int] | None:
    """Return the cheapest path between two boxes as its cells and the two sides that point into the boxes.

    A step across costs 1 and a step down 2, a turn 4, a cell a parallel line already runs through 6 and a crossing
    2, and a cell beside a box that is not one of the two 2, which keeps a line off the borders it passes.
    """
    goals = {cell: (bit, penalty) for cell, bit, penalty in ends}

    def heuristic(x: int, y: int) -> int:
        return min(abs(x - gx) + 2 * abs(y - gy) for gx, gy in goals)

    heap: list[tuple[int, int, int, int, int, int]] = []
    best: dict[tuple[int, int, int], int] = {}
    parent: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    first: dict[tuple[int, int, int], int] = {}
    tick = 0
    for (x, y), bit, penalty in starts:
        if not (0 <= x < width and 0 <= y < height) or (x, y) in blocked:
            continue
        outward = (_BITS.index(bit) + 2) % 4
        state = (x, y, outward)
        best[state] = penalty
        parent[state] = None
        first[state] = bit
        heapq.heappush(heap, (penalty + heuristic(x, y), penalty, tick, x, y, outward))
        tick += 1
    expanded = 0
    while heap:
        _, cost, _, x, y, d = heapq.heappop(heap)
        if cost > best.get((x, y, d), cost):
            continue
        if (x, y) in goals:
            cells: list[Cell] = []
            walk: tuple[int, int, int] | None = (x, y, d)
            start_bit = 0
            while walk is not None:
                cells.append((walk[0], walk[1]))
                start_bit = first.get(walk, start_bit)
                walk = parent[walk]
            cells.reverse()
            return cells, start_bit, goals[(x, y)][0]
        expanded += 1
        if expanded > 30000:
            return None
        for nd, (dx, dy) in enumerate(_DIRS):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in blocked:
                continue
            axis = 1 if nd in (1, 3) else 2
            step = 1 if axis == 1 else 2
            step += 0 if nd == d else 4
            seen = used.get((nx, ny), 0)
            if seen & axis:
                step += 6
            elif seen:
                step += 2
            if halo.get((nx, ny), frozenset()) - allowed:
                step += 2
            if (nx, ny) in goals:
                step += goals[(nx, ny)][1]
            total = cost + step
            state = (nx, ny, nd)
            if total < best.get(state, 1 << 30):
                best[state] = total
                parent[state] = (x, y, d)
                heapq.heappush(heap, (total + heuristic(nx, ny), total, tick, nx, ny, nd))
                tick += 1
    return None


def _centre(box: tuple[int, int, int]) -> Cell:
    """Return the middle cell of a box."""
    return box[0] + box[2] // 2, box[1] + BOX_HEIGHT // 2


def _sides(cells: Sequence[Cell], start_bit: int, end_bit: int) -> list[int]:
    """Return which sides of each cell the path joins, the first and last also reaching into their boxes."""
    out = []
    for index, here in enumerate(cells):
        bits = 0
        for other in (cells[index - 1] if index else None, cells[index + 1] if index + 1 < len(cells) else None):
            if other is None:
                continue
            dx, dy = other[0] - here[0], other[1] - here[1]
            bits |= _E if dx > 0 else _W if dx < 0 else _S if dy > 0 else _N
        if index == 0:
            bits |= start_bit
        if index == len(cells) - 1:
            bits |= end_bit
        out.append(bits)
    return out


def _origin(link: Link, nodes: Mapping[str, Node], total: Mapping[str, int]) -> str:
    """Return the end a line is numbered at: not the reader's own session, else the busier one."""
    a, b = nodes[link.a], nodes[link.b]
    if a.me != b.me:
        return b.key if a.me else a.key
    return a.key if total.get(a.key, 0) >= total.get(b.key, 0) else b.key


def layout(nodes: Sequence[Node], links: Sequence[Link], width: int, height: int) -> Picture:
    """Lay the graph out in a ``width`` by ``height`` rectangle.

    The busiest nodes are kept, as many as fit on one ellipse with a lane left between every two boxes (a count that
    does not fit by a row is dropped, and the next smaller is tried); the rest are counted in ``hidden_nodes``.
    Only the strongest :data:`MAX_LINKS` lines are routed, strongest first so the busy ones get the straightest paths;
    those left out between two drawn nodes are counted in ``undrawn``.
    """
    if not nodes or width <= 0 or height <= 0:
        return Picture(width=width, height=height, hidden_nodes=len(nodes), hidden_links=len(links))
    ranked = rank(nodes, links)
    shown: list[Node] = []
    spots: dict[str, Cell] = {}
    boxes: dict[str, tuple[int, int, int]] = {}
    for count in range(min(MAX_NODES, len(ranked)), 0, -1):
        shown = ranked[:count]
        for whole_rows in (False, True):
            spots = _spots(shown, links, width, height, whole_rows=whole_rows)
            boxes = _rects(shown, spots)
            if _clear(boxes, width, height):
                break
        else:
            continue
        break
    else:
        return Picture(width=width, height=height, hidden_nodes=len(nodes), hidden_links=len(links))

    by_key = {node.key: node for node in shown}
    total = _totals(links)
    inside = [link for link in links if link.a in by_key and link.b in by_key]
    inside.sort(key=lambda link: -link.count)
    owner = {
        (x, y): key
        for key, (left, top, w) in boxes.items()
        for x in range(left, left + w)
        for y in range(top, top + BOX_HEIGHT)
    }
    blocked = set(owner)
    halo: dict[Cell, frozenset[str]] = {}
    for key, (left, top, w) in boxes.items():
        for x in range(left - 1, left + w + 1):
            for y in range(top - 1, top + BOX_HEIGHT + 1):
                if (x, y) not in blocked:
                    halo[(x, y)] = halo.get((x, y), frozenset()) | {key}

    used: dict[Cell, int] = {}
    routes: list[Route] = []
    cells: dict[Cell, list[tuple[int, int]]] = {}
    for link in inside[:MAX_LINKS]:
        origin = _origin(link, by_key, total)
        other = link.b if origin == link.a else link.a
        found = _search(
            _ports(boxes[origin], _centre(boxes[other])),
            _ports(boxes[other], _centre(boxes[origin])),
            blocked,
            used,
            halo,
            frozenset((link.a, link.b)),
            width,
            height,
        )
        if found is None:
            continue
        path, start_bit, end_bit = found
        index = len(routes)
        routes.append(Route(link, origin, tuple(path)))
        for cell, sides in zip(path, _sides(path, start_bit, end_bit), strict=True):
            cells.setdefault(cell, []).append((index, sides))
            used[cell] = used.get(cell, 0) | (1 if sides & (_E | _W) else 0) | (2 if sides & (_N | _S) else 0)
    labels = _place_labels(routes, cells, owner, width, height)
    return Picture(
        nodes=tuple(shown),
        boxes=boxes,
        routes=tuple(routes),
        cells={cell: tuple(parts) for cell, parts in cells.items()},
        labels=tuple(labels),
        hidden_nodes=len(nodes) - len(shown),
        hidden_links=len(links) - len(routes),
        undrawn=len(inside) - len(routes),
        unnumbered=len(routes) - len(labels),
        width=width,
        height=height,
    )


def _place_labels(
    routes: Sequence[Route],
    cells: Mapping[Cell, Sequence[tuple[int, int]]],
    owner: Mapping[Cell, str],
    width: int,
    height: int,
) -> list[tuple[int, int, str, int]]:
    """Put each line's number on its own line close to the end it is drawn from, or beside it, where nothing else is.

    On the line it replaces a straight stretch only (never a corner, never the cell that joins the box at the far
    end). Beside it, any side of any of the first cells will do, including the first, so a line of one cell still gets
    its number. A number is never written over a box, over a cell any line runs through or over another number, and
    it never touches a box other than the one the line is drawn from, where it would read as that box's own.
    """
    taken: set[Cell] = set()
    out: list[tuple[int, int, str, int]] = []

    def free(spot: set[Cell], origin: str) -> bool:
        for x, y in spot:
            if not (0 <= x < width and 0 <= y < height) or (x, y) in owner or (x, y) in cells or (x, y) in taken:
                return False
            if any(owner.get(near, origin) != origin for near in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))):
                return False
        return True

    for index, route in enumerate(routes):
        text = f" {route.link.count} "
        path = route.cells
        placed = False
        for start in range(1, len(path) - len(text)):
            run = path[start : start + len(text)]
            straight = all(cell[1] == run[0][1] for cell in run) and all(
                abs(run[i + 1][0] - run[i][0]) == 1 for i in range(len(run) - 1)
            )
            if not straight or any(cell in taken or dict(cells[cell])[index] != _E | _W for cell in run):
                continue
            if any(len(cells[cell]) != 1 for cell in run):
                continue
            out.append((min(cell[0] for cell in run), run[0][1], text, index))
            taken.update(run)
            placed = True
            break
        if placed:
            continue
        number = str(route.link.count)
        for cell_x, cell_y in path[:12]:
            for left, top in (
                (cell_x + 1, cell_y),
                (cell_x - len(number), cell_y),
                (cell_x, cell_y - 1),
                (cell_x, cell_y + 1),
            ):
                spot = {(left + i, top) for i in range(len(number))}
                if free(spot, route.origin):
                    out.append((left, top, number, index))
                    taken |= spot
                    placed = True
                    break
            if placed:
                break
    return out


# -- painting ---------------------------------------------------------------------------------------


def paint(canvas: Canvas, theme: Theme, x: int, y: int, picture: Picture, selected: str | None = None) -> None:
    """Paint a laid-out graph with its top left corner at ``(x, y)``; ``selected`` keeps its lines and dims the rest."""
    if not picture.nodes:
        return
    states = colours(theme)
    by_key = {node.key: node for node in picture.nodes}
    page = theme.surface_alt

    def lit(route: Route) -> bool:
        return selected is None or selected in (route.link.a, route.link.b)

    def colour_of(route: Route) -> str:
        return states[by_key[route.origin].state] if lit(route) else theme.border

    for (cell_x, cell_y), parts in picture.cells.items():
        # The glyph keeps every line through the cell, so a dimmed line is not cut where a bright one crosses it; the
        # colour is a bright line's when there is one.
        bits = 0
        for _, sides in parts:
            bits |= sides
        owner_route = next((index for index, _ in parts if lit(picture.routes[index])), parts[0][0])
        if bits in _JOINS:
            style = Style(foreground=colour_of(picture.routes[owner_route]), background=page)
            canvas.set_cell(x + cell_x, y + cell_y, _JOINS[bits], style)
    for left, top, text, index in picture.labels:
        route = picture.routes[index]
        canvas.draw_text(x + left, y + top, text, Style(foreground=colour_of(route), background=page, bold=lit(route)))

    near = {selected} if selected is not None else set()
    for route in picture.routes:
        if selected in (route.link.a, route.link.b):
            near.update((route.link.a, route.link.b))
    for node in picture.nodes:
        left, top, w = picture.boxes[node.key]
        colour = states[node.state]
        chosen = node.key == selected
        dim = selected is not None and node.key not in near
        fill = theme.selection if chosen else theme.surface
        edge = Style(
            foreground=theme.border if dim else colour,
            background=fill,
            bold=chosen or node.me or node.state == "working",
        )
        body = Style(foreground=theme.muted if dim else theme.text, background=fill, bold=node.me or chosen)
        canvas.fill(x + left, y + top, w, BOX_HEIGHT, Style(background=fill))
        if node.me or chosen:
            tl, tr, bl, br, bar, side = "\u2554", "\u2557", "\u255a", "\u255d", "\u2550", "\u2551"
        else:
            tl, tr, bl, br, bar, side = "\u256d", "\u256e", "\u2570", "\u256f", "\u2500", "\u2502"
        canvas.draw_text(x + left, y + top, tl + bar * (w - 2) + tr, edge)
        canvas.draw_text(x + left, y + top + 2, bl + bar * (w - 2) + br, edge)
        canvas.draw_text(x + left, y + top + 1, side, edge)
        canvas.draw_text(x + left + w - 1, y + top + 1, side, edge)
        canvas.draw_text(
            x + left + 2, y + top + 1, glyph(node.state), Style(foreground=colour, background=fill, bold=True)
        )
        canvas.draw_text(x + left + 4, y + top + 1, truncate(_text(node), w - 6), body, max_width=w - 6)


#: The step an arrow key takes on the picture, as (columns, rows).
_ARROWS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}


def nearest(picture: Picture, selected: str | None, direction: str) -> str | None:
    """Return the node to select when an arrow key is pressed, or ``None`` when there is none that way.

    Every node has a place, so an arrow goes to the node nearest in that direction: of those ahead of the selected
    one it takes the one with the least distance along the arrow plus twice the distance across it, preferring
    those inside a cone of about 60 degrees either side, and falling back to any that lies ahead. A row is about
    twice as tall as a column is wide, so rows count double. With nothing selected the first arrow selects the
    reader's own session, which comes first.
    """
    if not picture.nodes:
        return None
    if selected is None or selected not in picture.boxes:
        return picture.nodes[0].key
    step_x, step_y = _ARROWS[direction]
    # Everything below is in columns: a row is about twice as tall as a column is wide, so a row is two units. That
    # one unit is used for the cone and for the score, which is what makes up and down behave like left and right.
    left, top, width = picture.boxes[selected]
    here_x, here_y = left + width / 2, (top + BOX_HEIGHT / 2) * 2
    best: dict[bool, tuple[float, str]] = {}
    for node in picture.nodes:
        if node.key == selected:
            continue
        left, top, width = picture.boxes[node.key]
        dx, dy = left + width / 2 - here_x, (top + BOX_HEIGHT / 2) * 2 - here_y
        ahead = dx * step_x + dy * step_y
        across = abs(dx * step_y) + abs(dy * step_x)
        if ahead <= 0:
            continue
        inside = across <= 1.7 * ahead
        score = (ahead + 2 * across, node.key)
        if inside not in best or score < best[inside]:
            best[inside] = score
    chosen = best.get(True) or best.get(False)
    return chosen[1] if chosen else None


def summary(nodes: Sequence[Node], links: Sequence[Link], picture: Picture, selected: str | None = None) -> str:
    """Return the line over the picture: what the whole graph holds, or what the selected node is part of."""
    chosen = next((node for node in nodes if node.key == selected), None)
    if chosen is not None:
        mine = [link for link in links if selected in (link.a, link.b)]
        drawn = sum(1 for route in picture.routes if selected in (route.link.a, route.link.b))
        shown = f"{drawn}" if drawn == len(mine) else f"{drawn} of {len(mine)}"
        return (
            f"{glyph(chosen.state)} {_text(chosen)} \u00b7 {chosen.state} \u00b7 "
            f"{shown} {'line' if len(mine) == 1 else 'lines'} \u00b7 {sum(link.count for link in mine)} messages"
        )
    working = sum(1 for node in nodes if node.state == "working")
    text = f"{len(nodes)} nodes \u00b7 {working} working \u00b7 {sum(link.count for link in links)} messages"
    if picture.hidden_nodes:
        text += f" \u00b7 {picture.hidden_nodes} quieter not drawn"
    if picture.undrawn:
        text += f" \u00b7 {picture.undrawn} lines not drawn"
    if picture.unnumbered:
        text += f" \u00b7 {picture.unnumbered} without a number"
    return text


def legend(theme: Theme) -> list[list[tuple[str, Style]]]:
    """Return the legend as groups of styled text, what a number means first.

    A group is drawn whole or not at all, so a narrow page drops the last state rather than half of it.
    """
    states = colours(theme)
    muted = Style(foreground=theme.muted, background=theme.surface_alt)
    groups = [[("n = messages  ", muted)]]
    for state in STATES:
        groups.append(
            [
                (glyph(state) + " ", Style(foreground=states[state], background=theme.surface_alt, bold=True)),
                (state + "  ", muted),
            ]
        )
    return groups
