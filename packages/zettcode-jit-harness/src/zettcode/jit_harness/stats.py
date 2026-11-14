"""How tools have done, read from a session's stored conversation instead of measured while they run.

Every finished tool call is already a line of the session's ``data.jsonl``: the tool's name, whether it succeeded, what
it handed back and how long it took (``timing.duration_ns``). Counting them there needs no wrapper around a call, covers
every tool the session ever ran (the application's, an MCP server's, the model's own), and survives a restart, which a
counter held in memory does not.

The file can be very large (a long session is hundreds of megabytes), so nothing here reads it whole:

* only the **tail** is read, at most :data:`SCAN_BYTES`, because how a tool has been doing lately is the question; the
  answer says when it left older calls out;
* it is read line by line, and a line is parsed only when it can be a tool result (a byte search first, which is what
  keeps a scan of tens of megabytes at a fraction of a second);
* a line longer than :data:`MAX_LINE` is skipped unparsed (a tool result that large would cost more to read than the
  number is worth) and counted, so the answer can say so;
* what is kept is a handful of numbers and at most :data:`ERRORS_KEPT` short messages per tool, never a message.

The store writes one tool result to a message, and the time it records is that message's. A message that ever carried
two results would have its time counted for each, so this is the place to look if the framework starts batching them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

from zett_agent.jit_harness import ToolStatsReport, ToolStatsRow

__all__ = [
    "ERRORS_KEPT",
    "MAX_LINE",
    "MAX_NAMES",
    "MAX_ROWS",
    "SCAN_BYTES",
    "Scan",
    "Tally",
    "UsageReport",
    "build_report",
    "scan_tool_calls",
]


class UsageReport(ToolStatsReport):
    """The framework's report, and a sentence saying how much of the conversation it was counted from."""

    window: str


#: The most of a conversation file that is read, counted back from its end.
SCAN_BYTES = 32 * 1024 * 1024

#: The longest line that is parsed; a longer one is skipped.
MAX_LINE = 2 * 1024 * 1024

#: The most distinct recent error messages kept for one tool.
ERRORS_KEPT = 5

#: How much of an error message is kept.
ERROR_CHARS = 200

#: Only a tool result carries this key, which is what makes the byte search a safe first filter.
_MARK = b'"tool_call_id"'

#: How much of an oversized line is read at once while the rest of it is thrown away.
_DRAIN = 1024 * 1024


@dataclass
class Tally:
    """What one tool has done in the part of the conversation that was read."""

    calls: int = 0
    failed: int = 0
    #: Milliseconds over the calls that said how long they took, and how many did.
    total_ms: float = 0.0
    timed: int = 0
    #: Characters handed back, over all calls.
    total_chars: int = 0
    #: Distinct recent error messages, oldest first.
    errors: list[str] = field(default_factory=list)

    @property
    def completed(self) -> int:
        """Return how many calls succeeded."""
        return self.calls - self.failed

    def remember(self, message: str) -> None:
        """Keep a failed call's message, newest last, once."""
        if message in self.errors:
            self.errors.remove(message)
        self.errors.append(message)
        del self.errors[:-ERRORS_KEPT]


@dataclass
class Scan:
    """The result of reading a conversation file: a tally per tool, and how much of the file that covers."""

    tools: dict[str, Tally] = field(default_factory=dict)
    #: Bytes read and the size of the file; they differ when the file was longer than the window.
    scanned: int = 0
    size: int = 0
    #: Lines left unparsed because they were longer than :data:`MAX_LINE`.
    skipped: int = 0

    @property
    def partial(self) -> bool:
        """Return whether the start of the file was left out."""
        return self.scanned < self.size

    def describe(self) -> str:
        """Return one sentence saying what was read, for whoever reads the numbers."""
        if self.size == 0:
            return "this session has no stored conversation yet"
        text = (
            f"the last {_megabytes(self.scanned)} of {_megabytes(self.size)} of this session; older calls are not counted"
            if self.partial
            else "the whole of this session"
        )
        if self.skipped:
            text += f"; {self.skipped} results too large to read were left out"
        return text


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def scan_tool_calls(path: Path, *, max_bytes: int = SCAN_BYTES, max_line: int = MAX_LINE) -> Scan:
    """Count the finished tool calls in the tail of a conversation file.

    A file that is missing or unreadable is an empty scan, since a conversation that has not been stored yet has simply
    not run a tool.

    Args:
        path: The session's ``data.jsonl``.
        max_bytes: How much of the end of the file may be read.
        max_line: The longest line that is parsed, in bytes, its line break not counted: one of exactly this length is
            read and one byte more is skipped.
    """
    scan = Scan()
    try:
        handle = path.open("rb")
    except OSError:
        return scan
    with handle:
        try:
            scan.size = os.fstat(handle.fileno()).st_size
            start = max(0, scan.size - max_bytes)
            if start:
                # The window opens inside a line unless it happens to open at the start of one: skip to the next.
                handle.seek(start - 1)
                if handle.read(1) != b"\n":
                    first = handle.readline(max_line)
                    if first and not first.endswith(b"\n"):
                        _drain(handle)
            scan.scanned = scan.size - handle.tell()
            while True:
                line = handle.readline(max_line + 1)
                if not line:
                    break
                if len(line) > max_line and not line.endswith(b"\n"):
                    scan.skipped += 1
                    _drain(handle)
                    continue
                if _MARK in line:
                    _count(scan, line)
        except OSError:
            pass
    return scan


