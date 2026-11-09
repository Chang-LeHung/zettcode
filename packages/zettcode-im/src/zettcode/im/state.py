"""What the bridge has to remember between two starts.

The IM side is stateless on purpose (``agim`` keeps nothing), so this is the only place the continuity lives:
the login handshake and its credentials, the cursor a ``receive`` call answered with, the session the daemon
runs, and the reply context of each chat. ``send`` needs that context back, and a restart mid-batch re-delivers
the batch rather than dropping the messages behind the first one, which is why the cursor is written only after
a message has been answered.

Nothing here talks to the network. A file that cannot be read is treated as a first run — the worst it costs is
a login — and a file that cannot be written is an error the caller has to see, because a bridge that silently
loses its cursor re-answers messages the reader has already read.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How many event ids are remembered, so a re-delivered batch is answered once. The platform hands a batch back
#: whole after a restart, and a batch is small; a hundred is several restarts of slack.
SEEN_LIMIT = 200

#: How many chats keep their reply context. One entry per chat is tiny, and a chat that falls out of it simply
#: loses the quoting, not the answer.
CHATS_LIMIT = 100


@dataclass
class BridgeState:
    """Everything the bridge persists, in one file."""

    #: The login handshake as the IM client gave it, verbatim: its QR payload and the provider state behind it.
    handshake: dict[str, Any] = field(default_factory=dict)
    #: What a finished login handed back; the token the client needs to send and poll.
    credentials: dict[str, Any] = field(default_factory=dict)
    #: The cursor the last answered message came with.
    cursor: str = ""
    #: The session the daemon runs. Empty until the first message starts one.
    session_id: str = ""
    #: The reply context of the last message of each chat, by chat id.
    chats: dict[str, str] = field(default_factory=dict)
    #: Event ids already answered, oldest first.
    seen: list[str] = field(default_factory=list)
    #: What the bridge was started with, so the worker needs no flags: where the daemon works, the model it runs on,
    #: its shell level, and who may drive it.
    workspace: str = ""
    model: str = ""
    effort: str = ""
    permission: str = "safe"
    allow: list[str] = field(default_factory=list)
    allow_all: bool = False
    #: Where this state came from. Not written into the file; it is what :meth:`save` writes back to by default.
    path: Path | None = field(default=None, compare=False, repr=False)

    # -- what the bridge asks -------------------------------------------------------------------------
    @property
    def logged_in(self) -> bool:
        """Return whether a login has finished, which is what a run needs: a login without a token is not one."""
        return bool(self.token())

    def token(self) -> str:
        """Return the bot token a finished login produced, or an empty string.

        The IM client hands it over inside ``credentials`` — ``{"config": {...}, "secrets": {...}}`` — and a token
        read from the wrong level is an empty string that looks like a login until the first send fails, so both
        the nested shape and a flat one are read.
        """
        secrets = self.credentials.get("secrets")
        value = secrets.get("bot_token") if isinstance(secrets, dict) else None
        if not isinstance(value, str) or not value:
            value = self.credentials.get("bot_token")
        return value if isinstance(value, str) else ""

    def answered(self, event_id: str) -> bool:
        """Return whether this message has already been answered."""
        return event_id in self.seen

    def remember(self, event_id: str, *, cursor: str, chat_id: str, reply_token: str | None) -> None:
        """Record that a message has been answered, and the context the next answer of that chat needs."""
        if event_id and event_id not in self.seen:
            self.seen.append(event_id)
            del self.seen[:-SEEN_LIMIT]
        self.cursor = cursor
        if reply_token:
            self.chats[chat_id] = reply_token
            while len(self.chats) > CHATS_LIMIT:
                self.chats.pop(next(iter(self.chats)))
        else:
            self.chats.pop(chat_id, None)

    def reply_token(self, chat_id: str) -> str | None:
        """Return the context token of the last message of this chat, if it had one."""
        return self.chats.get(chat_id)

    # -- the file -------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> BridgeState:
        """Read the state at ``path``; a missing or unreadable file is a first run."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path=path)
        if not isinstance(raw, dict):
            return cls(path=path)
        state = cls(path=path)
        handshake = raw.get("handshake")
        state.handshake = handshake if isinstance(handshake, dict) else {}
        credentials = raw.get("credentials")
        state.credentials = credentials if isinstance(credentials, dict) else {}
        cursor = raw.get("cursor")
        state.cursor = cursor if isinstance(cursor, str) else ""
        session_id = raw.get("session_id")
        state.session_id = session_id if isinstance(session_id, str) else ""
        chats = raw.get("chats")
        if isinstance(chats, dict):
            state.chats = {str(key): value for key, value in chats.items() if isinstance(value, str)}
        seen = raw.get("seen")
        if isinstance(seen, list):
            state.seen = [item for item in seen if isinstance(item, str)][-SEEN_LIMIT:]
        state.workspace = _text(raw.get("workspace"))
        state.model = _text(raw.get("model"))
        state.effort = _text(raw.get("effort"))
        state.permission = _text(raw.get("permission")) or "safe"
        allow = raw.get("allow")
        state.allow = [item for item in allow if isinstance(item, str)] if isinstance(allow, list) else []
        state.allow_all = raw.get("allow_all") is True
        return state

    def save(self, path: Path | None = None) -> None:
        """Write the state to ``path`` (this state's own file by default), all at once, readable by this user only.

        The write goes to a temporary file in the same directory and is moved into place, so a process killed
        mid-write leaves the previous state rather than half of this one — a torn cursor is a re-answered batch.
        """
        target = path or self.path
        if target is None:
            raise ValueError("this state has no file; pass the path to save it to")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "handshake": self.handshake,
            "credentials": self.credentials,
            "cursor": self.cursor,
            "session_id": self.session_id,
            "chats": self.chats,
            "seen": self.seen,
            "workspace": self.workspace,
            "model": self.model,
            "effort": self.effort,
            "permission": self.permission,
            "allow": self.allow,
            "allow_all": self.allow_all,
        }
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _text(value: object) -> str:
    """Return ``value`` when it is a string, and an empty string for anything a damaged file may hold instead."""
    return value if isinstance(value, str) else ""


__all__ = ["BridgeState", "CHATS_LIMIT", "SEEN_LIMIT"]
