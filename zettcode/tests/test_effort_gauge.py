"""The row vocabulary: the shapes a transcript row and the header's gauge are written in."""

from __future__ import annotations

import pytest

from zettcode.app.agent.conversation.effort_gauge import EFFORT_GLOW_HALF_WIDTH, EffortFrame, effort_frame

LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def _lit(frame: EffortFrame) -> int:
    return sum(cell.lit for cell in frame.cells)


def _frames(previous: str, current: str, steps: int = 40) -> list[EffortFrame]:
    result = [effort_frame(previous, current, LEVELS, progress=step / steps) for step in range(steps)]
    assert all(frame is not None for frame in result)
    return [frame for frame in result if frame is not None]


def test_the_fill_travels_from_the_level_left_to_the_level_chosen():
    """A gauge, not a spinner: where the fill is says the level, and its direction the move.

    The word alone says which level is in force; the fill also says whether the
    effort went up or down and how far, which is what a reader who just changed it
    wants to see.
    """
    up = [_lit(frame) for frame in _frames("low", "ultra")]
    down = [_lit(frame) for frame in _frames("ultra", "low")]

    assert up == sorted(up), "going up only ever fills"
    assert down == sorted(down, reverse=True), "going down wipes back"
    assert up[0] <= LEVELS.index("low") + 2, "from the level it came from"
    assert up[-1] == len(LEVELS), "to the top of the scale"
    assert down[-1] == LEVELS.index("low") + 1, "and back to the level chosen"


def test_an_unknown_previous_level_fills_from_empty():
    """There is no rung to have come from, so the gauge starts from nothing."""
    first = effort_frame("an old name", "high", LEVELS, progress=0.0)

    assert first is not None
    assert _lit(first) == 0


def test_colour_is_a_position_on_the_scale_not_a_direction():
    """The heat of a cell and of the word depend on where they are, not on the move.

    The cheap end is one colour and the dear end another, whichever way the effort
    was going; the word takes the heat of the level it names, so the fill and the
    word say the same thing twice.
    """
    one = effort_frame("off", "ultra", LEVELS, progress=0.5)
    other = effort_frame("max", "ultra", LEVELS, progress=0.5)

    assert one is not None and other is not None
    assert [cell.heat for cell in one.cells] == [cell.heat for cell in other.cells]
    assert one.cells[0].heat == 0.0 and one.cells[-1].heat == 1.0
    assert one.word_heat == other.word_heat == 1.0
    low = effort_frame("high", "low", LEVELS, progress=0.5)
    assert low is not None and low.word_heat == LEVELS.index("low") / (len(LEVELS) - 1)


def test_the_glow_travels_and_has_no_edge():
    """A soft highlight moves over the gauge and then the word, falling off as a cosine."""
    frames = _frames("off", "ultra")
    centres = []
    for frame in frames:
        cells = [(cell.glow, index) for index, cell in enumerate(frame.cells) if cell.lit]
        centres.append(max(cells)[1] if cells else -1)

    assert centres == sorted(centres), "the glow only ever moves forward"
    assert all(0.0 <= cell.glow <= 1.0 for frame in frames for cell in frame.cells)
    # No edge: neighbouring cells differ by less than the whole range, except where
    # the lit part of the gauge ends.
    steps = [
        abs(left.glow - right.glow)
        for frame in frames
        for left, right in zip(frame.cells, frame.cells[1:], strict=False)
        if left.lit and right.lit
    ]
    assert max(steps) < 0.9, "a window with an edge would jump from dark to bright in one cell"
    assert EFFORT_GLOW_HALF_WIDTH > 2, "and it is wide enough to read as a glow rather than a spark"
    assert any(glow > 0 for frame in frames for glow in frame.word_glow), "the word is lit too"


def test_the_gauge_fades_in_and_out_instead_of_cutting():
    """It arrives from nothing, holds, and leaves toward nothing."""
    start = effort_frame("low", "high", LEVELS, progress=0.0)
    middle = effort_frame("low", "high", LEVELS, progress=0.5)
    end = effort_frame("low", "high", LEVELS, progress=0.99)

    assert start is not None and middle is not None and end is not None
    assert start.presence == 0.0
    assert middle.presence == 1.0
    assert 0.0 <= end.presence < 0.1, "the last frame is nearly the plain header"


@pytest.mark.parametrize("progress", [-0.1, 1.0, 1.5])
def test_outside_its_second_there_is_nothing_to_draw(progress):
    """The caller reads None as the cue to release the frame loop."""
    assert effort_frame("low", "high", LEVELS, progress=progress) is None


def test_a_level_the_scale_does_not_hold_is_not_animated():
    """An unknown level has no rung to fill, and no levels have no scale."""
    assert effort_frame("low", "enormous", LEVELS, progress=0.5) is None
    assert effort_frame("low", "high", (), progress=0.5) is None
