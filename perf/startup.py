"""Where a launch spends its time before the first frame.

Four answers, one command: the stages a launch goes through, the modules the
shell's import graph pays for, the slowest of those modules, and — under a real
pseudo-terminal — the wall time until the interface first writes a byte. Every
run uses a throwaway workspace and config, so nothing here touches the reader's
sessions or their ``~/.zettcode``.

Run it with ``uv run python -m perf.startup``; add ``--pty`` for the number a
reader actually feels, and ``--runs`` to average more samples. The absolute
values move with the machine; the shape of the table, and what moves between
two runs on the same machine, is the signal.

``--pty`` runs the real command line, so it is the one mode that is not fully
hermetic: the interface appends to the diagnostics log under ``~/.zettcode/log``.
Everything else — workspace, config, update check, skills, MCP — is a throwaway
directory the probe owns.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from .harness import table

#: A model nothing calls, and every optional scan switched off: the probe must
#: not read the reader's skills or MCP servers, and the release check would
#: make the numbers depend on the network.
_CONFIG = (
    '[[models]]\nmodel = "perf-model"\ntoken = "perf-token"\n\n'
    "[update]\nenabled = false\n\n"
    "[skills]\nenabled = false\n\n"
    "[mcp]\nenabled = false\n"
)

#: The launch, timed stage by stage, in a fresh interpreter.
_PHASES = textwrap.dedent(
    """
    import asyncio, json, sys
    from time import perf_counter

    marks = []
    def mark(name, since):
        now = perf_counter()
        marks.append([name, (now - since) * 1000])
        return now

    start = perf_counter()
    import zettcode.cli
    t = mark("import zettcode.cli", start)
    config = zettcode.cli.resolve_config(["-w", sys.argv[1]])
    t = mark("resolve_config (file + terminal)", t)
    from zettcode.app import ZettCodeApp
    t = mark("import the shell + agent glue", t)
    from zettcode.app.agent.agent import ZettCodeAgent
    agent = ZettCodeAgent.preview(config)
    t = mark("ZettCodeAgent.preview", t)
    app = ZettCodeApp(agent, auto_theme=False)
    t = mark("build the widget tree", t)

    async def launch():
        # The runtime warms behind the frame: start() only schedules it, so the
        # paint below does not wait for the provider import and client build.
        warm = agent.runtime.start()
        app.app.resize(120, 40)
        app.app.mount()
        app.app.render()
        mark("mount + paint one frame", t)
        await asyncio.gather(warm, return_exceptions=True)

    asyncio.run(launch())
    t = mark("provider + client warm-up (behind the frame)", t)
    print(json.dumps(marks))
    """
)

#: The imports a launch pays for, as opposed to the ones it never touches.
_IMPORTS = "import zettcode.cli; import zettcode.app.ui.app"

#: Cells the synthetic terminal is sized to, and the rows it starts on.
_COLUMNS = 120
_ROWS = 40


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the sample count, the table size, and whether to use a terminal."""
    parser = argparse.ArgumentParser(prog="perf.startup", description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="samples per measurement (default: 3)")
    parser.add_argument("--top", type=int, default=12, help="imports to list (default: 12)")
    parser.add_argument("--pty", action="store_true", help="also time the real command line in a pseudo-terminal")
    return parser.parse_args(argv)


def workspace() -> Path:
    """Return a throwaway workspace, with a config file beside it."""
    root = Path(tempfile.mkdtemp(prefix="zettcode-startup."))
    (root / "work").mkdir()
    (root / "config.toml").write_text(_CONFIG, encoding="utf-8")
    return root


def environment(root: Path) -> dict[str, str]:
    """Return an environment that reads the probe's config, not the reader's."""
    return {**os.environ, "ZETTCODE_CONFIG": str(root / "config.toml")}


def phases(root: Path, *, runs: int) -> list[tuple[str, float]]:
    """Return each launch stage's median wall time in milliseconds."""
    samples: dict[str, list[float]] = {}
    order: list[str] = []
    for _ in range(runs):
        result = subprocess.run(
            [sys.executable, "-c", _PHASES, str(root / "work")],
            check=True,
            capture_output=True,
            text=True,
            env=environment(root),
        )
        for name, milliseconds in json.loads(result.stdout.strip().splitlines()[-1]):
            samples.setdefault(name, []).append(milliseconds)
            if name not in order:
                order.append(name)
    return [(name, statistics.median(samples[name])) for name in order]


def slowest_imports(*, top: int) -> list[tuple[str, float]]:
    """Return the modules with the largest cumulative import time, slowest first."""
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", _IMPORTS],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[str, float]] = []
    for line in result.stderr.splitlines():
        if not line.startswith("import time:") or line.count("|") < 2:
            continue
        _, cumulative, name = (part.strip() for part in line.split("|", 2))
        try:
            milliseconds = int(cumulative) / 1000
        except ValueError:
            continue
        rows.append((name, milliseconds))
    rows.sort(key=lambda row: row[1], reverse=True)
    return rows[:top]


def time_to_first_frame(root: Path, *, runs: int) -> list[float]:
    """Return the milliseconds until the real command line writes its first byte."""
    if os.name != "posix":
        return []
    import fcntl
    import pty
    import select
    import struct
    import termios

    command = _command()
    samples: list[float] = []
    for _ in range(runs):
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", _ROWS, _COLUMNS, 0, 0))
        began = time.perf_counter()
        process = subprocess.Popen(
            [*command, "-w", str(root / "work")],
            stdin=slave,
            stdout=slave,
            stderr=subprocess.DEVNULL,
            env=environment(root),
            cwd=str(root),
        )
        os.close(slave)
        try:
            while time.perf_counter() - began < 20:
                ready, _, _ = select.select([master], [], [], 0.02)
                if ready and os.read(master, 65536):
                    samples.append((time.perf_counter() - began) * 1000)
                    break
        finally:
            process.terminate()
            process.wait(timeout=10)
            os.close(master)
    return samples


def _command() -> list[str]:
    """Return the installed console script, or the module when there is none."""
    script = Path(sys.executable).with_name("zettcode")
    return [str(script)] if script.exists() else [sys.executable, "-m", "zettcode.cli"]


def main() -> None:
    """Print the launch's stages, its import graph, and the time to first paint."""
    args = parse_args()
    root = workspace()
    print(f"workspace       {root}")
    print(f"samples         {args.runs}\n")

    stages = phases(root, runs=args.runs)
    rows = [[name, f"{milliseconds:7.1f} ms"] for name, milliseconds in stages]
    rows.append(["total", f"{sum(value for _, value in stages):7.1f} ms"])
    print(table(["stage", "median"], rows))

    print()
    imports = [[name, f"{milliseconds:7.1f} ms"] for name, milliseconds in slowest_imports(top=args.top)]
    print(table(["slowest import (cumulative)", "time"], imports))

    if args.pty:
        print()
        samples = time_to_first_frame(root, runs=args.runs)
        if not samples:
            print("time to first frame  not measurable on this platform")
        else:
            shown = ", ".join(f"{value:.0f}" for value in samples)
            print(f"time to first frame  {statistics.median(samples):.0f} ms  (samples: {shown})")


if __name__ == "__main__":
    main()
