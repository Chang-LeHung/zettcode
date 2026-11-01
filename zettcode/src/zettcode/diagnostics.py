"""Structured diagnostics for the long-running faces of the program.

The terminal, the broker and the gateway are separate processes, and each
already has a place its stderr goes: ``tui.log``, ``broker.log`` and
``gateway.log``. This module adds the event-shaped lines a support report needs
without making the caller import a logging framework or thread a logger through
every layer.

Every line is one JSON object with a UTC timestamp, level, component, event,
process id and whatever safe fields the caller passes. Exception lines carry the
type and, best-effort, the message and traceback. Never pass a prompt, a message
body or a token: the logs are meant to be attached to a report.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: A model error can carry a whole validation input; a report needs the start,
#: not a second copy of the conversation.
MAX_MESSAGE = 2_000

#: Enough for the frames that matter, bounded so a traceback cannot make one
#: line arbitrarily large.
MAX_TRACEBACK = 20_000

_LOCK = threading.Lock()


def _line(component: str, event: str, level: str, fields: dict[str, Any]) -> str:
    record: dict[str, Any] = {
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level,
        "component": component,
        "event": event,
        "pid": os.getpid(),
        **fields,
    }
    # No sort_keys: a caller's mapping may mix key types, and diagnostics must
    # never be the reason a failed command becomes a crashed one.
    return json.dumps(record, ensure_ascii=False, default=str)


def ensure_log_parent(path: Path) -> None:
    """Create the folder a log file lives in, owner-only when this call made it."""
    parent = path.parent
    created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if created and os.name != "nt":
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass


def _append(path: Path, line: str) -> None:
    """Append one line to an owner-only file, creating the folder owner-only too."""
    ensure_log_parent(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        handle = os.fdopen(descriptor, "a", encoding="utf-8")
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    with handle:
        handle.write(line + "\n")
        handle.flush()
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def write(component: str, event: str, *, path: Path | None = None, level: str = "info", **fields: Any) -> None:
    """Append one event to ``path``, or to stderr when no file was named.

    Args:
        component: ``terminal``, ``broker`` or ``gateway``.
        event: Stable machine-readable event name, such as ``turn.failed``.
        path: File to append to; the terminal passes its diagnostics file, while
            the broker and gateway already catch their stderr in their own log.
        level: ``debug``, ``info``, ``warning`` or ``error``.
        fields: Safe, small facts about the event. No prompts, message bodies or
            credentials.
    """
    try:
        line = _line(component, event, level, fields)
    except Exception as error:  # noqa: BLE001 - the logger must not fail its caller
        try:
            line = _line(
                component,
                event,
                "error",
                {"diagnostic_error": f"{type(error).__name__}: {error}"},
            )
        except Exception:  # noqa: BLE001 - nothing sensible to write
            return
    if path is None:
        try:
            print(line, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass
        return
    try:
        with _LOCK:
            _append(path, line)
    except Exception:  # noqa: BLE001 - diagnostics are a convenience, never a failure
        # A full disk, a read-only home or a path that is not a directory must
        # not turn a working command into a failed one.
        pass


def exception(
    component: str,
    event: str,
    error: BaseException,
    *,
    path: Path | None = None,
    level: str = "error",
    trace: bool = True,
    **fields: Any,
) -> None:
    """Append one error event with its type, message and traceback.

    The message and traceback are best-effort: an exception with a broken
    ``__str__`` or an unusable traceback is still recorded by type. The message
    is capped because provider and validation errors can embed a lot of input.
    ``trace=False`` keeps the record for a refusal whose traceback would only
    add noise.
    """
    try:
        message = str(error)[:MAX_MESSAGE]
    except Exception:  # noqa: BLE001 - a broken __str__ must not hide the failure
        message = f"<unprintable {type(error).__name__}>"
    formatted = ""
    if trace:
        try:
            formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        except Exception:  # noqa: BLE001 - a broken traceback must not hide the failure
            formatted = "<traceback unavailable>"
        if len(formatted) > MAX_TRACEBACK:
            marker = "\n<traceback truncated>\n"
            keep = MAX_TRACEBACK - len(marker)
            head, tail = keep // 2, keep - keep // 2
            formatted = formatted[:head] + marker + formatted[-tail:]
    payload: dict[str, Any] = {
        "error": {"type": type(error).__name__, "message": message},
    }
    if trace:
        payload["traceback"] = formatted
    write(
        component,
        event,
        path=path,
        level=level,
        **payload,
        **fields,
    )
