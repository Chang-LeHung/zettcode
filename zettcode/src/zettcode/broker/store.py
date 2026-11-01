"""What the broker remembers: the messages that passed through it, and the groups sessions have formed.

SQLite from the standard library, one file beside the broker's note (``broker.db``), opened in write-ahead mode so that
a second process reading it (``sqlite3 broker.db``) does not block the broker. The hub calls it from the event loop; every statement is a
single indexed lookup or insert, so it is not worth a thread.

A message is stored once it has been handed over, with the names its sender and recipient had at that moment: the
roster only lists sessions that are connected, and a history that could not say who ``@parser`` was last week would be
of little use. Only the newest :data:`KEEP` messages are kept.

A store that cannot be opened or written must never stop messages from flowing, so the hub treats every failure here as
"nothing was remembered" (see :meth:`~.hub.Hub._remember`).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("zettcode.broker")

#: How many messages are kept; older ones are deleted as new ones arrive.
KEEP = 20_000

#: The most a single query returns.
MAX_ROWS = 2_000

#: The shape of the file; changed whenever a table or column does, which rebuilds it (see :meth:`Store._versioned`).
SCHEMA_VERSION = 1

KIND_SESSION = "session"
KIND_GROUP = "group"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    from_id     TEXT NOT NULL,
    from_handle TEXT NOT NULL,
    from_title  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    to_handle   TEXT NOT NULL,
    to_title    TEXT NOT NULL,
    recipients  TEXT NOT NULL,
    text        TEXT NOT NULL,
    via         TEXT NOT NULL,
    hops        INTEGER NOT NULL,
    mode        TEXT NOT NULL,
    status      TEXT NOT NULL,
    disposition TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages (ts);
CREATE INDEX IF NOT EXISTS messages_pair ON messages (kind, from_id, to_id);
CREATE TABLE IF NOT EXISTS groups (
    name       TEXT PRIMARY KEY,
    created    REAL NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    name       TEXT NOT NULL,
    session_id TEXT NOT NULL,
    joined     REAL NOT NULL,
    PRIMARY KEY (name, session_id)
);
CREATE INDEX IF NOT EXISTS members_session ON members (session_id);
"""


def _wire(row: sqlite3.Row) -> dict[str, Any]:
    """Return a stored message as it goes over the wire (the shape the gateway's page reads)."""
    to: dict[str, Any] = (
        {"kind": KIND_GROUP, "name": row["to_id"]}
        if row["kind"] == KIND_GROUP
        else {"kind": KIND_SESSION, "session_id": row["to_id"], "handle": row["to_handle"], "title": row["to_title"]}
    )
    try:
        recipients = json.loads(row["recipients"])
    except ValueError:
        recipients = []
    return {
        "id": row["id"],
        "ts": row["ts"],
        "from": {"session_id": row["from_id"], "handle": row["from_handle"], "title": row["from_title"]},
        "to": to,
        "recipients": recipients if isinstance(recipients, list) else [],
        "text": row["text"],
        "via": row["via"],
        "hops": row["hops"],
        "mode": row["mode"],
        "status": row["status"],
        "disposition": row["disposition"],
    }


class TooNew(OSError):
    """The file was written by a newer ZettCode than this one; it is left as it is and nothing is remembered in it."""


