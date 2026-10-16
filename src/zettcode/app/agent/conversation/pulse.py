"""How the waiting row and the status bar's icon move: the pulse, the sweep, and the blink.

Everything here is a function of one monotonic frame counter the application keeps, counted in animation
steps rather than terminal ticks, so the pace of the sweep and of the running marker does not depend on how
often the terminal happens to repaint: a period is a number of seconds, and a step is a share of it.
"""

from __future__ import annotations

from ....tui import RUNNING

#: Animation steps per second: the rate the sweep, the running marker and the
#: timers advance at, matching the frame loop's own ceiling. It used to be ten a
#: second, which is a step the eye can see — the sweep moved in jumps — while the
#: loop was repainting a hundred and twenty times a second to show the same
#: picture twelve times over.
ANIMATION_FPS = 120

#: Wall-clock length of one animation step. ``Transcript.frame`` counts these
#: steps rather than terminal ticks, so the pace of the sweep and the running
#: marker does not depend on how often the terminal happens to repaint: a period
#: is a number of seconds, and a step is a share of it.
ANIMATION_SECONDS = 1 / ANIMATION_FPS

#: The running marker's two states: the sparkle, then a dot of the same width so
#: the label after it never shifts as the row pulses.
RUNNING_GLYPHS = RUNNING

#: Seconds one pulse of the waiting row takes: it moves for a second, then rests
#: for a second before it moves again. The marker and the highlight share the
#: period, so the row reads as one thing breathing instead of two effects on
#: clocks of their own. The rest is deliberate: a row that never stops reads as
#: busy-work, and the pause is what makes the sweep look like an event.
MOVE_SECONDS = 1.0
REST_SECONDS = 1.0

#: Share of a pulse spent moving, and the frames one takes, counted in animation
#: steps: the pace is a period rather than a speed, so a long wait row is crossed
#: in the same time as a short one and the pulse does not depend on how often the
#: terminal happens to repaint. The share is what the demo's pace keys scale, so
#: changing the period keeps the two phases in proportion.
MOVE_SHARE = MOVE_SECONDS / (MOVE_SECONDS + REST_SECONDS)
PULSE_FRAMES = round((MOVE_SECONDS + REST_SECONDS) / ANIMATION_SECONDS)

#: Seconds one blink of the status bar's icon takes. The icon is a small thing on
#: a line of its own, so it turns over on a period of its own — no rest to sit
#: through, unlike the waiting row it reports on.
STATUS_BLINK_SECONDS = 1.5
STATUS_BLINK_FRAMES = round(STATUS_BLINK_SECONDS / ANIMATION_SECONDS)


def move_frames() -> int:
    """Return the frames of one pulse the waiting row spends moving."""
    return max(1, round(PULSE_FRAMES * MOVE_SHARE))


def moving(frame: int) -> bool:
    """Say whether the waiting row is in the moving part of its pulse."""
    return frame % PULSE_FRAMES < move_frames()


def sweep_column(frame: int, travel: int) -> int:
    """Return the column the highlight has reached at one animation frame.

    One pass takes the moving part of the pulse, so the highlight arrives at the
    end of the label as the row rests and sets off again when it moves.

    Args:
        frame: Monotonic frame counter shared by the whole application.
        travel: Columns one whole pass takes, ends included —
            :attr:`~zettcode.tui.render.sweep.SweepSpan.travel`.
    """
    return frame % PULSE_FRAMES * max(1, travel) // move_frames()


#: Columns of fade on each side of the waiting row's highlight. The presenter draws with it and
#: :func:`wait_picture` counts with it, so the two cannot disagree about how far a pass travels.
WAIT_RAMP = 3


def wait_picture(frame: int, title_width: int) -> tuple[bool, int]:
    """Return what the waiting row looks like at one frame, as a value.

    Two frames give equal values exactly when the row is drawn the same way at both: the
    highlight sits on a whole column, and its colours depend on nothing else, so this is
    that column (``0`` while the row rests, which is drawn flat whatever the frame is).
    The loop uses it to tell a frame that changes the screen from one that only repeats it.

    Args:
        frame: Monotonic frame counter shared by the whole application.
        title_width: Display width of the word the highlight crosses.
    """
    if not moving(frame):
        return (False, 0)
    return (True, sweep_column(frame, title_width + 2 * WAIT_RAMP))


def blink_state(frame: int) -> bool:
    """Say which of its two states the status bar's icon is in at one frame."""
    return frame % STATUS_BLINK_FRAMES < STATUS_BLINK_FRAMES // 2


def activity_glyph(frame: int) -> str:
    """Return the marker the status bar shows while work is in progress.

    The marker keeps one column and holds each of its two states instead of
    cycling through different symbols, which is what makes it read as an icon
    rather than as a spinner. It alternates on a period of its own, with no rest
    between blinks, because a small icon can turn over faster than the row it
    reports on; both read the same frame counter, so neither depends on how often
    the terminal repaints.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return RUNNING_GLYPHS[0 if blink_state(frame) else 1]
