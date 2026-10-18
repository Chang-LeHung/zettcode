"""What a request did to the files, added up: the data behind the summary at the end of a turn."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath

from .entries import DeleteEntry, Entry, EntryStatus, FileChangeEntry, FileSummary


def shown_path(path: str, workspace: PurePath | None) -> str:
    """Return a file as the reader knows it: relative to the workspace when it is inside it.

    The model names the same file as ``app.py`` in one call and as ``/work/app.py`` in the next, and
    the summary must not count them twice. Only the text is looked at, never the disk.

    Args:
        path: The path as the call named it.
        workspace: The directory the session works in, or ``None`` to leave every path as it is.
    """
    if workspace is None or not path:
        return path
    candidate = PurePath(path)
    # Rooted, not only absolute: on Windows ``/work/a.py`` has a root and no drive, which is not
    # "absolute" to pathlib, and it still has to be compared with the workspace it is inside.
    if candidate.is_absolute() or candidate.root:
        try:
            return candidate.relative_to(workspace).as_posix()
        except ValueError:
            return path
    return candidate.as_posix()


def changed_files(entries: Iterable[Entry], workspace: PurePath | None = None) -> tuple[FileSummary, ...]:
    """Return the files a run of entries changed, each once, in the order they were first touched.

    Only a call that *succeeded* counts: a failed edit changed nothing, and a skipped one never ran.
    A file changed several times is one row with the totals. A file deleted and then written again is
    a file that exists, counted from the write, and one written and then deleted is deleted.

    Args:
        entries: The entries of one request, in order; anything that is not a file change is ignored.
        workspace: The directory paths are shown relative to.
    """
    order: list[str] = []
    totals: dict[str, FileSummary] = {}
    for entry in entries:
        if not isinstance(entry, (FileChangeEntry, DeleteEntry)) or entry.status is not EntryStatus.COMPLETED:
            continue
        if not entry.path:
            continue
        path = shown_path(entry.path, workspace)
        if path not in totals:
            order.append(path)
            totals[path] = FileSummary(path)
        current = totals[path]
        if isinstance(entry, DeleteEntry):
            totals[path] = FileSummary(path, deleted=True)
            continue
        base = FileSummary(path) if current.deleted else current
        totals[path] = FileSummary(
            path, base.added + entry.added, base.removed + getattr(entry, "removed", 0), deleted=False
        )
    return tuple(totals[path] for path in order)
