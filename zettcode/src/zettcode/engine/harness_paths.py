"""Where a session's just-in-time tools live: one workspace folder, then the session, then the repository.

The layout is ``<harness_dir>/<workspace>/<session id>/<repository>``. The framework underneath takes a root and
appends the session id, so the plugin passes it the workspace folder; the command that lists repositories asks this
module for the same path. An installation from before the workspace level has ``<harness_dir>/<session id>/``; that
directory is moved under the workspace the first time the session asks for it, so the model keeps its tools.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig


def workspace_directory_name(workspace: Path) -> str:
    """Return the folder name one workspace's sessions live under: its directory name, safe as a path segment."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", workspace.name, flags=re.ASCII).strip("._-")
    return name or "workspace"


def harness_root(config: ZettCodeConfig) -> Path:
    """Return the root the harness appends a session id to: ``<harness_dir>/<workspace>``."""
    return config.harness_dir / workspace_directory_name(config.workspace)


def move_session(legacy_root: Path, root: Path, session_id: str) -> Path:
    """Return this session's directory under ``root``, moving ``legacy_root``'s copy into it first.

    A move this cannot make leaves the old directory where it is and returns that path, so nothing is lost and a
    reader still sees the repositories.
    """
    from zett_agent.jit_harness.repo import session_directory_name

    name = session_directory_name(session_id)
    current = root / name
    legacy = legacy_root / name
    if legacy.is_dir() and not current.exists():
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            os.replace(legacy, current)
        except OSError:
            return legacy
    return current


def session_directory(config: ZettCodeConfig, session_id: str) -> Path:
    """Return this session's directory under the workspace root, moving a pre-workspace one into it first."""
    return move_session(config.harness_dir, harness_root(config), session_id)
