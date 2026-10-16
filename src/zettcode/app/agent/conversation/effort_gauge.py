"""The gauge the header plays when the reasoning effort changes: a hairline that fills, and a glow that travels.

A frame is a value without a colour: the cells, the word, and how bright the glow is on each. The painter turns
it into spans with the theme's colours, and the switch to the top of the scale has an animation of its own in
:mod:`.shimmer`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: How long the effort gauge plays after a switch. It is a function of time rather
#: than of a frame count, so it is as smooth as the loop that paints it and its
#: length is one number to tune: a switch at the top of the scale is worth a moment
#: of watching, and the gauge holds the corner for this one.
EFFORT_SECONDS = 3

#: Fraction of the second the fill takes to arrive; the rest is the glow leaving.
EFFORT_FILL_SHARE = 0.8

#: Half the width, in cells, of the glow that travels over the gauge and over the
#: word. Its brightness falls off as a cosine, so it has no edge.
EFFORT_GLOW_HALF_WIDTH = 3.5

#: Cells past either end the glow travels, so it enters and leaves rather than
#: appearing on the first cell.
EFFORT_GLOW_RUNWAY = 4

#: Fractions of the second the gauge takes to arrive and to leave. Both are short
#: and the leaving one is longer: a thing that appears should be there at once, and
#: one that goes should be allowed to go, or the header jumps back to plain text.
EFFORT_FADE_IN = 0.12
EFFORT_FADE_OUT = 0.25


@dataclass(frozen=True, slots=True)
class GaugeCell:
    """One cell of the effort gauge, described without a colour.

    Attributes:
        char: The glyph: a full rule, a half rule for the leading edge, or the
            faint rail that has not been reached.
        heat: Where on the scale this cell sits, ``0`` at the cheapest level and
            ``1`` at the dearest; the colour ramp reads it.
        glow: How much of the travelling highlight is on this cell, ``0`` to ``1``.
        lit: Whether the fill has reached it; an unlit cell is rail.
    """

    char: str
    heat: float
    glow: float
    lit: bool


@dataclass(frozen=True, slots=True)
class EffortFrame:
    """One instant of the effort gauge: its cells and the word beside them.

    ``presence`` is how much of the gauge is there: it rises from nothing, holds,
    and falls back to nothing, and the painter blends every colour toward the
    resting header by what is missing, so the gauge fades in and out instead of
    appearing and vanishing between one frame and the next.
    """

    cells: tuple[GaugeCell, ...]
    word: str
    word_heat: float
    word_glow: tuple[float, ...]
    presence: float


def _glow(position: float, centre: float) -> float:
    """Return the highlight's brightness at a position: a cosine, zero past its reach."""
    distance = abs(position - centre)
    if distance >= EFFORT_GLOW_HALF_WIDTH:
        return 0.0
    return 0.5 * (1 + math.cos(math.pi * distance / EFFORT_GLOW_HALF_WIDTH))


def effort_frame(previous: str, current: str, levels: Sequence[str], *, progress: float) -> EffortFrame | None:
    """Return the effort gauge ``progress`` of the way through a switch.

    The gauge is a hairline with one cell per level. The fill eases out from the
    level being left to the level chosen, so a jump of four rungs travels four
    times as far as a nudge and a step down wipes back. Its colour is a property
    of *where* a cell sits on the scale rather than of what is being switched to:
    the cheap end is the accent, the dear end is warm, and the word beside it takes
    the heat of the level it names — so the position of the fill and the colour of
    the word say the same thing twice, and `ultra` is the one that is red.

    A soft highlight travels over the gauge and then over the word, a cosine of its
    distance rather than a window with edges, which is what keeps it from looking
    like a progress bar.

    Args:
        previous: Level the switch came from; an unknown name starts from empty.
        current: Level being reached; an unknown name answers ``None``.
        levels: The configured levels, cheapest first.
        progress: ``0`` at the start through ``1`` at the end; outside that range
            there is nothing to draw and the answer is ``None``, which is the
            caller's cue to release the frame loop.

    Returns:
        The cells and the word, or ``None`` when there is nothing to animate.
    """
    if not 0.0 <= progress < 1.0 or not levels or current not in levels:
        return None
    count = len(levels)
    target = levels.index(current)
    source = levels.index(previous) if previous in levels else -1
    arrived = 1 - (1 - min(1.0, progress / EFFORT_FILL_SHARE)) ** 3
    reach = (source + 1) + (target - source) * arrived
    span = count + 2 * EFFORT_GLOW_RUNWAY + len(current) + 1
    sweep = -EFFORT_GLOW_RUNWAY + progress * span
    last = max(1, count - 1)
    cells = []
    for index in range(count):
        fill = max(0.0, min(1.0, reach - index))
        lit = fill > 0.45
        char = "\u2501" if fill >= 1.0 else "\u2578" if lit else "\u2500"
        cells.append(GaugeCell(char, index / last, _glow(index, sweep) if lit else 0.0, lit))
    word_glow = tuple(_glow(count + 1 + offset, sweep) for offset in range(len(current)))
    presence = min(1.0, progress / EFFORT_FADE_IN, (1.0 - progress) / EFFORT_FADE_OUT)
    return EffortFrame(tuple(cells), current, target / last, word_glow, max(0.0, presence))
