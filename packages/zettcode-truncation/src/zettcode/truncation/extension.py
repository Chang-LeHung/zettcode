"""Keep a tool result that is too long to send in a file, and send its start and its end instead.

The tools in this repository bound what they return (``zettcode/tools/output.py``: 50 KB and 2000 lines, with a note
saying how to go on). Nothing bounds a tool that comes from somewhere else — an MCP server's answer, a subagent's
report, a plugin's own tool — and one of those can arrive carrying a megabyte: it is paid for in the model's context
on every later request of the session, and once it is cut nothing in it can be read again.

So after a call, and before its result is stored or sent anywhere, a result over the budget is written whole into the
session's folder beside the shell's kept streams (``tool-output/``), and what replaces it is its start and its end
around a note naming that file. The model reads the rest with ``read_tool_output``, a bounded local reader restricted
to files this extension retained for the current session. It stays local even when workspace tools are remote.
The file goes away with the session it belongs to, and the reader's project never sees it.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
from pathlib import Path
from typing import Annotated

from pydantic import Field
from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import ToolCall, ToolMessage
from zett_agent.tools.base import tool

from zettcode.engine.storage import KEPT_OUTPUT, SessionStore
from zettcode.tools.output import MAX_OUTPUT_BYTES, MAX_OUTPUT_LINES, stream_preview

#: The tool that keeps its own output: it names the streams it kept, and that note is the whole point of its
#: result, so its preview is never taken apart here.
OWN_TRUNCATION = "bash"

#: What a result may carry and still be sent whole. It is a little over what our own tools keep themselves to, with
#: room for the note each of them ends with, so a result they bounded is left exactly as they wrote it; anything
#: larger came from a tool that does not bound itself.
MAX_RESULT_BYTES = MAX_OUTPUT_BYTES + 4 * 1024
MAX_RESULT_LINES = MAX_OUTPUT_LINES + 100

#: Every character ``str.splitlines()`` treats as a line boundary. A guard that counted only ``\n`` would call a
#: CR-separated result short, which is how a tool passing on a Windows program's output is written.
LINE_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"

#: What a kept file may be named after, from the tool and the call. A name from the model is not a path: no `/`, no
#: `..`, and nothing a shell or a filesystem reads as special.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")

#: The longest stem a kept file gets, before the suffix that tells two of them apart.
MAX_STEM = 80


class LongOutputExtension(AgentExtension):
    """Keep an over-long tool result in the session's folder, and send its start and its end."""

    def __init__(self, store: SessionStore) -> None:
        """Keep the store whose session folders the output is written into."""
        self._store = store

    async def on_tool(self, context: AgentRunContext) -> None:
        session_id = context.config.session_id
        if not isinstance(session_id, str):
            return

        @tool
        async def read_tool_output(
            file_path: str,
            offset: Annotated[int, Field(ge=1, le=1_000_000)] = 1,
            limit: Annotated[int, Field(ge=1, le=2000)] = 2000,
        ) -> str:
            """Read retained local tool output for this session, even when workspace tools use SSH.

            Guidelines:
                - Use only for the file named in a retained-output hint, never for workspace files.
                - Pass offset and limit to read the next bounded range.
            """
            return await asyncio.to_thread(self._read, session_id, file_path, offset, limit)

        context.register_tool(read_tool_output)

    def _read(self, session_id: str, file_path: str, offset: int, limit: int) -> str:
        if type(offset) is not int or not 1 <= offset <= 1_000_000 or type(limit) is not int or not 1 <= limit <= 2000:
            raise ValueError("offset must be 1..1000000 and limit must be 1..2000")
        path = Path(file_path)
        expected = self._store.session_dir(session_id) / KEPT_OUTPUT
        parent = path.parent
        direct = parent.resolve() == expected.resolve()
        shell_stream = (
            parent.name.startswith("shell-")
            and path.name in {"stdout.txt", "stderr.txt"}
            and parent.parent.resolve() == expected.resolve()
            and not parent.is_symlink()
        )
        if path.is_symlink() or not (direct or shell_stream):
            raise ValueError("Not retained tool output for this session")
        if expected.is_symlink():
            raise ValueError("Retained output directory was replaced")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("Retained output must be a regular file")
            lines: list[str] = []
            size = 0
            number = 0
            while True:
                line = handle.readline(MAX_OUTPUT_BYTES + 1)
                if not line:
                    return "".join(lines)
                number += 1
                if number < offset:
                    continue
                rendered = f"{number}\t{line}"
                size += len(rendered.encode("utf-8"))
                if size > MAX_OUTPUT_BYTES or len(line) > MAX_OUTPUT_BYTES:
                    return "".join(lines) + f"\n... [byte limit reached at line {number}; request a smaller range]"
                lines.append(rendered)
                if len(lines) >= limit:
                    return "".join(lines) + f"\n... [continue with offset={number + 1}]"

    async def after_tool(
        self,
        context: AgentRunContext,
        call: ToolCall,
        result: ToolMessage,
        error: Exception | None,
    ) -> None:
        """Replace an over-long result with a preview of it and a note naming the file that holds it.

        Both outcomes are handled, since a failed call's message can be long too. Nothing here may fail a tool
        call: whatever goes wrong — no session yet, a folder that cannot be written — the result is left as the
        tool wrote it, and the model still has it.
        """
        if call.name == OWN_TRUNCATION or not isinstance(result.content, str):
            return
        session_id = context.config.session_id
        if not isinstance(session_id, str) or lightly_under_budget(result.content):
            return
        try:
            kept = await asyncio.to_thread(self._keep, result.content, call, session_id)
        except (OSError, ValueError):
            return
        if kept is not None:
            result.content = kept

    def _keep(self, text: str, call: ToolCall, session_id: str) -> str | None:
        """Write ``text`` whole into the session's folder and return what stands in its place.

        Returns ``None`` when the result is already small enough: the encode that decides it costs what the text
        costs, so it is paid here, off the event loop, and not twice.
        """
        if not over_budget(text):
            return None
        path = self._write(text, call, session_id)
        marker = f"\n... [middle omitted; the whole of it is at {path} — read with read_tool_output] ...\n"
        preview = stream_preview(path, marker=marker)
        if not preview.truncated:
            # The budget here is a little over the preview's, so this cannot happen while the two constants
            # hold; a file left behind with the text sent whole would be worse than no file at all.
            path.unlink(missing_ok=True)
            return None
        return preview.text

    def _write(self, text: str, call: ToolCall, session_id: str) -> Path:
        """Write the result to a new file in the session's ``tool-output`` folder, and return its path."""
        kept = self._store.session_dir(session_id) / KEPT_OUTPUT
        kept.mkdir(parents=True, exist_ok=True)
        stem = _stem(call)
        suffix = 1
        while True:
            target = kept / (f"{stem}.txt" if suffix == 1 else f"{stem}-{suffix}.txt")
            # The name is claimed by creating it, not by asking whether it is free: two calls of one name can
            # reach the folder at the same time, and `exists()` then a write would let them share a file.
            try:
                # `newline=""` because the preview reads these bytes back: text mode would write `\r\n` on
                # Windows, so the model would be shown a file that says something its `read` does not.
                with target.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except FileExistsError:
                suffix += 1
                continue
            return target


