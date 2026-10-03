"""The conversation log: its JSONL record union and the parsed read model.

Records are a tree, not a list. Every record names the node it continues from::

    m1 ── m2 ── m3 ── m4 ── m5        <- the head is the last message written
                 └── C (a checkpoint through m3)

* The **head** is the last message line in the file. Appending continues from
  it, and a *fork* is therefore a plain append: write a message whose ``parent``
  is an older node and the abandoned branch stays in the file, out of context.
* A **checkpoint** is an annotation rather than a conversation node: its
  ``parent`` is the last message it summarizes. The summary applies to any
  branch that still contains that boundary, and a checkpoint never becomes the
  parent of later messages.
* The **active branch** is the chain from the head back to the first message.
  Its context is the newest checkpoint whose boundary sits on that chain, plus
  the messages after it (see :meth:`Session.active`).

Message bodies are the runtime's own types: ``AnyMessage``, ``MessageTiming``,
and ``ModelUsage`` are imported from ``zett-agent`` rather than restated, and
the ``{"kind": ..., "data": ...}`` envelope is the runtime's own
``encode_messages``/``decode_messages`` pair, called at this module's edge.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_serializer, field_validator
from zett_agent import AnyMessage, MessageTiming, ModelUsage
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.storage import decode_messages, encode_messages

STORE_FILE = "data.jsonl"
STORE_VERSION = 1
MAX_AGENT_NAME = 64

# Session ids become directory names, so they may not escape the store root.
SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: A JSON value, as the stored metadata and tags can contain.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def now() -> datetime:
    """Return the current UTC time, so every writer stamps records the same way."""
    return datetime.now(UTC)


class LineKind(StrEnum):
    """Discriminator values of the record union, written as ``kind``."""

    SESSION = "session"
    MESSAGE = "message"
    COMPACTION = "compaction"


def _load_messages(value: object) -> object:
    """Decode stored ``{"kind", "data"}`` envelopes into runtime messages.

    The runtime's decoder owns the kind-to-type union, so this module never
    restates the message schema. A value that already holds decoded messages —
    when a caller re-validates a line this process just built — passes through.
    """
    if isinstance(value, (tuple, list)) and (not value or not isinstance(value[0], dict)):
        return value
    return tuple(decode_messages(json.dumps(list(value))))


def _dump_messages(messages: Sequence[AnyMessage]) -> list[dict[str, object]]:
    """Encode runtime messages into the stored envelope form."""
    return json.loads(encode_messages(list(messages)))


class SessionLine(BaseModel):
    """The first line of a session file: identity and origin."""

    kind: Literal[LineKind.SESSION] = LineKind.SESSION
    version: int
    session_id: str
    parent_session_id: str | None = None
    agent_name: str | None = None
    created_at: datetime


class MessageLine(BaseModel):
    """One message, continuing from ``parent``."""

    kind: Literal[LineKind.MESSAGE] = LineKind.MESSAGE
    id: str
    parent: str | None = None
    session_id: str
    request_id: str
    message: tuple[AnyMessage, ...]
    timing: MessageTiming
    usage: ModelUsage | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    tags: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("message", mode="before")
    @classmethod
    def _messages_from_storage(cls, value: object) -> object:
        """Read the stored envelope list back into typed runtime messages."""
        return _load_messages(value)

    @field_serializer("message", when_used="json")
    def _messages_to_storage(self, value: Sequence[AnyMessage]) -> list[dict[str, object]]:
        """Write typed runtime messages as the stored envelope list."""
        return _dump_messages(value)


class CompactionLine(BaseModel):
    """One checkpoint summarizing the branch up to ``parent``."""

    kind: Literal[LineKind.COMPACTION] = LineKind.COMPACTION
    id: str
    parent: str
    version: int
    message: tuple[CompactedMessage, ...]
    created_at: datetime

    @field_validator("message", mode="before")
    @classmethod
    def _messages_from_storage(cls, value: object) -> object:
        """Read the stored summary envelope back into a typed checkpoint body."""
        return _load_messages(value)

    @field_serializer("message", when_used="json")
    def _messages_to_storage(self, value: Sequence[AnyMessage]) -> list[dict[str, object]]:
        """Write the typed summary as the stored envelope list."""
        return _dump_messages(value)


Line = Annotated[SessionLine | MessageLine | CompactionLine, Field(discriminator="kind")]
LINES = TypeAdapter(Line)


@dataclass(frozen=True, slots=True)
class Session:
    """One parsed session file: its header, every record, and the active branch.

    Attributes:
        header: The session line, or ``None`` for a file that has none yet.
        messages: Every message line in file order, across all branches.
        compactions: Every checkpoint in file order.
        head_id: Id of the last message written, which the next append continues
            from. A tree can have several leaves, so "the head" is a choice and
            this is the store's: the most recent append wins, which is what
            makes a fork a plain append.
    """

    header: SessionLine | None
    messages: tuple[MessageLine, ...]
    compactions: tuple[CompactionLine, ...]
    head_id: str | None

    @property
    def session_id(self) -> str:
        """Return the session id; every listed session has a header."""
        assert self.header is not None
        return self.header.session_id

    @property
    def parent_session_id(self) -> str | None:
        """Return the conversation this one was delegated from, if any."""
        return self.header.parent_session_id if self.header is not None else None

    @property
    def agent_name(self) -> str | None:
        """Return the agent profile that owns the session, when set."""
        return self.header.agent_name if self.header is not None else None

    @property
    def message_count(self) -> int:
        """Return the number of stored messages, ignoring checkpoints."""
        return len(self.messages)

    def message(self, message_id: str) -> MessageLine | None:
        """Return one message by id."""
        return next((line for line in self.messages if line.id == message_id), None)

    def index(self, message_id: str) -> int | None:
        """Return a message's position in the file, or None when it is absent."""
        return next((index for index, line in enumerate(self.messages) if line.id == message_id), None)

    def branch(self) -> tuple[MessageLine, ...]:
        """Return the active branch, oldest first: the head and its ancestors.

        A fork leaves the abandoned branch in the file; this walk is what keeps
        the fork out of the active context.
        """
        by_id = {line.id: line for line in self.messages}
        branch: list[MessageLine] = []
        current = self.head_id
        while current is not None:
            line = by_id.get(current)
            if line is None:
                break
            branch.append(line)
            current = line.parent
        branch.reverse()
        return tuple(branch)

    def checkpoint_for(self, branch: tuple[MessageLine, ...] | None = None) -> CompactionLine | None:
        """Return the newest checkpoint whose boundary the branch still contains."""
        on_branch = {line.id for line in (self.branch() if branch is None else branch)}
        applicable = [line for line in self.compactions if line.parent in on_branch]
        return max(applicable, key=lambda line: line.version, default=None)

    @property
    def latest_compaction(self) -> CompactionLine | None:
        """Return the highest-version checkpoint in the file, on any branch."""
        return max(self.compactions, key=lambda line: line.version, default=None)

    def active(self) -> tuple[CompactionLine | None, tuple[MessageLine, ...]]:
        """Return the checkpoint and the messages that make up the model context.

        The messages are the part of the active branch after the checkpoint's
        boundary, oldest first.
        """
        branch = self.branch()
        checkpoint = self.checkpoint_for(branch)
        if checkpoint is None:
            return None, branch
        for position, line in enumerate(branch):
            if line.id == checkpoint.parent:
                return checkpoint, branch[position + 1 :]
        return checkpoint, branch  # unreachable: the boundary is on the branch

    @property
    def created_at(self) -> datetime:
        """Return when the session's first record was written."""
        assert self.header is not None  # a file always starts with its header
        return self.header.created_at

    @property
    def updated_at(self) -> datetime:
        """Return the time of the newest record, falling back to the header."""
        stamps = [*self.messages, *self.compactions]
        if stamps:
            return max(line.created_at for line in stamps)
        assert self.header is not None  # a file always starts with its header
        return self.header.created_at
