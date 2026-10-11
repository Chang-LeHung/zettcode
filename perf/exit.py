"""What a quit costs, and which part of it belongs to this program.

Two answers, one command. The first is where the time goes: a child process that
imports the heavy modules, decides to leave, and then dies — with the heap
frozen, with the collector off, or with neither — so the part the interpreter
spends can be told apart from the part this program spends. The second, behind
``--pty``, is the number a reader feels: how long the process takes to disappear
after Ctrl-D, against the installed command line in a real pseudo-terminal.

The pseudo-terminal's master side is read continuously in that mode. A driver
that stops reading lets the child block on its own frame, and then it is timing
itself rather than the program.

Everything except ``--pty`` is hermetic: a throwaway workspace and config, no
network, nothing in ``~/.zettcode``.

Run it with ``uv run python -m perf.exit``; add ``--pty`` for the end-to-end
number and ``--runs`` to average more samples.

``--pty`` runs the real command line, so it is the one mode that is not fully
hermetic: the interface appends to the diagnostics log under ``~/.zettcode/log``.
Everything else — workspace, config, update check, skills, MCP — is a throwaway
directory the probe owns.
"""

from __future__ import annotations

import argparse
import os
import select
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from .harness import table

#: A model nothing calls, and every optional scan switched off: this probe must
#: not read the reader's skills or MCP servers, and the release check would make
#: the numbers depend on the network.
_CONFIG = (
    '[[models]]\nmodel = "perf-model"\ntoken = "perf-token"\n\n'
    "[update]\nenabled = false\n\n"
    "[skills]\nenabled = false\n\n"
    "[mcp]\nenabled = false\n"
)

#: The modules a launch warms, and whose import is what an exit pays for.
HEAVY = ("openai", "anthropic", "zett_agent.client")

#: A child that imports them, takes the requested last-minute action, and writes
#: the moment it decided to leave where the parent is watching for it.
_CHILD = textwrap.dedent(
    """
    import gc, sys, time
    for name in filter(None, sys.argv[1].split(",")):
        __import__(name)
    match sys.argv[2]:
        case "freeze":
            gc.freeze()
        case "disable":
            gc.disable()
    open(sys.argv[3], "w").write(str(time.perf_counter()))
    """
)

_ROWS = 40
_COLUMNS = 120


def workspace() -> Path:
    """Return a throwaway workspace, with a config file beside it."""
    root = Path(tempfile.mkdtemp(prefix="zettcode-exit."))
    (root / "work").mkdir()
    (root / "config.toml").write_text(_CONFIG, encoding="utf-8")
    return root


def environment(root: Path) -> dict[str, str]:
    """Return an environment that reads the probe's config, not the reader's."""
    return {**os.environ, "ZETTCODE_CONFIG": str(root / "config.toml")}


def _command() -> list[str]:
    """Return the installed console script, or the module when there is none."""
    script = Path(sys.executable).with_name("zettcode")
    return [str(script)] if script.exists() else [sys.executable, "-m", "zettcode.cli"]


def death_latency(mode: str, modules: tuple[str, ...] = HEAVY, *, runs: int) -> float:
    """Return the median time from a child deciding to leave to it being gone.

    The parent has to know when the decision was made, so the child writes a
    stamp and the parent starts its clock when that file appears: everything
    after it is the exit itself.

    Args:
        mode: ``"freeze"``, ``"disable"``, or anything else for no last-minute
            action at all.
        modules: What the child imports before deciding.
        runs: Samples to take the median of.
    """
    samples: list[float] = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="zettcode-exit-child-") as raw:
            stamp = Path(raw) / "stamp"
            child = subprocess.Popen(
                [sys.executable, "-c", _CHILD, ",".join(modules), mode, str(stamp)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.perf_counter() + 60.0
            while not stamp.exists() and time.perf_counter() < deadline:
                time.sleep(0.0005)
            decided = time.perf_counter()
            child.wait(timeout=60)
            samples.append((time.perf_counter() - decided) * 1000)
    return statistics.median(samples)


def teardown_rows(*, runs: int) -> list[list[str]]:
    """Return what each kind of exit costs, from a bare process up to a frozen one."""
    cases = (
        ("a process that imported nothing", "none", ()),
        ("the modules a launch warms", "none", HEAVY),
        ("the same, heap frozen before leaving", "freeze", HEAVY),
        ("the same, collector switched off", "disable", HEAVY),
    )
    return [[label, f"{death_latency(mode, modules, runs=runs):7.1f} ms"] for label, mode, modules in cases]


def _drain(master: int, timeout: float) -> bool:
    """Read whatever the child has written, so it never blocks on a full buffer."""
    ready, _, _ = select.select([master], [], [], timeout)
    if not ready:
        return False
    try:
        return bool(os.read(master, 1 << 20))
    except OSError:
        return False


def quit_in_a_terminal(root: Path, *, idle: float, runs: int) -> list[float]:
    """Return how long the process takes to disappear after Ctrl-D, per run.

    Args:
        root: The throwaway root the command line is started in.
        idle: Seconds to let the shell come up and warm before quitting.
        runs: Samples to take the median of.
    """
    if os.name != "posix":  # pragma: no cover - the probe runs where the shell runs
        return []
    import fcntl
    import pty
    import struct
    import termios

    command = _command()
    samples: list[float] = []
    for _ in range(runs):
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", _ROWS, _COLUMNS, 0, 0))
        process = subprocess.Popen(
            [*command, "-w", str(root / "work")],
            stdin=slave,
            stdout=slave,
            stderr=subprocess.DEVNULL,
            env=environment(root),
            cwd=str(root),
        )
        os.close(slave)
        began = time.perf_counter()
        try:
            while time.perf_counter() - began < idle:
                _drain(master, 0.01)
            quit_at = time.perf_counter()
            os.write(master, b"\x04")
            while process.poll() is None and time.perf_counter() - quit_at < 20.0:
                _drain(master, 0.0005)
            samples.append((time.perf_counter() - quit_at) * 1000)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            os.close(master)
    return samples


def parse_args() -> argparse.Namespace:
    """Return the probe's own flags."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="samples per measurement (median is printed)")
    parser.add_argument("--idle", type=float, default=1.5, help="seconds the shell is left running before Ctrl-D")
    parser.add_argument("--pty", action="store_true", help="also quit the real command line in a pseudo-terminal")
    return parser.parse_args()


def main() -> None:
    """Print what an exit costs, and what the interpreter's own part of it is."""
    args = parse_args()
    root = workspace()
    print(f"workspace       {root}")
    print(f"samples         {args.runs} (median)\n")

    print(table(["what the exiting process holds", "decide -> gone"], teardown_rows(runs=args.runs)))

    if args.pty:
        print()
        samples = quit_in_a_terminal(root, idle=args.idle, runs=args.runs)
        if not samples:
            print("Ctrl-D -> gone   not measurable on this platform")
        else:
            shown = ", ".join(f"{sample:.0f}" for sample in samples)
            print(f"Ctrl-D -> gone   {statistics.median(samples):5.0f} ms   ({shown})")


if __name__ == "__main__":
    main()
