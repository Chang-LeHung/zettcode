"""Session metadata: one small file per session, and the old per-workspace log it replaced.

**The file.** Each session folder holds a ``metadata.json`` beside its ``data.jsonl``::

    {"version": 1, "session_id": "01a1...", "created_at": "...", "updated_at": "...",
     "title": "Fix the parser", "model": "gpt-5-mini"}

It is written when a session begins, when it is renamed, and when the model it uses changes, and
at no other time — about two hundred bytes, whatever the conversation does. A file written before
the model was recorded simply has none, and a reader that does not know the field ignores it, so
the layout version is unchanged. What a list needs besides that is when the
conversation last changed, and the conversation file already says so: its modification time moves
with every message it is given, so the age a list shows is read from there instead of being
written down again on every append. The folder is also the unit a person copies, moves or
deletes, so the metadata that describes a session now travels with it.

Writes replace the file whole (a temporary file, then a rename), so a reader sees the old file or
the new one and never half of either. A file that is missing, damaged, or names another session
is not an error: it is rebuilt from what the store still knows, which is how a session survives
losing it.

**The log it replaced.** ``metadata.jsonl`` sat beside the session folders and took one line per
write — and one write per *message*, so it grew without bound: thousands of lines for a
workspace, a few hundred bytes for every message ever sent, folded in full on every read::

    {"created_at": "...", "kind": "session",  "session_id": "01a1..."}
    {"kind": "activity", "session_id": "01a1...", "updated_at": "..."}
    {"kind": "title",    "session_id": "01a1...", "title": "Fix the parser"}

Nothing writes it any more. It is still *read*, for a session that has no file of its own: that is
a session an older version made, and the store copies what the log says about it into the
session's folder the first time it is looked at, so the log is consulted once per old session and
never again. A torn final line is ignored, as in a conversation file, because a crash can cut the
line being written.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from zettcode._compat import StrEnum

#: The old per-workspace log, inside the workspace folder. Read, never written.
METADATA_FILE = "metadata.jsonl"

#: One session's own metadata, inside its folder.
SESSION_METADATA_FILE = "metadata.json"

#: Layout of :class:`SessionMetadata` on disk. A reader that finds a number it does not know
#: treats the file as missing and rebuilds it, so a newer layout is never half-understood.
SESSION_METADATA_VERSION = 1

MAX_TITLE = 200
MAX_MODEL = 200


class SessionMetadata(BaseModel):
    """What a session says about itself, in its own folder.

    Attributes:
        version: Layout of this file.
        session_id: The session it describes; a file that names another session — a folder
            copied under a new name — is not trusted.
        created_at: When the session's first record was written.
        updated_at: The newest conversation activity this file knows of. Not the whole answer:
            the conversation file's own modification time is newer after any later message, and
            :func:`effective_updated_at` takes the later of the two.
        title: The display title, or ``None`` while the session is unnamed.
        model: The model the session last used, by the name the model picker shows, or ``None``
            before any turn has run. It is what resuming the session switches back to. It is
            written when it *changes*, not on every turn, so it costs the file no more writes
            than a rename does.
    """

    version: int = SESSION_METADATA_VERSION
    session_id: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    model: str | None = None
    #: This session's own choice about letting the model request compaction: ``True`` or ``False``, or
    #: ``None`` when it never chose and follows the configuration's default. Older files hold no choice.
    self_compact: bool | None = Field(default=None, strict=True)
    #: The permission level this session last ran at — ``ask``, ``safe``, ``full`` or ``deny`` — or ``None`` when
    #: it never chose one and a run starts at the level it was built with. Resuming the session puts it back in
    #: force, so a reader who chose ``full`` for a job does not answer the question again on the next start.
    permission: str | None = None


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What a session list needs about one session.

    Attributes:
        session_id: Session identity.
        title: Display title written by the application, or ``None`` when the
            session is unnamed.
        created_at: When the session's first record was written.
        updated_at: When its conversation last changed; a title write does not move it,
            so the age a list shows is conversation activity.
    """

    session_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


def info_of(metadata: SessionMetadata, conversation: Path | None = None) -> SessionInfo:
    """Return the list row a session's metadata makes, with its real last-activity time.

    Args:
        metadata: The session's own file.
        conversation: The conversation file, whose modification time is when the session last
            changed; ``None`` leaves the stored time as it is.
    """
    return SessionInfo(
        metadata.session_id,
        metadata.title,
        metadata.created_at,
        effective_updated_at(metadata, conversation),
    )


def effective_updated_at(metadata: SessionMetadata, conversation: Path | None) -> datetime:
    """Return when the session last changed: the later of the stored time and the file's.

    The file's time wins for every session written since this layout began, because every
    message moves it. The stored time wins when a copy of the folder has an older one — and is
    what carries the right order across for a session an older version recorded.
    """
    if conversation is None:
        return metadata.updated_at
    try:
        modified = datetime.fromtimestamp(conversation.stat().st_mtime_ns / 1e9, tz=timezone.utc)
    except OSError:
        return metadata.updated_at
    return max(metadata.updated_at, modified)


def read_session_metadata(path: Path, session_id: str) -> SessionMetadata | None:
    """Return a session's own metadata, or ``None`` when it has to be rebuilt.

    ``None`` is the answer for a missing file, one that does not parse, one in a layout this
    version does not know, and one that names another session. None of those is an error the
    reader can do anything about, and each has the same remedy.

    Args:
        path: The session's ``metadata.json``.
        session_id: The session the folder belongs to.
    """
    try:
        text = path.read_bytes()
    except OSError:
        return None
    try:
        found = SessionMetadata.model_validate_json(text)
    except ValidationError:
        return None
    if found.version != SESSION_METADATA_VERSION or found.session_id != session_id:
        return None
    return found


def write_session_metadata(path: Path, metadata: SessionMetadata) -> bool:
    """Replace a session's metadata file whole, and report whether it was written.

    The new text goes to a temporary file in the same folder and is renamed over the old one,
    so a reader never sees half of a write and two writers cannot interleave their bytes. A
    failure — a read-only store, a full disk — leaves the old file as it was and returns
    ``False``: metadata is never worth failing a conversation for, and the next look at the
    session rebuilds what was not saved.
    """
    text = json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, allow_nan=False, sort_keys=True)
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False
        )
        temporary = handle.name
        with handle:
            handle.write(text + "\n")
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
        return False
    return True


# -- the log this replaced: read, to carry old sessions over ---------------------------------


class MetadataKind(StrEnum):
    """Discriminator values of the old log's records, written as ``kind``."""

    SESSION = "session"
    ACTIVITY = "activity"
    TITLE = "title"


class SessionStarted(BaseModel):
    """A session's first record in the old log: when its conversation began."""

    kind: Literal[MetadataKind.SESSION] = MetadataKind.SESSION
    session_id: str
    created_at: datetime


class SessionActivity(BaseModel):
    """One activity stamp in the old log: the newest one is the session's last change."""

    kind: Literal[MetadataKind.ACTIVITY] = MetadataKind.ACTIVITY
    session_id: str
    updated_at: datetime


class SessionTitle(BaseModel):
    """One display title in the old log; the newest line for a session replaces the earlier ones."""

    kind: Literal[MetadataKind.TITLE] = MetadataKind.TITLE
    session_id: str
    title: str


MetadataRecord: TypeAlias = Annotated[SessionStarted | SessionActivity | SessionTitle, Field(discriminator="kind")]
# The alias is a ``TypeForm`` pydantic accepts; mypy 1.20 does not read an ``Annotated`` union as one.
METADATA: TypeAdapter[SessionStarted | SessionActivity | SessionTitle] = TypeAdapter(cast(Any, MetadataRecord))


def read_metadata(path: Path) -> list[SessionInfo]:
    """Fold the old log into one row per session, newest activity first.

    Args:
        path: The log; a missing file is an empty log, not an error.

    Returns:
        Every session the log describes. Activity and title lines whose session
        line is absent are ignored, so a truncated or edited file can never
        invent a session.

    Raises:
        ValueError: A line other than the last is damaged.
    """
    rows: dict[str, SessionInfo] = {}
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = METADATA.validate_json(line)
        except ValidationError as error:
            if index == len(lines) - 1:
                break  # A crash can tear the line being appended; the rest is intact.
            raise ValueError(f"Corrupt metadata file {path.name} at line {index + 1}") from error
        match record:
            case SessionStarted():
                rows[record.session_id] = SessionInfo(record.session_id, None, record.created_at, record.created_at)
            case SessionActivity() if (row := rows.get(record.session_id)) is not None:
                rows[record.session_id] = replace(row, updated_at=max(row.updated_at, record.updated_at))
            case SessionTitle() if (row := rows.get(record.session_id)) is not None:
                rows[record.session_id] = replace(row, title=record.title)
    sessions = list(rows.values())
    sessions.sort(key=lambda info: (info.updated_at, info.session_id), reverse=True)
    return sessions