def over_budget(text: str) -> bool:
    """Return whether a result is longer than a tool may send: either more bytes or more lines than the budget."""
    return len(text.encode("utf-8")) > MAX_RESULT_BYTES or len(text.splitlines()) > MAX_RESULT_LINES


def lightly_under_budget(text: str) -> bool:
    """Return whether ``text`` is certainly within the budget, without encoding it.

    A character is at most four bytes in UTF-8, so a result of fewer than a quarter of the byte budget in
    characters, with fewer line boundaries than the line budget, cannot be over it. The boundaries are the ones
    ``str.splitlines()`` counts, not just ``\n``: a result written with carriage returns only is as many lines as
    one with newlines, and a guard that missed them would send it whole.

    This is the cheap answer read before the work goes to a thread: the encode that decides the rest costs what
    the text costs, which is the reason it is off the loop.
    """
    boundaries = sum(text.count(break_) for break_ in LINE_BREAKS)
    return len(text) * 4 <= MAX_RESULT_BYTES and boundaries + 1 <= MAX_RESULT_LINES


def _stem(call: ToolCall) -> str:
    """Return the name a kept file is given: the tool and the call, with anything a path could not hold removed."""
    cleaned = _UNSAFE.sub("-", f"{call.name}-{call.id}").strip("-.")
    return cleaned[:MAX_STEM].strip("-.") or "output"


__all__ = [
    "LINE_BREAKS",
    "MAX_RESULT_BYTES",
    "MAX_RESULT_LINES",
    "OWN_TRUNCATION",
    "LongOutputExtension",
    "lightly_under_budget",
    "over_budget",
]
