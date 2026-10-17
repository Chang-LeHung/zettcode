"""The show the header plays for a switch to the top of the scale: light crossing the whole row, right to left.

Reaching ``max`` or ``ultra`` is the expensive thing a reader can do here, and the header marks it with an
animation of its own rather than the gauge every other switch gets (:mod:`.effort_gauge`). Light crosses the
header several times; the first pass ignites the right segment as it goes and the later ones glint over the
left. A frame is a value without a colour, like the gauge's: the painter chooses the colours from the theme.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: The levels at the top of the scale. Reaching one is the expensive thing a reader can do here, and the
#: header marks it with a show of its own rather than the gauge every other switch gets.
SHIMMER_LEVELS = frozenset({"max", "ultra"})

#: How fast the light crosses the header, in columns a second, pass by pass. It is a speed rather than a time,
#: because a time would send the light across a wide terminal at twice the pace it crosses a narrow one. The
#: first pass is the slowest, so there is time to watch it light the corner as it goes, and each later one is a
#: little quicker; the top of the scale gets one pass more. The pace is chosen against the frame: at 120 frames a
#: second the slowest pass moves the light about a cell per frame, which is what makes it read as one continuous
#: crossing rather than a light that sits still and then jumps a column — at half this pace most frames carried
#: no movement at all, which is the stutter a reader sees as jerky.
SHIMMER_SPEEDS: dict[str, tuple[float, ...]] = {
    "max": (110.0, 140.0, 170.0, 200.0),
    "ultra": (110.0, 140.0, 170.0, 200.0, 230.0),
}

#: How far across its trip a pass is when the next one sets off, so the light keeps coming. High enough that a
#: pass is still crossing when the next is well under way: the row carries light the whole time.
SHIMMER_OVERLAP = 0.5

#: Seconds the corner stays lit after the last pass has gone, before it hands the header back. It is a hold
#: rather than a fade of nothing: the corner keeps the light the first pass put on it, and the row would look
#: abandoned if it went straight back to the resting header the moment the last pass left.
SHIMMER_TAIL = 1.6

#: Seconds the row takes to arrive and to leave.
SHIMMER_FADE_IN_SECONDS = 0.25
SHIMMER_FADE_OUT_SECONDS = 0.8

#: Seconds the slowest pass is allowed to take, however wide the terminal: past this the light speeds up rather
#: than keep a very wide header waiting.
SHIMMER_LONGEST_PASS = 2.6

#: Half the width, in cells, of the light that crosses the header (its halo), and of the white-hot core inside it.
#: The halo is what makes the crossing visible at a glance; the core is the hot centre of it. The core is wide
#: enough to cover a few cells, so the glint is a band of light rather than a single cell that flickers.
SHIMMER_HALO = 8.0
SHIMMER_CORE = 4.0

#: Cells past either end of the row a pass starts and finishes, so the light enters and leaves.
SHIMMER_RUNWAY = 8

#: Twinkles either side of the word, by level, stepped this many times a second.
SHIMMER_SPARKS: dict[str, tuple[str, ...]] = {
    "max": ("\u2726", " ", "\u00b7", " "),
    "ultra": ("\u2726", "\u2727", "\u00b7", "\u2727"),
}
SHIMMER_SPARK_RATE = 14

#: Columns between the last gauge cell and the word's first letter (a gap, a sparkle, a gap), and after the word.
SHIMMER_BEFORE_WORD = 3
SHIMMER_AFTER_WORD = 2


def shimmer_schedule(level: str, reach: int) -> tuple[tuple[float, float], ...]:
    """Return when each pass of light is on, in seconds from the start of the show: ``(start, end)``.

    A pass crosses ``reach`` columns and its runway at its level's speed (but takes no longer than
    :data:`SHIMMER_LONGEST_PASS`, scaled by its speed), and the next sets off once this one is
    :data:`SHIMMER_OVERLAP` of the way across.
    """
    trip = reach + 2 * SHIMMER_RUNWAY
    windows = []
    start = 0.0
    slowest = SHIMMER_SPEEDS[level][0]
    for speed in SHIMMER_SPEEDS[level]:
        duration = min(trip / speed, SHIMMER_LONGEST_PASS * slowest / speed)
        windows.append((start, start + duration))
        start += duration * SHIMMER_OVERLAP
    return tuple(windows)


def shimmer_seconds(level: str, reach: int) -> float:
    """Return how long the show lasts for a header ``reach`` columns wide: the last pass, then the tail."""
    return shimmer_schedule(level, reach)[-1][1] + SHIMMER_TAIL


@dataclass(frozen=True, slots=True)
class ShimmerFrame:
    """One instant of the show a switch to the top of the scale plays in the header, without a colour.

    The row is ``model \u00b7 gauge  \u2726 word \u2726`` and every list here has one entry per column of it, from the
    first letter of the model's name to the last sparkle, so the painter lays them over the spans it draws. The
    width never changes during the show: the sparkles are always there, blank or not, so the right-aligned row
    does not shiver as they twinkle.

    Attributes:
        lead: Columns before the gauge: the model's name and the separator after it.
        cells: Cells in the gauge.
        lit_cells: How many of them the level reaches; the rest stay rail.
        word: The level being shown.
        glow: How much of the light's halo is on each column, ``0`` to ``1``.
        core: How much of its white-hot core is, ``0`` to ``1``; always at most the glow.
        ignited: Whether the first pass has gone over each column. The light travels right to left, so the
            columns it has left behind are the ones to the right of it.
        glitter: A fast twinkle on each column; nothing at ``max``, and on the lit part of the row at ``ultra``.
        sparks: The sparkle drawn left of the word and the one drawn right of it.
        heat: Where on the scale the level sits, ``0`` to ``1``; the colour ramp reads it.
        presence: How much of the show is there: it rises, holds and falls, and the painter blends every colour
            toward the resting header by what is missing.
        reach: Columns of the header the light crosses, from the right edge to the left one.
        bands: Where each pass of light is now, as its distance from the right edge.
    """

    lead: int
    cells: int
    lit_cells: int
    word: str
    glow: tuple[float, ...]
    core: tuple[float, ...]
    ignited: tuple[bool, ...]
    glitter: tuple[float, ...]
    sparks: tuple[str, str]
    heat: float
    presence: float
    reach: int
    bands: tuple[float, ...]

    @property
    def width(self) -> int:
        """Return the columns the row takes, which does not change from one frame to the next."""
        return len(self.glow)

    def light(self, distance: float) -> tuple[float, float]:
        """Return the halo and the core of the light at a column ``distance`` cells from the right edge.

        The right segment is described by :attr:`glow` and :attr:`core`; this is the same light for any other
        column of the header, which is how the left segment glints as the light goes over it.
        """
        halo = max((_profile(abs(distance - centre), SHIMMER_HALO) for centre in self.bands), default=0.0)
        core = max((_profile(abs(distance - centre), SHIMMER_CORE) for centre in self.bands), default=0.0)
        return halo, core

    @property
    def word_start(self) -> int:
        """Return the column the word's first letter is in."""
        return self.lead + self.cells + SHIMMER_BEFORE_WORD


