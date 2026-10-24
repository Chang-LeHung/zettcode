"""Where a resume spends its time, against a stored session of a realistic shape and size.

Resuming a session does five things before the reader can type: it checks the
session exists, parses the stored branch, rebuilds the conversation's entries from
it, primes the context report, and then the first frame has to measure every entry
to learn how tall the transcript is. A resume feels slow when any of those scales
with the size of the history, and the history is the one thing in this program that
only ever grows.

This probe builds a session of a fixed, repeatable shape in a throwaway store — user
turns, reasoning, tool calls with outputs from a few lines to tens of kilobytes,
Markdown answers — and times each stage on its own, then the whole command line.
It never reads the reader's sessions or their ``~/.zettcode``: the end-to-end run
points ``HOME`` at the probe's own directory.

Run it with ``uv run python -m perf.resume``; ``--messages`` sets the size (the
default is a session of the length a long working day produces), ``--runs`` the
samples per stage, and ``--e2e`` adds the real command line, which is what a reader
feels and the only number here that includes the interpreter's own start.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage

from zettcode.app import TranscriptSource
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.conversation.replay import replay
from zettcode.cli import session_exists
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.storage import SessionStore
from zettcode.tui import DARK

from .harness import table

#: Cells wide the first frame measures the transcript at.
WIDTH = 120

_CONFIG = (
    '[[models]]\nmodel = "perf-model"\ntoken = "perf-token"\n\n'
    "[update]\nenabled = false\n\n"
    "[skills]\nenabled = false\n\n"
    "[mcp]\nenabled = false\n"
)

_ANSWER = (
    "I found the cause in `parse_line`: the tokenizer treated a trailing backslash as an escape.\n\n"
    "```python\n"
    "def parse_line(line: str) -> list[str]:\n"
    "    tokens = []\n"
    "    for word in line.split():\n"
    "        tokens.append(word.rstrip('\\\\'))\n"
    "    return tokens\n"
    "```\n\n"
    "- the loop now strips the escape before the token is stored\n"
    "- `tests/test_parse.py` covers the case\n"
)

_REASONING = "The failing test names parse_line, so the tokenizer is the first place to look. " * 6


def _tool_output(turn: int, call: int) -> str:
    """Return one tool result: mostly short, now and then a screenful, sometimes huge.

    Real sessions look like this — a test run's whole log is one result and a
    ``grep`` is a handful of lines — and the long ones are what a renderer that
    wraps everything it is given pays for.
    """
    if turn % 25 == 0 and call == 1:
        return "\n".join(
            f"tests/test_module_{turn}.py::test_case_{index} PASSED  [{index % 100:3d}%]" for index in range(900)
        )
    if call == 1:
        return "\n".join(
            f"{index + 1:4d}  def helper_{turn}_{index}(value):  # computes {index} things" for index in range(40)
        )
    return f"src/pkg/module_{turn}.py:{turn + 3}:    return parse_line(value)\nsrc/pkg/other.py:12: parse_line"


async def build_session(store: SessionStore, session_id: str, messages: int) -> int:
    """Write a session of about ``messages`` messages and return how many it wrote."""
    written = 0
    turn = 0
    while written < messages:
        request = f"req-{turn}"
        await store.append(
            session_id, request, UserMessage(content=f"turn {turn}: fix the failing parse test in module_{turn}")
        )
        calls = (
            ToolCall(f"c{turn}-0", "read_file", {"path": f"src/pkg/module_{turn}.py"}),
            ToolCall(f"c{turn}-1", "bash", {"command": f"pytest tests/test_module_{turn}.py -q"}),
        )
        for index, call in enumerate(calls):
            await store.append(
                session_id, request, AssistantMessage(reasoning=_REASONING if index == 0 else "", tool_calls=(call,))
            )
            await store.append(
                session_id,
                request,
                ToolMessage(tool_call_id=call.id, name=call.name, content=_tool_output(turn, index), success=True),
            )
        await store.append(session_id, request, AssistantMessage(content=_ANSWER))
        written += 6
        turn += 1
    return written


def median_ms(samples: list[float]) -> float:
    """Return the median of a list of seconds, in milliseconds."""
    return statistics.median(samples) * 1000


def stages(config: ZettCodeConfig, session_id: str, *, runs: int) -> list[tuple[str, float]]:
    """Return each stage's median wall time in milliseconds, every run from a cold start."""
    samples: dict[str, list[float]] = {}

    def record(name: str, since: float) -> float:
        now = perf_counter()
        samples.setdefault(name, []).append(now - since)
        return now

    for _ in range(runs):
        # What the command line does before it builds anything: is there such a session?
        start = perf_counter()
        session_exists(config, session_id)
        record("session_exists (cli)", start)

        # The agent's own store has not seen the file, which is the real situation.
        store = SessionStore(config.store, config.workspace)
        start = perf_counter()
        session = store.read(session_id)
        record("store.read (parse the branch)", start)

        start = perf_counter()
        replayed = replay(session)
        record("replay (rebuild the entries)", start)

        source = TranscriptSource(replayed.transcript, theme=DARK)
        start = perf_counter()
        source.count(WIDTH)
        record("first paint (measure every entry)", start)

        agent = ZettCodeAgent.preview(config)
        agent.runtime.persistence.read(session_id)  # parse once; what follows is the rest of restoring
        start = perf_counter()
        agent.restore_session(session_id)
        record("restore_session minus the parse", start)
    return [(name, median_ms(values)) for name, values in samples.items()]


