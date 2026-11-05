"""The ``@`` provider for the files of the workspace."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from heapq import nsmallest
from pathlib import Path
from time import monotonic
from typing import TypeAlias

from zettcode.mention import Mention, MentionProvider

__all__ = ["LISTING_SECONDS", "MAX_CANDIDATES", "MAX_FILES", "SKIP_DIRECTORIES", "FileMentions"]

#: Directories ``@`` never offers files from: version control, the dependency
#: trees, and the caches. They are where a repository keeps things nobody wants
#: to reference in a message, and walking them is most of what a listing costs.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "site-packages",
        "dist",
        "build",
        "target",
    }
)

#: Files offered in one listing. A repository larger than this is listed up to
#: here rather than not at all, and the walk stops as soon as the cap is reached.
MAX_FILES = 4000

#: Candidates returned for one query. The menu shows a handful; the rest would be
#: scrolled past, and building them on every keystroke is the cost this bounds.
MAX_CANDIDATES = 40

#: How long a listing is reused. Long enough that typing a path walks the tree
#: once instead of once a keystroke, short enough that a file made in the
#: meantime shows up in the menu.
LISTING_SECONDS = 15.0

#: One listed file: its path, the path lowercased, and its name lowercased. Built
#: once per walk, because the menu is filtered again on every keystroke and a
#: listing of thousands would otherwise be lowercased and split every time.
ListedFile: TypeAlias = tuple[str, str, str]


class FileMentions(MentionProvider):
    """Files in the workspace, so a draft can point at one by path.

    The listing is not the completeness of ``ls``: it is what a reader is likely to
    type after an ``@``, so the version control and dependency directories are
    skipped and there is a cap. What a token expands to is a sentence naming the
    path, not the file's contents: the model has ``read_file``, and inlining a
    file nobody needs would spend context on it.
    """

    kind = "file"

    def __init__(self, workspace: Path, *, clock: Callable[[], float] = monotonic) -> None:
        """List ``workspace`` when something first asks, and remember it for a while.

        Args:
            workspace: Directory to walk; the paths offered are relative to it.
            clock: Time source, injectable so a test can age the listing.
        """
        self.workspace = workspace
        self._clock = clock
        self._files: tuple[ListedFile, ...] = ()
        self._listed_at: float | None = None

    def _listing(self) -> tuple[ListedFile, ...]:
        """Return the workspace's files, walking it again when the listing is stale.

        The walk happens on the first keystroke after an ``@``, so it is bounded three
        ways: the directories nobody references are never entered, the walk stops at
        :data:`MAX_FILES`, and the result is reused for :data:`LISTING_SECONDS`.
        """
        now = self._clock()
        if self._listed_at is not None and now - self._listed_at < LISTING_SECONDS:
            return self._files
        found: list[ListedFile] = []
        for root, directories, names in os.walk(self.workspace):
            directories[:] = sorted(
                name for name in directories if name not in SKIP_DIRECTORIES and not name.startswith(".")
            )
            base = Path(root)
            for name in sorted(names):
                path = (base / name).relative_to(self.workspace).as_posix()
                found.append((path, path.lower(), name.lower()))
                if len(found) >= MAX_FILES:
                    break
            if len(found) >= MAX_FILES:
                break
        self._files = tuple(found)
        self._listed_at = now
        return self._files

    def candidates(self, query: str) -> Sequence[Mention]:
        """Offer the files whose path matches ``query``, the likeliest ones first.

        A path that starts with what was typed, or whose file name does, comes
        before one that merely contains it: ``@cli`` should offer
        ``cli.py`` before ``src/zettcode/tui/render/cli_helper.py``.
        """
        lowered = query.lower()
        ranked: list[tuple[int, int, str]] = []
        for path, path_lower, name_lower in self._listing():
            if path_lower.startswith(lowered) or name_lower.startswith(lowered):
                rank = 0
            elif lowered in path_lower:
                rank = 1
            else:
                continue
            ranked.append((rank, len(path), path))
        # Only the rows that will be shown are ordered: a one-letter query can match a
        # listing of thousands in hundreds of places, and sorting all of those is work
        # the menu never shows.
        return tuple(
            Mention(token=f"@{path}", kind=self.kind, name=path, description=described)
            for _, _, path in nsmallest(MAX_CANDIDATES, ranked)
            if (described := self._describe(path)) is not None
        )

    def _describe(self, path: str) -> str | None:
        """Return the menu's one line for a file: how big it is, or ``None`` if it is gone.

        Asking the file also drops one that was deleted since the listing, which is
        the one way a cached listing goes wrong while it is being typed into.
        """
        try:
            size = (self.workspace / path).stat().st_size
        except OSError:
            return None
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} kB"
        return f"{size / (1024 * 1024):.1f} MB"

    def expand(self, name: str) -> str | None:
        """Name the path for the model, which reads it with a tool if it matters.

        A directory is named as one, because the tool to reach for is not
        ``read_file`` and saying so is cheaper than the model finding out.
        """
        target = self.workspace / name
        if target.is_dir():
            return (
                f'The reader pointed at the directory "{name}" in the workspace; '
                "list or search it with the file tools when it matters."
            )
        if not target.is_file():
            return None
        return (
            f'The reader pointed at the file "{name}" in the workspace; '
            "read it before answering when its contents matter."
        )
