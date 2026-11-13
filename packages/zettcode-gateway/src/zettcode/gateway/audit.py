"""The gateway's audit log: who signed in, and what each change made through it was, one JSON object per line.

It records the *fact* of an action (when, who by role and address, which route, which target, the answer) and never
its content: no token, no cookie, no message text. A person reading it learns that a message was sent to a session at
a time, not what it said. Writing is best effort: a full disk or a read-only folder must not stop the gateway from
answering, so a failure is logged once and the line is dropped.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("zettcode.gateway.audit")

#: The log is moved to ``audit.jsonl.1`` (replacing the one before) when it grows past this, so it cannot fill a disk.
MAX_BYTES = 5 * 1024 * 1024


class Audit:
    """Appends audit lines to a file only its owner can read."""

    def __init__(self, path: Path, clock: Any = time.time) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._warned = False

    def record(self, event: str, **fields: Any) -> None:
        """Append one line: the time, the ``event`` name, and the fields (``None`` values are left out)."""
        line = {"ts": round(self._clock(), 3), "event": event, **{k: v for k, v in fields.items() if v is not None}}
        try:
            text = json.dumps(line, separators=(",", ":"), ensure_ascii=False)
            with self._lock:
                self._append(text)
        except (OSError, TypeError, ValueError) as error:
            if not self._warned:
                self._warned = True
                logger.warning("audit.failed", extra={"path": str(self.path), "error": type(error).__name__})

    def _append(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size > MAX_BYTES:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the last ``limit`` lines that parse, oldest first; a missing or damaged file is an empty answer."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        found: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                found.append(value)
        return found