def _drain(handle: BinaryIO) -> None:
    """Throw away the rest of the line the last read stopped inside of, without holding it."""
    while True:
        # A line ends at a newline; a read that did not reach one is still inside it.
        position = handle.tell()
        chunk = handle.read(_DRAIN)
        if not chunk:
            return
        cut = chunk.find(b"\n")
        if cut >= 0:
            handle.seek(position + cut + 1)
            return


def _count(scan: Scan, line: bytes) -> None:
    """Add the tool result a line holds, when it holds one."""
    try:
        record = json.loads(line)
    except ValueError:
        return
    if not isinstance(record, dict) or record.get("kind") != "message":
        return
    parts = record.get("message")
    if not isinstance(parts, list):
        return
    timing = record.get("timing")
    nanoseconds = timing.get("duration_ns") if isinstance(timing, dict) else None
    for part in parts:
        data = part.get("data") if isinstance(part, dict) else None
        if not isinstance(data, dict) or "tool_call_id" not in data:
            continue
        name, success = data.get("name"), data.get("success")
        if not isinstance(name, str) or not isinstance(success, bool):
            continue
        content = data.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        tally = scan.tools.setdefault(name, Tally())
        tally.calls += 1
        tally.total_chars += len(text)
        if isinstance(nanoseconds, (int, float)) and not isinstance(nanoseconds, bool):
            tally.total_ms += nanoseconds / 1_000_000
            tally.timed += 1
        if not success:
            tally.failed += 1
            tally.remember(" ".join(text.split())[:ERROR_CHARS] or "failed with no message")


#: The most rows an overview holds, and the most tools that may be asked for by name.
MAX_ROWS = 20
MAX_NAMES = 10


def build_report(
    scan: Scan,
    catalog: Mapping[str, Mapping[str, Any]],
    names: Sequence[str] | None,
    *,
    management: Collection[str] = (),
) -> UsageReport:
    """Return what the model is shown: a row per tool, shaped like the framework's own ``ToolStatsReport``.

    Args:
        scan: What :func:`scan_tool_calls` read.
        catalog: The tools known now, by name; each says its ``origin`` and ``status``.
        names: The tools to look at, each with up to three recent errors, or ``None`` for an overview: the model's own
            tools whether or not they were called, and the application's that were, most called first.
        management: The control tools, which are not measured.

    Raises:
        ValueError: For a name that is not a tool, is a control tool, or too many names.
    """
    explicit = names is not None
    if names is None:
        wanted = sorted(catalog)
    else:
        wanted = list(dict.fromkeys(names))
        if not wanted or len(wanted) > MAX_NAMES:
            raise ValueError(f"Name between 1 and {MAX_NAMES} tools")
        unknown = [name for name in wanted if name not in catalog]
        if unknown:
            raise ValueError(f"Unknown tool: {', '.join(unknown)} (the control tools are not measured)")
    rows: list[dict[str, Any]] = []
    for name in wanted:
        if name in management:
            continue
        entry = catalog[name]
        tally = scan.tools.get(name, Tally())
        if not explicit and entry.get("origin") == "base" and not tally.calls:
            continue
        rows.append(_row(name, entry, tally, 3 if explicit else 1))
    if explicit:
        return UsageReport(tools=cast("list[ToolStatsRow]", rows), omitted=0, window=scan.describe())
    rows.sort(key=lambda row: (-row["calls"], row["name"]))
    return UsageReport(
        tools=cast("list[ToolStatsRow]", rows[:MAX_ROWS]),
        omitted=max(0, len(rows) - MAX_ROWS),
        window=scan.describe(),
    )


def _row(name: str, entry: Mapping[str, Any], tally: Tally, errors: int) -> dict[str, Any]:
    return {
        "name": name,
        "origin": entry.get("origin"),
        "status": entry.get("status"),
        "calls": tally.calls,
        "success_rate": round(tally.completed / tally.calls, 3) if tally.calls else None,
        "failed": tally.failed,
        "avg_ms": round(tally.total_ms / tally.timed, 1) if tally.timed else None,
        "avg_output_chars": round(tally.total_chars / tally.calls) if tally.calls else None,
        "recent_errors": list(reversed(tally.errors))[:errors],
    }
