"""Report frame cost against transcript size, the guard against O(N) regressions.

Each row is one interaction a reader performs — typing, a running animation
frame, a streamed token — repeated at growing transcript sizes. A healthy
result is a flat column: the terminal window is bounded, so a frame must not
get slower just because the session got longer. A rising column points at a
full-transcript pass hiding behind a version or a file read.

Run::

    uv run python -m perf.scaling --turns 10,100,400,1600 --frames 200
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from time import perf_counter

from .frame_stages import FRAME_SECONDS
from .harness import PerfApp, build, table


def _idle(perf: PerfApp, frames: int) -> float:
    """Seconds per typed character plus the frame it triggers."""

    def step() -> None:
        perf.frame(text="x")

    return _time(frames, step)


def _busy(perf: PerfApp, frames: int) -> float:
    """Seconds per animation frame with a running row on screen."""

    def step() -> None:
        perf.advance(FRAME_SECONDS)
        perf.frame()

    return _time(frames, step)


def _stream(perf: PerfApp, frames: int) -> float:
    """Seconds per streamed token plus the frame it invalidates."""
    counter = [0]

    def step() -> None:
        perf.transcript.append_answer(f"token{counter[0]} ")
        counter[0] += 1
        perf.frame()

    return _time(frames, step)


def _time(frames: int, step: Callable[[], None]) -> float:
    """Return the mean seconds per call of ``step`` over ``frames`` runs."""
    start = perf_counter()
    for _ in range(frames):
        step()
    return (perf_counter() - start) / frames


def main() -> None:
    """Measure the three interactions at each requested transcript size."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", default="10,100,400,1600", help="comma-separated turn counts")
    parser.add_argument("--frames", type=int, default=200, help="frames to average per point")
    parser.add_argument("--width", type=int, default=120, help="synthetic terminal width")
    parser.add_argument("--height", type=int, default=40, help="synthetic terminal height")
    args = parser.parse_args()
    sizes = [int(value) for value in args.turns.split(",") if value.strip()]

    rows: list[tuple[str, ...]] = []
    for turns in sizes:
        options = {"width": args.width, "height": args.height}
        idle = build(turns, **options)
        try:
            idle_ms = _idle(idle, args.frames) * 1e3
        finally:
            idle.close()
        busy = build(turns, busy=True, **options)
        try:
            busy_ms = _busy(busy, args.frames) * 1e3
        finally:
            busy.close()
        streaming = build(turns, **options)
        try:
            stream_ms = _stream(streaming, args.frames) * 1e3
        finally:
            streaming.close()
        rows.append((str(turns), f"{idle_ms:.3f}", f"{busy_ms:.3f}", f"{stream_ms:.3f}"))

    print(f"\nframes={args.frames}  size={args.width}x{args.height}\n")
    print(table(("turns", "typing ms", "animating ms", "streaming ms"), rows))


if __name__ == "__main__":
    main()
