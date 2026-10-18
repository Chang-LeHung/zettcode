"""Run one scenario under cProfile and print the functions that dominate it.

The stage table says *which phase* costs time; this says *which function* does.
Pair them: a rising ``paint`` stage with ``TranscriptSource._sync`` at the top
means an entry walk, while a flat stage with ``Canvas.set_cell`` on top is the
screen itself and has nothing to do with session length.

Run::

    uv run python -m perf.profile --scenario stream --turns 1600 --frames 300
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
from collections.abc import Callable

from .frame_stages import FRAME_SECONDS
from .harness import PerfApp, build


def _idle(perf: PerfApp, _: int) -> None:
    """Type one character and paint the frame it triggers."""
    perf.frame(text="x")


def _busy(perf: PerfApp, _: int) -> None:
    """Paint one animation frame while a running row is on screen."""
    perf.advance(FRAME_SECONDS)
    perf.frame()


def _stream(perf: PerfApp, index: int) -> None:
    """Append one streamed token and paint the frame it invalidates."""
    perf.transcript.append_answer(f"token{index} ")
    perf.frame()


#: Scenario name to the loop body, so the CLI and the profile share one table.
SCENARIOS: dict[str, Callable[[PerfApp, int], None]] = {
    "idle": _idle,
    "busy": _busy,
    "stream": _stream,
}


def main() -> None:
    """Profile one scenario and print the top functions by self time."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="stream")
    parser.add_argument("--turns", type=int, default=1600)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--sort", default="tottime", choices=("tottime", "cumtime"))
    args = parser.parse_args()
    step = SCENARIOS[args.scenario]

    perf = build(args.turns, busy=args.scenario == "busy")
    try:
        profiler = cProfile.Profile()
        profiler.enable()
        for index in range(args.frames):
            step(perf, index)
        profiler.disable()
    finally:
        perf.close()

    print(f"\nscenario={args.scenario}  turns={args.turns}  frames={args.frames}\n")
    pstats.Stats(profiler).sort_stats(args.sort).print_stats(args.top)


if __name__ == "__main__":
    main()
