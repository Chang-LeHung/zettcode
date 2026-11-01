"""Process-wide setup for the standard-library loggers.

Every component uses ordinary ``logging`` calls::

    logger = logging.getLogger("zettcode.terminal")
    logger.info("turn.start", extra={"session": session})
    logger.exception("turn.failed")

``setup`` adds one rotating JSON-lines handler under ``~/.zettcode/log``. The
terminal's stderr capture stays in ``tui.log``; structured events go to
``terminal.jsonl`` so rotation never renames the file fd 2 writes to.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_BACKUPS = 3
MAX_MESSAGE = 2_000
MAX_TRACEBACK = 20_000
MAX_RECORD_CHARS = 64_000
DEFAULT_DIR = Path.home() / ".zettcode" / "log"

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }
)


def _env_positive(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_non_negative(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


def level() -> int:
    """Return the configured threshold; an unknown value falls back to info."""
    return _LEVELS.get(os.getenv("ZETTCODE_LOG_LEVEL", "info").strip().lower(), logging.INFO)


def log_path(component: str) -> Path:
    """Return the JSONL file for one component."""
    return DEFAULT_DIR / f"{component}.jsonl"


class _OwnerRotatingHandler(RotatingFileHandler):
    """Rotating handler that creates its file owner-only, not with the umask."""

    def _open(self) -> Any:
        stream = super()._open()
        if os.name != "nt":
            try:
                os.chmod(self.baseFilename, 0o600)
            except OSError:
                pass
        return stream


class JsonFormatter(logging.Formatter):
    """One JSON object per record, including the caller's ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage()[:MAX_MESSAGE],
            "pid": record.process,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info is not None:
            formatted = self.formatException(record.exc_info)
            if len(formatted) > MAX_TRACEBACK:
                marker = "\n<traceback truncated>\n"
                keep = MAX_TRACEBACK - len(marker)
                head, tail = keep // 2, keep - keep // 2
                formatted = formatted[:head] + marker + formatted[-tail:]
            payload["traceback"] = formatted
        line = json.dumps(payload, ensure_ascii=False, default=str)
        if len(line) > MAX_RECORD_CHARS:
            line = json.dumps(
                {
                    "time": payload["time"],
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "event": payload["event"],
                    "pid": payload["pid"],
                    "truncated": True,
                    "original_chars": len(line),
                },
                ensure_ascii=False,
            )
        return line


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


def setup(component: str, *, path: Path | None = None) -> logging.Logger:
    """Configure and return ``zettcode.<component>``; safe to call repeatedly."""
    logger = logging.getLogger(f"zettcode.{component}")
    logger.setLevel(level())
    logger.propagate = False
    logger.handlers.clear()
    target = path or log_path(component)
    try:
        ensure_log_parent(target)
        handler: logging.Handler = _OwnerRotatingHandler(
            target,
            maxBytes=_env_positive("ZETTCODE_LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
            backupCount=_env_non_negative("ZETTCODE_LOG_BACKUPS", DEFAULT_BACKUPS),
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    if not isinstance(handler, logging.NullHandler) and os.name != "nt":
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    return logger


def rotate_text(path: Path, *, max_bytes: int | None = None, backups: int | None = None) -> None:
    """Rotate a text log at startup, before a raw stderr fd opens it."""
    limit = max_bytes if max_bytes is not None else _env_positive("ZETTCODE_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)
    count = backups if backups is not None else _env_non_negative("ZETTCODE_LOG_BACKUPS", DEFAULT_BACKUPS)
    try:
        if not path.is_file() or path.stat().st_size <= limit:
            return
        if count <= 0:
            path.unlink(missing_ok=True)
            return
        for index in range(count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass
