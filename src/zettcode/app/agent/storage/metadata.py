"""The per-workspace metadata log: titles and activity, without conversations.

``metadata.jsonl`` sits beside the session folders and holds one small record
per line, appended and never rewritten::

    {"created_at": "...", "kind": "session",  "session_id": "01a1..."}
    {"kind": "activity", "session_id": "01a1...", "updated_at": "..."}
    {"kind": "title",    "session_id": "01a1...", "title": "Fix the parser"}

Reading folds the lines in order, so the newest record of each kind wins and a
rename is one more line rather than a rewrite — the same append-only idea the
conversation log uses. A torn final line is ignored, exactly like a session
file, because a crash can cut the line being written.

The file holds one line per write, so it grows with conversation activity; it
stays small next to the conversation it indexes, and listing sessions is one
read of this file instead of one parse per conversation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

#: File name of the metadata log, inside the workspace folder.
METADATA_FILE = "metadata.jsonl"
MAX_TITLE = 200


class MetadataKind(StrEnum):
    """Discriminator values of the metadata union, written as ``kind``."""

    SESSION = "session"
    ACTIVITY = "activity"
    TITLE = "title"


class SessionStarted(BaseModel):
    """A session's first record in the log: when its conversation began."""

    kind: Literal[MetadataKind.SESSION] = MetadataKind.SESSION
    session_id: str
    created_at: datetime


class SessionActivity(BaseModel):
    """One activity stamp: the newest one is the session's last change."""

    kind: Literal[MetadataKind.ACTIVITY] = MetadataKind.ACTIVITY
    session_id: str
    updated_at: datetime


class SessionTitle(BaseModel):
    """One display title; the newest line for a session replaces the earlier ones."""

    kind: Literal[MetadataKind.TITLE] = MetadataKind.TITLE
    session_id: str
    title: str


MetadataRecord = Annotated[SessionStarted | SessionActivity | SessionTitle, Field(discriminator="kind")]
METADATA = TypeAdapter(MetadataRecord)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What a session list needs, folded out of the metadata log.

    Attributes:
        session_id: Session identity, named by every record kind.
        title: Display title written by the application, or ``None`` when the
            session is unnamed.
        created_at: When the session's first record was written.
        updated_at: When its newest conversation record was written; a title
            write does not move it, so the age a list shows is conversation
            activity.
    """

    session_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


def read_metadata(path: Path) -> list[SessionInfo]:
    """Fold the log into one row per session, newest activity first.

    Args:
        path: The metadata file; a missing file is an empty store, not an error.

    Returns:
        Every session the log describes. Activity and title lines whose session
        line is absent are ignored, so a truncated or edited file can never
        invent a session.
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


def append_metadata(path: Path, record: MetadataRecord) -> None:
    """Append one record, creating the file and flushing so a reader sees it whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, allow_nan=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
        handle.flush()
