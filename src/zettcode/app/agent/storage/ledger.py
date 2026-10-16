"""What a workspace's sessions have spent: tokens by model, by session, and by day.

Every model reply is stored with the usage its provider reported, so the totals ``/usage``
shows are read back from the conversation files rather than kept in a second place that could
disagree with them. A reader never builds a :class:`~zettcode.app.agent.storage.records.Session`
for this: it looks at one line at a time, parses only the lines that carry usage, and takes from
them the counters and the model's name.

**What is counted.** The sessions the reader works in. A subagent's session names an agent
(``agent_name`` in its header) and is left out: its tokens are real, but they are not part of
any conversation the reader had.

**A fork is not counted twice.** ``/fork`` copies the conversation into a new session together
with the usage of each reply, so adding every session up would charge the same answer to both.
A reply is identified by the request it answered, when it was written, the model that wrote it
and what it reported; the first session to hold it, in the order the sessions began, keeps it,
and a copy of it elsewhere is not counted. A fork therefore shows only what it spent after the
fork.

**Days** are the reader's own: a reply written at 23:30 UTC belongs to the day it was in the
reader's time zone, which is the day a calendar on their screen should put it on. The index
below keeps the moment, not the day, so changing time zone changes nothing it stored.

**The index.** Reading is a pass over every byte of every conversation, which is a fraction of a
second for tens of megabytes and many seconds for gigabytes, so what a pass finds is kept in
``usage.json`` beside the session folders. A conversation file is append-only, so the index
records, for each one, how far it was read and a fingerprint of the bytes at its start and just
before that point; the next read checks the fingerprints and reads only what came after. A file
that no longer matches (replaced, or edited in the part already read) is read again from the
beginning, and a damaged, foreign, or older index is ignored whole. The index is never the
truth, only a way to avoid re-reading it: deleting it costs one slow read, and it is written
best-effort, so a read-only store or two processes writing at once cost nothing but a re-read.
A rewrite that keeps both fingerprinted ends is not noticed; nothing in this program makes one.
"""

from __future__ import annotations

import json
import os
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO

from .layout import find_workspace
from .metadata import SESSION_METADATA_FILE
from .records import SAFE_SESSION_ID, STORE_FILE

#: The model a reply is filed under when its message does not say.
UNKNOWN_MODEL = "unknown"

#: The index, in the workspace's folder beside the session folders (which is where
#: ``metadata.jsonl`` already sits, so a session listing never mistakes it for a session).
INDEX_FILE = "usage.json"

#: Bumped when the index's shape changes; an index of another version is ignored.
INDEX_VERSION = 1

#: Bytes at the start of a file, and bytes before the read point, that fingerprint a file.
HEAD_BYTES = 256
TAIL_BYTES = 64

#: A quarter of an hour: every time zone's midnight falls on one, so a day is worked out once
#: for each and not once for each reply.
BUCKET_SECONDS = 900

#: One reply as the index keeps it: request id, stored timestamp, UTC seconds, model, then the
#: input, output, cache-read and reasoning counters.
Row = tuple[str, str, int, str, int, int, int, int]


@dataclass(slots=True)
class Tally:
    """Token counters added up over some replies.

    ``input_tokens`` already contains what came from the provider's cache and
    ``output_tokens`` already contains reasoning, as the provider reports them, so
    :attr:`total` is their sum and nothing is counted twice.
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        """Return everything sent plus everything generated."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_share(self) -> float | None:
        """Return the cached share of all input, or ``None`` before there is any."""
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else None

    def add(self, other: Tally) -> None:
        """Add another tally's counters into this one."""
        self.requests += other.requests
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.reasoning_tokens += other.reasoning_tokens


@dataclass(frozen=True, slots=True)
class SessionUsage:
    """What one session spent, and when it began and last changed."""

    session_id: str
    title: str | None
    started: datetime
    updated: datetime
    tally: Tally
    models: tuple[str, ...]