class Store:
    """The broker's memory.

    Args:
        path: The database file, or ``":memory:"`` for one that lives and dies with the process (the default of a hub
            nobody gave a file, which is every test).
        clock: Wall-clock seconds, injectable for tests.
        keep: How many messages to keep.
    """

    def __init__(self, path: Path | str = ":memory:", *, clock: Any = time.time, keep: int = KEEP) -> None:
        self.clock = clock
        self.keep = keep
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._db = self._connect()
        self._versioned()
        self._db.executescript(_SCHEMA)
        self._added = 0

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self._path), isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        if str(self._path) != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
        return db

    def _versioned(self) -> None:
        """Make the file this version's, or refuse it.

        A file of an older shape is discarded and made again: without that a column added later would make every
        insert fail, and the hub treats a failed insert as "not remembered", so the history would stop being written
        while the broker looked healthy. A file of a newer shape is never touched, because it was written by a newer
        ZettCode and holds a transcript this one cannot read: that is :class:`TooNew`.
        """
        have = self._db.execute("PRAGMA user_version").fetchone()[0]
        if have > SCHEMA_VERSION:
            self._db.close()
            raise TooNew(
                f"{self._path} was written by a newer ZettCode (layout {have}, this one reads {SCHEMA_VERSION})"
            )
        if have not in (0, SCHEMA_VERSION):
            logger.warning("store.rebuilt", extra={"was": have, "now": SCHEMA_VERSION, "path": str(self._path)})
            self._db.close()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{self._path}{suffix}").unlink(missing_ok=True)
            self._db = self._connect()
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        """Close the file; safe to call twice."""
        try:
            self._db.close()
        except sqlite3.Error:
            pass

    # -- messages ---------------------------------------------------------------------------------
    def add_message(
        self,
        *,
        sender: tuple[str, str, str],
        kind: str,
        to: tuple[str, str, str],
        recipients: list[str],
        text: str,
        via: str,
        hops: int,
        mode: str,
        status: str,
        disposition: str,
    ) -> dict[str, Any]:
        """Remember a message and return it as it goes over the wire.

        Args:
            sender: Its session id, handle and title.
            kind: :data:`KIND_SESSION` or :data:`KIND_GROUP`.
            to: The recipient's session id, handle and title; for a group its name twice and an empty title.
            recipients: The session ids that took it.
        """
        now = float(self.clock())
        cursor = self._db.execute(
            "INSERT INTO messages (ts, from_id, from_handle, from_title, kind, to_id, to_handle, to_title,"
            " recipients, text, via, hops, mode, status, disposition) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, *sender, kind, *to, json.dumps(recipients), text, via, hops, mode, status, disposition),
        )
        self._added += 1
        if self._added % 200 == 0:
            self._db.execute("DELETE FROM messages WHERE id <= (SELECT MAX(id) FROM messages) - ?", (self.keep,))
        return self._one(cursor.lastrowid)

    def _one(self, row_id: int | None) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM messages WHERE id = ?", (row_id,)).fetchone()
        return _wire(row)

    def _page(self, where: str, args: tuple[Any, ...], limit: int, before: int | None) -> list[dict[str, Any]]:
        """Return the newest ``limit`` messages that match, oldest first; ``before`` is the id to page back from."""
        limit = max(1, min(int(limit), MAX_ROWS))
        clause = f"({where})" + (" AND id < ?" if before is not None else "")
        rows = self._db.execute(
            f"SELECT * FROM messages WHERE {clause} ORDER BY id DESC LIMIT ?",  # noqa: S608 - fixed fragments
            (*args, *(() if before is None else (before,)), limit),
        ).fetchall()
        return [_wire(row) for row in reversed(rows)]

    def between(self, a: str, b: str, *, limit: int = 20, before: int | None = None) -> list[dict[str, Any]]:
        """Return the one-to-one messages the two sessions exchanged."""
        return self._page(
            "kind = 'session' AND ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))",
            (a, b, b, a),
            limit,
            before,
        )

    def in_group(self, name: str, *, limit: int = 20, before: int | None = None) -> list[dict[str, Any]]:
        """Return what was said in a group."""
        return self._page("kind = 'group' AND to_id = ?", (name,), limit, before)

    def involving(self, session_id: str, *, limit: int = 20, before: int | None = None) -> list[dict[str, Any]]:
        """Return every one-to-one message a session sent or received."""
        return self._page("kind = 'session' AND (from_id = ? OR to_id = ?)", (session_id, session_id), limit, before)

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return the newest messages of any kind, oldest first."""
        return self._page("1", (), limit, None)

    def before(self, before: int, limit: int) -> list[dict[str, Any]]:
        """Return the newest ``limit`` messages with an id below ``before``, oldest first."""
        return self._page("1", (), limit, before)

    def has_before(self, row_id: int) -> bool:
        """Return whether any message is stored with an id below ``row_id``."""
        return self._db.execute("SELECT 1 FROM messages WHERE id < ? LIMIT 1", (row_id,)).fetchone() is not None

    def window(self, since: float, until: float, *, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        """Return the messages sent in ``[since, until]``, oldest first: what a replay of the past is drawn from.

        When more than ``limit`` fall in the window the newest ones are returned.
        """
        return self._page("ts >= ? AND ts <= ?", (since, until), limit, None)

    def span(self) -> tuple[float, float] | None:
        """Return the times of the oldest and the newest message, or ``None`` when there are none."""
        row = self._db.execute("SELECT MIN(ts) AS lo, MAX(ts) AS hi FROM messages").fetchone()
        return None if row["lo"] is None else (row["lo"], row["hi"])

    def session_by_handle(self, handle: str) -> str | None:
        """Return the id of the session that last went by a handle, or ``None``."""
        row = self._db.execute(
            "SELECT CASE WHEN from_handle = ?1 THEN from_id ELSE to_id END AS sid FROM messages"
            " WHERE from_handle = ?1 OR (kind = 'session' AND to_handle = ?1) ORDER BY id DESC LIMIT 1",
            (handle,),
        ).fetchone()
        return None if row is None else row["sid"]

    def edges(self) -> list[dict[str, Any]]:
        """Return, for each pair of sessions that exchanged messages, how many and when last."""
        rows = self._db.execute(
            "SELECT MIN(from_id, to_id) AS a, MAX(from_id, to_id) AS b, COUNT(*) AS count, MAX(ts) AS last"
            " FROM messages WHERE kind = 'session' GROUP BY 1, 2 ORDER BY last DESC LIMIT 500"
        ).fetchall()
        return [{"a": row["a"], "b": row["b"], "count": row["count"], "last": row["last"]} for row in rows]

    # -- groups -----------------------------------------------------------------------------------
    def group_names(self) -> list[str]:
        """Return the names of all groups."""
        return [row["name"] for row in self._db.execute("SELECT name FROM groups ORDER BY created, name")]

    def group(self, name: str) -> dict[str, Any] | None:
        """Return a group with its members, or ``None``."""
        row = self._db.execute("SELECT * FROM groups WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        members = [
            m["session_id"]
            for m in self._db.execute(
                "SELECT session_id FROM members WHERE name = ? ORDER BY joined, session_id", (name,)
            )
        ]
        return {"name": row["name"], "created": row["created"], "created_by": row["created_by"], "members": members}

    def groups(self) -> list[dict[str, Any]]:
        """Return every group with its members."""
        return [g for g in (self.group(name) for name in self.group_names()) if g is not None]

    def create_group(self, name: str, created_by: str, members: list[str]) -> None:
        """Create a group; the caller has checked that the name is free."""
        now = float(self.clock())
        self._db.execute("BEGIN")
        try:
            self._db.execute("INSERT INTO groups (name, created, created_by) VALUES (?,?,?)", (name, now, created_by))
            for member in members:
                self.add_member(name, member)
            self._db.execute("COMMIT")
        except BaseException:
            # A failed commit leaves the transaction open, and the next BEGIN on this connection would then fail.
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def add_member(self, name: str, session_id: str) -> None:
        """Add a session to a group; already being in it changes nothing."""
        self._db.execute(
            "INSERT OR IGNORE INTO members (name, session_id, joined) VALUES (?,?,?)",
            (name, session_id, float(self.clock())),
        )

    def remove_member(self, name: str, session_id: str) -> None:
        """Remove a session from a group, and delete the group when nobody is left."""
        self._db.execute("DELETE FROM members WHERE name = ? AND session_id = ?", (name, session_id))
        left = self._db.execute("SELECT COUNT(*) AS n FROM members WHERE name = ?", (name,)).fetchone()["n"]
        if left == 0:
            self.delete_group(name)

    def delete_group(self, name: str) -> None:
        """Delete a group and its membership; what was said in it stays in the history."""
        self._db.execute("DELETE FROM members WHERE name = ?", (name,))
        self._db.execute("DELETE FROM groups WHERE name = ?", (name,))

    def groups_of(self, session_id: str) -> list[dict[str, Any]]:
        """Return the groups a session is a member of."""
        names = [
            row["name"] for row in self._db.execute("SELECT name FROM members WHERE session_id = ?", (session_id,))
        ]
        found = (self.group(name) for name in sorted(names))
        return [g for g in found if g is not None]
