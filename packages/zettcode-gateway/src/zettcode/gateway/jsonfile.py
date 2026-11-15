"""Small JSON files the gateway keeps in its own folder: read one that may be missing or damaged, and write one whole.

Every file the gateway remembers (profiles, the inbox, read marks, the roster, which session hosts it, the run file) is
a document that is rewritten in full. A reader of such a file must never see half of one, and a damaged file must not
stop the gateway from starting, so the two halves are kept here once instead of being repeated at each place.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

#: Numbers the temporary files of this process, so that two writes of one file never share one.
_writes = itertools.count(1)


def read_json(path: Path) -> object | None:
    """Return the document in ``path``, or ``None`` when the file is missing, unreadable, or not JSON.

    The caller checks the shape it expects with ``isinstance``: this says only whether there was a document.
    """
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value


def write_json(
    path: Path,
    value: Any,
    *,
    private: bool = False,
    ensure_ascii: bool = True,
    indent: int | None = None,
) -> None:
    """Write ``value`` to ``path`` as one step: the file is the old document or the new one, never a part of either.

    The text goes to a hidden file beside it, named for this process and this write (so neither another gateway of the
    same user nor a second write of the same file shares it), which then replaces ``path``; a failure leaves nothing
    behind. ``private`` asks for a file readable by this account only, for what holds a token or what people said: the
    temporary is created with that mode, so the document is never wider than it, and a filesystem that holds no modes
    simply has none.

    Raises:
        OSError: The folder cannot be made or the file cannot be written; the caller says whether that matters.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{next(_writes)}.tmp")
    text = json.dumps(value, ensure_ascii=ensure_ascii, indent=indent)
    try:
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