async def _stall(config: ZettCodeConfig, session_id: str) -> tuple[float, float]:
    """Return (wall time, longest stall of the event loop) of resuming from inside the app, in seconds.

    The stall is what the reader feels: for as long as the loop cannot turn, no key is
    read, nothing repaints, and the spinner stops. A heartbeat that asks to run every
    5 ms records the longest time it was kept waiting.
    """
    from zettcode.app import ZettCodeApp

    # The stages before this one leave a large heap behind, and a collection of it is a
    # pause that belongs to them, not to the resume: start from a collected one.
    gc.collect()
    app = ZettCodeApp(ZettCodeAgent.preview(config))
    app.app.resize(WIDTH, 40)
    app.app.mount()
    gaps: list[float] = []

    async def heartbeat() -> None:
        last = perf_counter()
        while True:
            await asyncio.sleep(0.005)
            now = perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)
    gaps.clear()
    start = perf_counter()
    await app.resume_session(session_id)
    wall = perf_counter() - start
    await asyncio.sleep(0.02)
    task.cancel()
    return wall, max(gaps)


def stall(config: ZettCodeConfig, session_id: str, *, runs: int) -> tuple[float, float]:
    """Return the median wall time and the median longest stall of ``/resume``, in milliseconds."""
    results = [asyncio.run(_stall(config, session_id)) for _ in range(runs)]
    return median_ms([wall for wall, _ in results]), median_ms([longest for _, longest in results])


def command_line(root: Path, workspace: Path, args: list[str], *, runs: int) -> float:
    """Return the median wall time of the real command line, in milliseconds."""
    script = Path(sys.executable).with_name("zettcode")
    command = [str(script)] if script.exists() else [sys.executable, "-m", "zettcode.cli"]
    env = {**os.environ, "HOME": str(root / "home"), "ZETTCODE_CONFIG": str(root / "config.toml")}
    samples = []
    for _ in range(runs):
        began = perf_counter()
        subprocess.run([*command, "-w", str(workspace), *args, "--dry-run"], check=True, capture_output=True, env=env)
        samples.append(perf_counter() - began)
    return median_ms(samples)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the session size, the sample count, and whether to run the command line."""
    parser = argparse.ArgumentParser(prog="perf.resume", description=__doc__)
    parser.add_argument("--messages", type=int, default=4000, help="messages in the session (default: 4000)")
    parser.add_argument("--runs", type=int, default=5, help="samples per stage (default: 5)")
    parser.add_argument("--e2e", action="store_true", help="also time the real command line")
    return parser.parse_args(argv)


def main() -> None:
    """Build a session, then print what each part of resuming it costs."""
    args = parse_args()
    root = Path(tempfile.mkdtemp(prefix="zettcode-resume.")).resolve()
    workspace = root / "work"
    workspace.mkdir()
    (root / "config.toml").write_text(_CONFIG, encoding="utf-8")
    store_dir = root / "home" / ".zettcode" / "sessions"
    config = ZettCodeConfig(
        workspace=workspace,
        models=(ModelConfig(model="perf-model", token="perf-token"),),
        store=store_dir,
        plugins_enabled=False,
        skills_enabled=False,
        mcp_enabled=False,
    )
    session_id = "perf-session"
    written = asyncio.run(build_session(SessionStore(config.store, config.workspace), session_id, args.messages))
    size = SessionStore(config.store, config.workspace).session_path(session_id).stat().st_size
    print(f"session         {written} messages, {size / 1e6:.1f} MB, in {root}")
    print(f"samples         {args.runs}\n")

    rows = [[name, f"{milliseconds:8.1f} ms"] for name, milliseconds in stages(config, session_id, runs=args.runs)]
    print(table(["stage (cold)", "median"], rows))

    wall, longest = stall(config, session_id, runs=args.runs)
    print()
    print(
        table(
            ["/resume from inside the app", "median"],
            [
                ["wall time until the session is shown", f"{wall:8.1f} ms"],
                ["longest the event loop could not turn", f"{longest:8.1f} ms"],
            ],
        )
    )

    if args.e2e:
        fresh = command_line(root, workspace, [], runs=args.runs)
        resumed = command_line(root, workspace, ["--resume", session_id], runs=args.runs)
        print()
        print(
            table(
                ["command line", "median"],
                [
                    ["zettcode --dry-run", f"{fresh:8.0f} ms"],
                    [f"zettcode --resume ({written} messages)", f"{resumed:8.0f} ms"],
                    ["resume costs", f"{resumed - fresh:8.0f} ms"],
                ],
            )
        )


if __name__ == "__main__":
    main()
