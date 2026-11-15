"""Small JSON files the gateway keeps in its own folder: read one that may be missing or damaged, and write one whole.

Every file the gateway remembers (profiles, the inbox, read marks, the roster, which session hosts it, the run file) is
a document that is rewritten in full. A reader of such a file must never see half of one, and a damaged file must not
stop the gateway from starting, so the two halves are kept here once instead of being repeated at each place.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any | None:
    """Return the document in ``path``, or ``None`` when the file is missing, unreadable, or not JSON.

    A caller checks the shape it expects (``isinstance``) as it always has: this says only that there was no document.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(
    path: Path,
    value: Any,
    *,
    private: bool = False,
    ensure_ascii: bool = True,
    indent: int | None = None,
) -> None:
    """Write ``value`` to ``path`` as one step: the file is the old document or the new one, never a part of either.

    The text goes to a file beside it (named for this process, so two gateways of one user do not share one) which then
    replaces ``path``; a failure leaves nothing behind. ``private`` makes the file readable by this account only, for
    what holds a token or what people said.

    Raises:
        OSError: The folder cannot be made or the file cannot be written; the caller says whether that matters.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = json.dumps(value, ensure_ascii=ensure_ascii, indent=indent)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666)
        if private and hasattr(os, "fchmod"):
            # POSIX only; a temporary left by an earlier run keeps its old mode otherwise.
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
