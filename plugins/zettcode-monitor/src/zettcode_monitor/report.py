"""Render the recorded calls of one session as a single self-contained HTML page."""

from __future__ import annotations

import html
import json
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any


def render_report(session_id: str, calls: list[dict[str, Any]], *, workspace: str = "") -> str:
    """Return the page: one HTML document with the data embedded and nothing fetched."""
    data = {
        "session": session_id,
        "workspace": workspace,
        "exported_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "calls": calls,
    }
    # "<" is escaped so that no string in the data can close the script element.
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("<", "\\u003c").replace("\u2028", "\\u2028")
    template = files("zettcode_monitor").joinpath("report.html").read_text(encoding="utf-8")
    return template.replace("__TITLE__", html.escape(session_id[:8])).replace("__DATA__", payload)


def write_report(path: Path, content: str) -> Path:
    """Write the page, creating the folder, and return the absolute path."""
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target.resolve()
