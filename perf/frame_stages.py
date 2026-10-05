"""Break one frame into its stages and report the time each one takes.

Answers "where does the time actually go" for the four things a reader feels:
typing (dispatch + repaint), a running animation frame, a streamed token, and
the first frame after a resize (which pays for layout). Each stage is timed
with the same :class:`PerfApp` the other probes use, so the rows line up.

Run::

    uv run python -m perf.frame_stages --turns 200 --frames 200
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from .harness import PerfApp, StageTimings, build, table

#: Seconds between animation steps, mirroring the scheduler's frame budget.
FRAME_SECONDS = 1 / 120


def _average(perf: PerfApp, frames: int, step: Callable[[PerfApp, int], StageTimings]) -> StageTimings:
    """Average the stage timings of ``frames`` frames produced by ``step``."""
    total = StageTimings()
    for index in range(frames):
        total = total.plus(step(perf, index))
    return total.divided(frames)


def _idle(perf: PerfApp, *_: int) -> StageTimings:
    """Type one character and paint the frame it triggers."""
    return perf.frame(text="x")


def _busy(perf: PerfApp, *_: int) -> StageTimings:
    """Paint one animation frame while a running row is on screen."""
    perf.advance(FRAME_SECONDS)
    return perf.frame()


def _stream(perf: PerfApp, index: int) -> StageTimings:
    """Append one streamed token and paint the frame it invalidates."""
    perf.transcript.append_answer(f"token{index} ")
    return perf.frame()


def _rows(label: str, timings: StageTimings) -> str:
    """Return one row per stage plus a total, already scaled to microseconds."""
    lines = [f"{label:>9}  {name:<9} {seconds * 1e6:9.1f} us" for name, seconds in timings.stages()]
    lines.append(f"{'':>9}  {'total':<9} {timings.total * 1e6:9.1f} us")
    return "\n".join(lines)


def main() -> None:
    """Run the four scenarios and print the per-stage breakdown."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=200, help="seeded turns in the transcript")
    parser.add_argument("--frames", type=int, default=200, help="frames to average per scenario")
    parser.add_argument("--width", type=int, default=120, help="synthetic terminal width")
    parser.add_argument("--height", type=int, default=40, help="synthetic terminal height")
    args = parser.parse_args()
    options = {"width": args.width, "height": args.height}

    print(f"\nturns={args.turns}  frames={args.frames}  size={args.width}x{args.height}\n")
    blocks: dict[str, StageTimings] = {}

    idle = build(args.turns, **options)
    try:
        blocks["typing"] = _average(idle, args.frames, _idle)
    finally:
        idle.close()

    busy = build(args.turns, busy=True, **options)
    try:
        blocks["animating"] = _average(busy, args.frames, _busy)
    finally:
        busy.close()

    streaming = build(args.turns, **options)
    try:
        blocks["streaming"] = _average(streaming, args.frames, _stream)
    finally:
        streaming.close()

    resized = build(args.turns, **options)
    try:
        resized.app.app.resize(args.width - 1, args.height)
        blocks["resize"] = resized.frame()
    finally:
        resized.close()

    for label, timings in blocks.items():
        print(_rows(label, timings))
        print()

    headers = ("scenario", "dispatch", "layout", "tick", "paint", "cursor", "diff", "total")
    rows = [
        (
            label,
            *[
                f"{value * 1e6:.1f}"
                for value in (
                    timings.dispatch,
                    timings.layout,
                    timings.tick,
                    timings.paint,
                    timings.cursor,
                    timings.diff,
                    timings.total,
                )
            ],
        )
        for label, timings in blocks.items()
    ]
    print("microseconds per frame\n")
    print(table(headers, rows))


if __name__ == "__main__":
    main()
