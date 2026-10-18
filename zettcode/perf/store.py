"""Measure the session store's append and read cost against log size.

The store is on the request's critical path: the agent reads the branch before
a call and appends every message that comes back. If either is O(N) in the
session length, a long session makes the whole loop progressively slower and
the echo of a submitted prompt waits behind the parse. A healthy result is a
flat ``append`` and ``read`` column.

Run::

    uv run python -m perf.store --messages 200,800,3000 --repeats 20
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path
from time import perf_counter

from zett_agent.messages import UserMessage

from zettcode.app.agent.storage import SessionStore

from .harness import table


async def _measure(messages: int, repeats: int) -> tuple[float, float]:
    """Return (append ms/message, read ms/call) for one log size."""
    with tempfile.TemporaryDirectory(prefix="zettcode-perf-store-") as directory:
        store = SessionStore(Path(directory))
        start = perf_counter()
        for index in range(messages):
            await store.append("s", f"req{index}", UserMessage(content=f"message {index}"))
        append_ms = (perf_counter() - start) / messages * 1e3
        start = perf_counter()
        for _ in range(repeats):
            store.read("s")
        read_ms = (perf_counter() - start) / repeats * 1e3
    return append_ms, read_ms


def main() -> None:
    """Benchmark each requested message count and print the table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", default="200,800,3000", help="comma-separated log sizes")
    parser.add_argument("--repeats", type=int, default=20, help="reads to average per size")
    args = parser.parse_args()
    sizes = [int(value) for value in args.messages.split(",") if value.strip()]
    rows = []
    for messages in sizes:
        append_ms, read_ms = asyncio.run(_measure(messages, args.repeats))
        rows.append((str(messages), f"{append_ms:.3f}", f"{read_ms:.3f}"))
    print("\nmilliseconds per operation\n")
    print(table(("messages", "append ms", "read ms"), rows))


if __name__ == "__main__":
    main()
