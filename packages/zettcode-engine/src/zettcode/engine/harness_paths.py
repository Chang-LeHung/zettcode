"""Where a session's just-in-time tools live: one workspace folder, then the session, then the repository.

The layout is ``<harness_dir>/<workspace>/<session id>/<repository>``. The framework underneath takes a root and
appends the session id, so the plugin passes it the workspace folder; the command that lists repositories asks this
module for the same path. An installation from before the workspace level has ``<harness_dir>/<session id>/``; that
directory is moved under the workspace the first time the session asks for it, so the model keeps its tools.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig


def workspace_directory_name(workspace: Path) -> str:
    """Return the folder name one workspace's sessions live under: its directory name and a short path digest.

    Two checkouts called ``app`` must not share a folder, and a name that is a Windows device name (``CON``) must
    not be created at all; the digest makes the first unambiguous and the second harmless.
    """
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", workspace.name, flags=re.ASCII).strip("._-") or "workspace"
    digest = hashlib.sha1(str(workspace.resolve()).encode()).hexdigest()[:8]
    return f"{name}-{digest}"


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
    if not legacy.is_dir():
        return current
    try:
        current.parent.mkdir(parents=True, exist_ok=True)
        if not current.exists():
            os.replace(legacy, current)
            return current
        # Both exist: keep what the new folder already has, move over only what it lacks, then drop the empty old one.
        for child in legacy.iterdir():
            target = current / child.name
            if not target.exists():
                try:
                    os.replace(child, target)
                except OSError:
                    pass
        try:
            legacy.rmdir()
        except OSError:
            pass
    except OSError:
        return legacy
    return current


def session_directory(config: ZettCodeConfig, session_id: str) -> Path:
    """Return this session's directory under the workspace root, moving a pre-workspace one into it first."""
    return move_session(config.harness_dir, harness_root(config), session_id)