def shimmer_width(lead: int, cells: int, word: str) -> int:
    """Return the columns of the show's row: the lead, the gauge, the word with its sparkles."""
    return lead + cells + SHIMMER_BEFORE_WORD + len(word) + SHIMMER_AFTER_WORD


def _profile(distance: float, half_width: float) -> float:
    """Return the brightness of light ``distance`` cells from its centre: a cosine, zero past its reach."""
    if distance >= half_width:
        return 0.0
    return 0.5 * (1 + math.cos(math.pi * distance / half_width))


def _centre(window: tuple[float, float], elapsed: float, reach: int) -> float | None:
    """Return where a pass of light is, as its distance from the right edge, or ``None`` when it is not on.

    It enters past the right edge and leaves past the left one, ``reach`` columns away. The ease is gentle — half
    a smooth step, half a straight line — so the light leans into the trip and out of it without the
    middle of the trip being much quicker than the pace the pass was given.
    """
    start, end = window
    if not start <= elapsed <= end:
        return None
    along = (elapsed - start) / (end - start)
    eased = 0.5 * along + 0.5 * along * along * (3 - 2 * along)
    return -SHIMMER_RUNWAY + eased * (reach + 2 * SHIMMER_RUNWAY)


def shimmer_frame(
    current: str,
    levels: Sequence[str],
    *,
    lead: int,
    reach: int,
    progress: float,
) -> ShimmerFrame | None:
    """Return the header's show for a switch to the top of the scale, ``progress`` of the way through it.

    Light crosses the whole header from right to left, several times: the first pass ignites the right segment,
    laying the gauge and the word down in the hot end of the scale's colours as it goes, and the later passes are
    a little quicker, each with a white-hot core inside a wide halo. They keep going over the left segment, so
    the whole row glints, not just the corner that changed. Sparkles twinkle either side of the word once it is
    lit. Everything is a function of ``progress``, the fraction of the show's time that has gone, so a slow
    terminal drops frames instead of stretching the show.

    Args:
        current: The level reached. One that is not at the top of the scale answers ``None``: the ordinary gauge
            is the animation for it.
        levels: The configured levels, cheapest first.
        lead: Columns of the right segment before the gauge, which the painter knows and this does not.
        reach: Columns of the header, which is how far the light travels and, at a fixed speed, how long the
            show lasts (:func:`shimmer_seconds`). At least as wide as the row itself.
        progress: ``0`` at the start through ``1`` at the end; outside that range the answer is ``None``, which
            is the caller's cue to release the frame loop.
    """
    if not 0.0 <= progress < 1.0 or current not in SHIMMER_LEVELS or current not in levels:
        return None
    count = len(levels)
    width = shimmer_width(lead, count, current)
    reach = max(reach, width)
    seconds = shimmer_seconds(current, reach)
    elapsed = progress * seconds
    schedule = shimmer_schedule(current, reach)
    target = levels.index(current)
    last = max(1, count - 1)
    bands = tuple(centre for window in schedule if (centre := _centre(window, elapsed, reach)) is not None)
    first = schedule[0]
    # The columns the first pass has gone over are the ones nearer the right edge than it is.
    first_centre = _centre(first, elapsed, reach)
    if first_centre is None:
        first_centre = -SHIMMER_RUNWAY if elapsed < first[0] else reach + SHIMMER_RUNWAY
    steps = int(elapsed * SHIMMER_SPARK_RATE)
    glow, core, ignited, glitter = [], [], [], []
    for column in range(width):
        distance = width - 1 - column
        glow.append(max((_profile(abs(distance - centre), SHIMMER_HALO) for centre in bands), default=0.0))
        core.append(max((_profile(abs(distance - centre), SHIMMER_CORE) for centre in bands), default=0.0))
        ignited.append(distance < first_centre)
        if current == "ultra" and distance < first_centre:
            twinkle = 0.5 + 0.5 * math.sin(elapsed * 31 + column * 2.3)
            glitter.append(max(0.0, twinkle - 0.62) / 0.38)
        else:
            glitter.append(0.0)
    sparks = SHIMMER_SPARKS[current]
    left_column = width - SHIMMER_AFTER_WORD - len(current) - 2
    right_column = width - 1
    left = sparks[steps % len(sparks)] if ignited[left_column] else " "
    right = sparks[(steps + 2) % len(sparks)] if ignited[right_column] else " "
    presence = min(1.0, elapsed / SHIMMER_FADE_IN_SECONDS, (seconds - elapsed) / SHIMMER_FADE_OUT_SECONDS)
    return ShimmerFrame(
        lead,
        count,
        target + 1,
        current,
        tuple(glow),
        tuple(core),
        tuple(ignited),
        tuple(glitter),
        (left, right),
        target / last,
        max(0.0, presence),
        reach,
        bands,
    )
