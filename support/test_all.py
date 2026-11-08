"""Run every distribution's test suite at once and print each result as it finishes.

Each package has its own ``Makefile`` and its own pytest configuration, so the work is one child process per package.
Running those children concurrently is what turns the workspace's suites from minutes into a little over the slowest
one. The largest suites also run their own tests on xdist workers, through ``PYTEST_ADDOPTS``; a small suite does not,
because starting workers costs more than it saves. ``TEST_JOBS`` caps how many packages run at once; ``1`` is the old
one-at-a-time run and also turns xdist off.

The output of a suite is held until it finishes, so a failure is one readable block rather than interleaved pytest
streams from every package; the line says how long it took and whether it passed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The suites with enough tests to pay for xdist workers; a small suite spends more time starting workers than it
#: saves. Two keeps the memory flat while the packages themselves run side by side.
PARALLEL = {
    "zettcode": 2,
    "zettcode-app": 2,
    "zettcode-broker": 2,
    "zettcode-messaging": 2,
    "zettcode-sdk": 2,
    "zettcode-server": 2,
}


def _jobs(given: str | None) -> int:
    """Return how many suites run at once: the argument, then ``TEST_JOBS``, then 60% of the machine's cores."""
    for value in (given, os.environ.get("TEST_JOBS")):
        if value:
            try:
                return max(1, int(value))
            except ValueError:
                pass
    return max(1, (os.cpu_count() or 4) * 6 // 10)


def _run(package: Path, jobs: int) -> tuple[Path, int, str, float]:
    """Run one package's suite and return it with its exit code, output and elapsed seconds."""
    started = time.monotonic()
    env = os.environ.copy()
    # The runner itself may have been started by a make with a jobserver; a child does not need it and would warn.
    env.pop("MAKEFLAGS", None)
    env.pop("MFLAGS", None)
    workers = 0 if jobs == 1 else min(PARALLEL.get(package.name, 0), jobs)
    if workers and " -n" not in f" {env.get('PYTEST_ADDOPTS', '')}":
        env["PYTEST_ADDOPTS"] = f"{env.get('PYTEST_ADDOPTS', '')} -n {workers}".strip()
    result = subprocess.run(
        ["make", "--no-print-directory", "-C", str(package), "test"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
    )
    return package, result.returncode, (result.stdout + result.stderr), time.monotonic() - started


def main(argv: list[str]) -> int:
    """Run every package under ``packages/`` that has tests; return a shell exit code."""
    jobs = _jobs(argv[1] if len(argv) > 1 else None)
    packages = sorted(path.parent for path in (ROOT / "packages").glob("*/tests"))
    if not packages:
        print("no package has tests", file=sys.stderr)
        return 1

    print(f"--- {len(packages)} package suites, {jobs} at a time", flush=True)
    failed: list[Path] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(_run, package, jobs) for package in packages]
        for future in as_completed(futures):
            package, code, output, elapsed = future.result()
            state = "failed" if code else "ok"
            print(f"--- {package.relative_to(ROOT)}  {elapsed:.1f}s  {state}", flush=True)
            print(output.rstrip(), flush=True)
            if code:
                failed.append(package)

    if failed:
        names = ", ".join(str(package.relative_to(ROOT)) for package in failed)
        print(f"--- {len(failed)} suite(s) failed: {names}", file=sys.stderr)
        return 1
    print(f"--- all {len(packages)} suites passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
