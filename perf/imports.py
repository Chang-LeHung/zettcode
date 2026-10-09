"""What deferring one import would actually save.

``-X importtime`` reports each module's *cumulative* cost, which counts
everything the module pulled in — including modules the shell needs anyway. A
deferral decision asks a narrower question: how much smaller is the graph if
this module is not loaded up front? That is a difference, not a column.

So this probe measures it directly. It imports the shell twice in fresh
interpreters, once with the candidate replaced by a permissive stub and once
without, and reports the difference. A candidate the shell cannot do without
fails the stubbed run, which the table says rather than guessing.

The stub is blunt on purpose: it replaces the whole module with something that
answers any attribute with a no-op. "needed at import" therefore means the
*stub* broke something — usually a class used as a base or an enum member —
and not that a careful deferral would be impossible. Read it as "this needs a
hand-written lazy import, not a mechanical one".

Run it with ``uv run python -m perf.imports``; ``--runs`` averages more
samples, ``--target`` points it at a different entry module.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import textwrap

from .harness import table
from .startup import slowest_imports

#: Modules worth asking about: each is imported before the first frame and
#: plausibly only needed by one command or a later step.
DEFAULT_CANDIDATES: tuple[str, ...] = (
    "zettcode.app.agent.export",
    "zettcode.app.agent.replay",
    "zettcode.app.agent.title",
    "zettcode.app.ui.updating",
    "zettcode.app.commands",
    "zettcode.plugins",
    "zett_agent.extensions.shell_approval",
)

#: Time one import in a fresh interpreter.
_PLAIN = "import time;t=time.perf_counter();import {target};print((time.perf_counter()-t)*1000)"

#: Import the target with each named module replaced, before anything else runs.
_STUB = textwrap.dedent(
    """
    import importlib, sys, types, time

    class Stub(types.ModuleType):
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    for name in sys.argv[2:]:
        sys.modules[name] = Stub(name)

    began = time.perf_counter()
    importlib.import_module(sys.argv[1])
    print((time.perf_counter() - began) * 1000)
    """
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the sample count and the entry module to import."""
    parser = argparse.ArgumentParser(prog="perf.imports", description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="samples per row (default: 5)")
    parser.add_argument("--top", type=int, default=24, help="imports to read cumulative costs from (default: 24)")
    parser.add_argument("--target", default="zettcode.app.ui.app", help="module to import (default: the shell)")
    return parser.parse_args(argv)


def import_time(script: str, *args: str) -> float | None:
    """Return one fresh interpreter's wall time for ``script``, or ``None`` if it failed."""
    result = subprocess.run([sys.executable, "-c", script, *args], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return None


def _samples(script: str, *args: str, runs: int) -> list[float]:
    """Return the readable samples of one measurement."""
    return [value for _ in range(runs) if (value := import_time(script, *args)) is not None]


def deferral_saving(target: str, module: str, *, runs: int) -> float | None:
    """Return the milliseconds saved by importing ``target`` without ``module``.

    ``None`` means the shell could not be imported without it: the module is
    load-bearing at import time, not merely present in the graph.
    """
    plain = _samples(_PLAIN.format(target=target), runs=runs)
    stubbed = _samples(_STUB, target, module, runs=runs)
    if not plain or not stubbed:
        return None
    return statistics.median(plain) - statistics.median(stubbed)


def main() -> None:
    """Print what each candidate costs the shell's graph, and what deferring it saves."""
    args = parse_args()
    cumulative = dict(slowest_imports(top=args.top))
    rows: list[list[str]] = []
    for module in DEFAULT_CANDIDATES:
        saving = deferral_saving(args.target, module, runs=args.runs)
        rows.append(
            [
                module,
                f"{cumulative[module]:.1f} ms" if module in cumulative else "—",
                "needed at import" if saving is None else f"{saving:6.1f} ms",
            ]
        )
    rows.sort(key=lambda row: row[2] == "needed at import")

    print(f"target  {args.target}")
    print(f"samples {args.runs}\n")
    print(table(["module", "cumulative", "deferring saves"], rows))
    print(
        "\nThe cumulative column counts everything the module pulled in, including what\n"
        "the shell imports anyway. The last column is the difference a deferral would\n"
        "actually make — the number to decide on."
    )


if __name__ == "__main__":
    main()
