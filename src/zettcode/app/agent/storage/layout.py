"""Which folder under the store root holds one workspace's sessions.

A workspace's folder is named after its path, the levels joined with ``-``::

    /Users/me/projects/api   ->   ~/.zettcode/sessions/-Users-me-projects-api/

so ``ls ~/.zettcode/sessions`` says which folder is which project. Older versions named it with the
URL-safe base64 of the path (``L1VzZXJzL21l...``); a store written that way is **moved** to the new
name the first time it is opened, with one rename, which is atomic: a reader sees the folder under
the old name or under the new one and never half of each.

The move is a courtesy, not a requirement, and it is skipped whenever it is not safe:

* a session in the folder is open in another process (its ``session.lock`` is held), or the system
  refuses the rename because a file in the folder is open (Windows does), and
* the rename fails for any other reason.

In every one of those the workspace **keeps its old name** and is used from there, exactly as before;
the next start tries again. Nothing is copied, so there is never a second copy to reconcile.

Joining with ``-`` is not injective (``/a-b/c`` and ``/a/b-c`` both read ``-a-b-c``), so each folder
records the path it belongs to in :data:`OWNER_FILE`. A folder that names a different path is not
shared: the workspace that finds it taken falls back to its base64 name, which is unique.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

from ....filelock import is_held
from .locks import LOCK_FILE

#: Longest workspace folder name; a longer path keeps a hash instead of its tail.
MAX_KEY_CHARS = 120

#: The file in a workspace folder that says which path the folder belongs to.
OWNER_FILE = "workspace.txt"

#: Everything a folder name keeps as it is; any other character becomes ``-``.
_UNSAFE = re.compile(r"[^\w.-]")


def _resolve(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve()


def legacy_workspace_key(workspace: str | Path) -> str:
    """Return the name older versions gave the workspace's folder: the base64 of its path.

    The URL-safe base64 of the resolved absolute path without padding. A path too long for one file
    name keeps a short digest instead of its tail.
    """
    encoded = base64.urlsafe_b64encode(str(_resolve(workspace)).encode()).decode().rstrip("=")
    if len(encoded) <= MAX_KEY_CHARS:
        return encoded
    digest = hashlib.sha256(encoded.encode()).hexdigest()[:12]
    return f"{encoded[: MAX_KEY_CHARS - 13]}-{digest}"


def workspace_key(workspace: str | Path) -> str:
    """Return the folder name that groups one workspace's sessions: its path with ``-`` between the levels.

    Every character that is not a letter, a digit, ``_``, ``.`` or ``-`` becomes ``-`` (so the path
    separators, a drive's colon and a space all do), which keeps the name one folder and legal on every
    platform. A name too long for one file keeps a short digest of the whole instead of its tail.
    """
    text = _UNSAFE.sub("-", str(_resolve(workspace)))
    if len(text) <= MAX_KEY_CHARS:
        return text
    digest = hashlib.sha256(str(_resolve(workspace)).encode()).hexdigest()[:12]
    return f"{text[: MAX_KEY_CHARS - 13]}-{digest}"


def _owner(folder: Path) -> str | None:
    """Return the path a folder says it belongs to, or ``None`` when it does not say."""
    try:
        return (folder / OWNER_FILE).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        return None


def _is_ours(folder: Path, path: Path) -> bool:
    """Say whether a folder under the readable name may hold this workspace's sessions.

    A folder that records no owner is taken as ours: it was made by a run that stopped before it wrote
    the note, and only a path joined to the same name could be the other claimant.
    """
    owner = _owner(folder)
    return owner is None or owner == str(path)


def _claim(folder: Path, path: Path) -> None:
    """Write the note that says the folder is this path's, if it has none. Never fails."""
    if _owner(folder) is not None:
        return
    try:
        (folder / OWNER_FILE).write_text(f"{path}\n", encoding="utf-8")
    except OSError:
        pass


def _in_use(folder: Path) -> bool:
    """Say whether a process has a session in the folder open (its lock is held)."""
    try:
        locks = sorted(folder.glob(f"*/{LOCK_FILE}"))
    except OSError:
        return True
    return any(is_held(lock) for lock in locks)


def _choose(root: Path, path: Path, *, move: bool) -> Path:
    """Return the folder to use, moving the old one to the new name first when ``move`` allows."""
    readable = root / workspace_key(path)
    legacy = root / legacy_workspace_key(path)
    if readable.is_dir():
        return readable if _is_ours(readable, path) else legacy
    if legacy == readable or not legacy.is_dir():
        return readable
    if not move or _in_use(legacy):
        return legacy
    try:
        os.rename(legacy, readable)
    except OSError:
        # Another process may have moved it a moment ago; otherwise the system said no (a file is
        # open), and the workspace stays where it was.
        return readable if readable.is_dir() and _is_ours(readable, path) else legacy
    _claim(readable, path)
    return readable


def find_workspace(root: str | Path, workspace: str | Path) -> Path:
    """Return the folder a workspace's sessions are in now, changing nothing on disk.

    For a reader that must not create anything: it names the readable folder, the old one when that
    is where the sessions still are, and the readable one when there are none yet.
    """
    return _choose(Path(root), _resolve(workspace), move=False)


def open_workspace(root: str | Path, workspace: str | Path) -> Path:
    """Return the folder to write a workspace's sessions in, creating it and moving an old one.

    An old base64 folder is renamed to the readable name when nothing has it open, and stays where it is
    when something does (see the module's notes). The folder exists when this returns.
    """
    path = _resolve(workspace)
    folder = _choose(Path(root), path, move=True)
    folder.mkdir(parents=True, exist_ok=True)
    if folder.name == workspace_key(path):
        _claim(folder, path)
    return folder