@dataclass(slots=True)
class Ledger:
    """A workspace's usage three ways: by model, by session, and by day.

    Attributes:
        sessions: One row per counted session, newest first. A session that has not
            spent anything is a row of zeros, so the list is the list ``/resume`` shows.
        models: Totals by model name.
        days: Totals by calendar day, only for days something was spent.
        total: Everything, which is also the sum of any one of the three.
    """

    sessions: list[SessionUsage] = field(default_factory=list)
    models: dict[str, Tally] = field(default_factory=dict)
    days: dict[date, Tally] = field(default_factory=dict)
    total: Tally = field(default_factory=Tally)

    @property
    def empty(self) -> bool:
        """Return whether no reply has been counted at all."""
        return self.total.requests == 0


def parse_time(text: object) -> datetime | None:
    """Return a stored UTC timestamp as an aware datetime, or ``None`` when it is not one."""
    if not isinstance(text, str):
        return None
    try:
        # ``fromisoformat`` only learned the trailing ``Z`` in 3.11.
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _count(value: object) -> int:
    """Return a stored counter, reading anything that is not a whole number as zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _model_of(message: object) -> str:
    """Return the model a stored message names, which sits inside its first envelope."""
    try:
        name = message[0]["data"]["model"]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return UNKNOWN_MODEL
    return name if isinstance(name, str) and name else UNKNOWN_MODEL


def _row_of(line: str) -> Row | None:
    """Return the reply a stored line records, or ``None`` when it records none."""
    # Most lines carry no usage; this keeps them from being parsed at all. A serializer that
    # leaves out the space after the colon is read the same.
    if '"usage":' not in line or '"usage": null' in line or '"usage":null' in line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("kind") != "message":
        return None
    usage = record.get("usage")
    moment = parse_time(record.get("created_at"))
    if not isinstance(usage, dict) or moment is None:
        return None
    return (
        str(record.get("request_id")),
        str(record.get("created_at")),
        int(moment.timestamp()),
        _model_of(record.get("message")),
        _count(usage.get("input_tokens")),
        _count(usage.get("output_tokens")),
        _count(usage.get("cache_read_tokens")),
        _count(usage.get("reasoning_tokens")),
    )


def _key_of(row: Row) -> tuple[str, str, str, int, int, int]:
    """Return what identifies a reply across sessions: a copy of it has the same key."""
    return (row[0], row[1], row[3], row[4], row[5], row[6])


@dataclass(frozen=True, slots=True)
class _File:
    """What is known of one conversation file: its replies, and how far they were read.

    Attributes:
        size: Bytes the file had when it was looked at; with ``mtime_ns``, "nothing changed".
        mtime_ns: Its modification time then.
        offset: Bytes consumed, which stops before a final line that has no newline yet.
        head: Fingerprint of the first bytes, so another file under the same name is noticed.
        tail: Fingerprint of the bytes just before ``offset``, so an edit in what was read is.
        started: The header's ``created_at``, as stored.
        counted: False for a subagent's session, whose replies are never read.
        rows: The replies found so far.
    """

    size: int
    mtime_ns: int
    offset: int
    head: int
    tail: int
    started: str | None
    counted: bool
    rows: tuple[Row, ...]


def _fingerprint(handle: BinaryIO, start: int, end: int) -> int:
    """Return a checksum of the bytes from ``start`` to ``end``, clipped to the file's start."""
    start = max(0, start)
    handle.seek(start)
    return zlib.crc32(handle.read(max(0, end - start)))


def _header_of(first: bytes) -> tuple[str | None, bool]:
    """Return when a session began, as stored, and whether it is one the reader had."""
    try:
        header = json.loads(first.decode("utf-8", errors="replace"))
    except ValueError:
        return None, True
    if not isinstance(header, dict):
        return None, True
    created = header.get("created_at")
    return (created if isinstance(created, str) else None), header.get("agent_name") is None


def _scan(path: Path, previous: _File | None) -> _File | None:
    """Read one conversation file, continuing from ``previous`` when the file only grew.

    Returns ``None`` when the file cannot be read at all.
    """
    try:
        stat = path.stat()
        with path.open("rb") as handle:
            head = _fingerprint(handle, 0, HEAD_BYTES)
            if (
                previous is not None
                and previous.head == head
                and 0 < previous.offset <= stat.st_size
                and _fingerprint(handle, previous.offset - TAIL_BYTES, previous.offset) == previous.tail
            ):
                if not previous.counted:
                    return replace(previous, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                offset, started, counted, rows = previous.offset, previous.started, True, list(previous.rows)
            else:
                handle.seek(0)
                first = handle.readline()
                # A header with no newline yet is a session still being born: read nothing of it.
                offset = len(first) if first.endswith(b"\n") else 0
                started, counted = _header_of(first)
                rows = []
            if counted and offset:
                handle.seek(offset)
                for raw in handle:
                    # A line without its newline is still being written: leave it for next time.
                    if not raw.endswith(b"\n"):
                        break
                    offset += len(raw)
                    row = _row_of(raw.decode("utf-8", errors="replace"))
                    if row is not None:
                        rows.append(row)
            tail = _fingerprint(handle, offset - TAIL_BYTES, offset)
    except OSError:
        return None
    return _File(stat.st_size, stat.st_mtime_ns, offset, head, tail, started, counted, tuple(rows))


def _title_of(folder: Path) -> str | None:
    """Return the title a session's metadata file holds, if there is one."""
    try:
        data = json.loads((folder / SESSION_METADATA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    title = data.get("title") if isinstance(data, dict) else None
    return title if isinstance(title, str) and title.strip() else None


def _whole(value: object) -> bool:
    """Say whether a stored value is an integer (a boolean is not one here)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _row_from_index(row: object) -> Row:
    """Check one stored row's shape and return it as a tuple; raise ``ValueError`` if it is odd."""
    if not isinstance(row, list) or len(row) != 8:
        raise ValueError("a row has eight fields")
    request, created, seconds, model, *counters = row
    if not (isinstance(request, str) and isinstance(created, str) and isinstance(model, str)):
        raise ValueError("a row's text fields are text")
    if not all(_whole(number) for number in (seconds, *counters)):
        raise ValueError("a row's counters are whole numbers")
    return (request, created, seconds, model, *counters)


def _file_from_index(item: object) -> _File | None:
    """Rebuild one file's entry from the index, or ``None`` when it is not a well-formed one."""
    if not isinstance(item, dict):
        return None
    try:
        size, mtime_ns, offset, head, tail = (item[name] for name in ("size", "mtime_ns", "offset", "head", "tail"))
        started, counted = item["started"], item["counted"]
        if not all(_whole(number) for number in (size, mtime_ns, offset, head, tail)):
            return None
        if not isinstance(counted, bool) or not (started is None or isinstance(started, str)):
            return None
        rows = tuple(_row_from_index(row) for row in item["rows"])
    except (KeyError, TypeError, ValueError):
        return None
    return _File(size, mtime_ns, offset, head, tail, started, counted, rows)


class LedgerReader:
    """Reads a workspace's ledger, reading as little as it can.

    Two things are remembered. In memory, each file's result is kept while its size and
    modification time are as they were, so opening ``/usage`` again a minute later reads the
    session being worked in and nothing else. On disk, the index (see the module's notes) lets a
    program that has just started pick up where the last one stopped, and lets a file that has
    grown be read from where it was last read instead of from its first byte.
    """

    def __init__(self, root: str | Path, workspace: str | Path, *, index: bool = True) -> None:
        """Name the store and the workspace; nothing is read or created yet.

        Args:
            root: The directory holding one folder per workspace.
            workspace: The project whose sessions are counted.
            index: Keep the index on disk. ``False`` is the in-memory behaviour alone.
        """
        self.directory = find_workspace(Path(root).expanduser(), workspace)
        self.index_path = self.directory / INDEX_FILE
        self._use_index = index
        self._files: dict[str, _File] = {}
        self._loaded = False

    def read(self) -> Ledger:
        """Return the ledger of every session the workspace holds right now."""
        if not self._loaded:
            self._loaded = True
            if self._use_index:
                self._files = self._load_index()
        found: list[tuple[datetime, str, Path, _File]] = []
        kept: dict[str, _File] = {}
        changed = False
        for path in sorted(self.directory.glob(f"*/{STORE_FILE}")):
            session_id = path.parent.name
            if not SAFE_SESSION_ID.match(session_id) or ".." in session_id:
                continue
            cached = self._files.get(session_id)
            try:
                stat = path.stat()
            except OSError:
                continue
            if cached is not None and cached.size == stat.st_size and cached.mtime_ns == stat.st_mtime_ns:
                read: _File | None = cached
            else:
                read = _scan(path, cached)
                changed = True
            if read is None:
                continue
            kept[session_id] = read
            if read.counted:
                began = parse_time(read.started) or datetime.fromtimestamp(0, tz=timezone.utc)
                found.append((began, session_id, path, read))
        # A session folder deleted since the last read is forgotten with it.
        changed = changed or kept.keys() != self._files.keys()
        self._files = kept
        if changed and self._use_index and kept:
            self._save_index(kept)
        return _fold(found)

    # -- the index ------------------------------------------------------------
    def _load_index(self) -> dict[str, _File]:
        """Return the files the index on disk describes, or none when it cannot be trusted."""
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
            return {}
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            return {}
        files: dict[str, _File] = {}
        for session_id, item in sessions.items():
            entry = _file_from_index(item)
            if entry is not None:
                files[session_id] = entry
        return files

    def _save_index(self, files: dict[str, _File]) -> None:
        """Write the index whole and atomically; a store that cannot be written is left alone."""
        payload = {
            "version": INDEX_VERSION,
            "sessions": {
                session_id: {
                    "size": item.size,
                    "mtime_ns": item.mtime_ns,
                    "offset": item.offset,
                    "head": item.head,
                    "tail": item.tail,
                    "started": item.started,
                    "counted": item.counted,
                    "rows": [list(row) for row in item.rows],
                }
                for session_id, item in files.items()
            },
        }
        temporary = self.index_path.with_name(f"{INDEX_FILE}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self.index_path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass


def _fold(found: Iterable[tuple[datetime, str, Path, _File]]) -> Ledger:
    """Fold sessions, oldest first, into a ledger that charges each reply once."""
    ledger = Ledger()
    seen: set[tuple[str, str, str, int, int, int]] = set()
    days: dict[int, date] = {}
    for started, session_id, path, read in sorted(found, key=lambda item: (item[0], item[1])):
        tally = Tally()
        models: dict[str, None] = {}
        for row in read.rows:
            key = _key_of(row)
            if key in seen:
                continue
            seen.add(key)
            reply = Tally(1, row[4], row[5], row[6], row[7])
            tally.add(reply)
            ledger.models.setdefault(row[3], Tally()).add(reply)
            bucket = row[2] // BUCKET_SECONDS
            if bucket not in days:
                moment = datetime.fromtimestamp(bucket * BUCKET_SECONDS, tz=timezone.utc)
                days[bucket] = moment.astimezone().date()
            ledger.days.setdefault(days[bucket], Tally()).add(reply)
            models[row[3]] = None
        ledger.total.add(tally)
        try:
            updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            updated = started
        title = _title_of(path.parent)
        ledger.sessions.append(SessionUsage(session_id, title, started, updated, tally, tuple(models)))
    ledger.sessions.reverse()
    return ledger
