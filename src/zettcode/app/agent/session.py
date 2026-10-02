"""Session storage: the JSONL format, the message tree, and the agent hooks.

One class does the whole job the application sees: :class:`SessionStore` is the
agent plugin — it restores the model context on ``on_state`` and saves messages
and checkpoints from the event stream. The save/load mechanics live in the
standalone :class:`SessionPersistenceMixin` it is built from: the store
directory (``~/.zettcode/sessions`` by default, one ``<session-id>/data.jsonl``
per session), the append-only records, the message tree, and the queries the
application needs.

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

File operations are plain blocking reads and writes: an append is one small
line, and the caller is the single process owning the session. The last line of
a file may be truncated by a crash, so an unparsable *final* line is ignored; a
corrupt line anywhere else raises, because that means real damage.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from weakref import WeakKeyDictionary

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_serializer, field_validator
from zett_agent import (
    AgentExtension,
    AgentRunContext,
    AnyMessage,
    AssistantMessage,
    ExtensionEvent,
    MessageTiming,
    ModelUsage,
    SystemMessage,
    ToolMessage,
    new_uuid7,
)
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.extensions.events import CompactionEvent, MessageAppendedEvent, RunCancelledEvent
from zett_agent.storage import decode_messages, encode_messages

STORE_FILE = "data.jsonl"
STORE_VERSION = 1
MAX_TITLE = 200
MAX_AGENT_NAME = 64

# Session ids become directory names, so they may not escape the store root.
SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: A JSON value, as the stored metadata and tags can contain.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


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


def _context(value: Mapping[str, object] | None, *, field: str, nonempty_keys: bool = False) -> dict[str, object]:
    """Validate one metadata or tags object before it reaches the log."""
    if value is None:
        return {}
    encoded: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field} keys must be strings")
        if nonempty_keys and not key.strip():
            raise ValueError(f"{field} keys cannot be empty")
        encoded[key] = item
    return encoded


def now() -> datetime:
    """Return the current UTC time, so every writer stamps records the same way."""
    return datetime.now(UTC)


class SessionLine(BaseModel):
    """The first line of a session file: identity and display values."""

    kind: Literal[LineKind.SESSION] = LineKind.SESSION
    version: int
    session_id: str
    parent_session_id: str | None = None
    title: str | None = None
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
    def title(self) -> str | None:
        """Return the display title, when the caller set one."""
        return self.header.title if self.header is not None else None

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
    def updated_at(self) -> datetime:
        """Return the time of the newest record, falling back to the header."""
        stamps = [*self.messages, *self.compactions]
        if stamps:
            return max(line.created_at for line in stamps)
        assert self.header is not None  # a file always starts with its header
        return self.header.created_at


@dataclass(slots=True)
class _Request:
    """Persistence bookkeeping for one request-scoped context."""

    request_id: str
    checkpoint_version: int = 0
    #: One stored message id for each replayable non-system context position.
    #: ``None`` marks a context-only message the store was told to skip. The
    #: checkpoint's own position is represented by its boundary message id, so
    #: a later compaction can name the same boundary again.
    context_ids: list[str | None] = field(default_factory=list)


class SessionPersistenceMixin:
    """Standalone mixin: read and write one conversation's JSONL tree.

    It inherits nothing, so it can be combined with the framework's
    ``AgentExtension`` (see :class:`SessionStore`). It owns the storage: the
    session directory layout, parsing and the torn-last-line policy, the tree
    walk, ``read``, ``append``, ``checkpoint``, and ``list_sessions``. It holds
    no framework behavior.

    Args:
        root: Directory holding one ``<session_id>/`` folder per session, each
            with its own ``data.jsonl``. ``None`` uses ``~/.zettcode/sessions``.
            Parent directories are created eagerly.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".zettcode" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        super().__init__()

    # -- files --------------------------------------------------------------
    def session_dir(self, session_id: str) -> Path:
        """Return the directory of one session, refusing ids that leave the store."""
        if not SAFE_SESSION_ID.match(session_id) or ".." in session_id:
            raise ValueError(f"Unsafe session id: {session_id!r}")
        return self.root / session_id

    def session_path(self, session_id: str) -> Path:
        """Return the conversation file of one session."""
        return self.session_dir(session_id) / STORE_FILE

    def session_ids(self) -> Iterator[str]:
        """Yield the id of every session folder this store owns."""
        for path in sorted(self.root.glob(f"*/{STORE_FILE}")):
            session_id = path.parent.name
            if SAFE_SESSION_ID.match(session_id) and ".." not in session_id:
                yield session_id

    def read(self, session_id: str) -> Session:
        """Parse one session file, tolerating a half-written final line."""
        path = self.session_path(session_id)
        if not path.is_file():
            return Session(header=None, messages=(), compactions=(), head_id=None)
        lines = path.read_text(encoding="utf-8").splitlines()
        header: SessionLine | None = None
        messages: list[MessageLine] = []
        compactions: list[CompactionLine] = []
        head_id: str | None = None
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                parsed = LINES.validate_json(line)
            except ValidationError as error:
                if index == len(lines) - 1:
                    break  # A crash can tear the line being appended; the rest is intact.
                raise ValueError(f"Corrupt session file {path.name} at line {index + 1}") from error
            match parsed:
                case SessionLine():
                    header = parsed
                case MessageLine():
                    messages.append(parsed)
                    head_id = parsed.id
                case CompactionLine():
                    compactions.append(parsed)
                case other:
                    raise ValueError(f"Unknown session record: {type(other).__name__}")
        self._check_links(path, messages, compactions)
        return Session(header=header, messages=tuple(messages), compactions=tuple(compactions), head_id=head_id)

    @staticmethod
    def _check_links(path: Path, messages: list[MessageLine], compactions: list[CompactionLine]) -> None:
        """Reject a file whose parent links do not form the tree they claim to.

        Appends only reference already-written nodes, so an unknown parent means
        the file was edited or truncated in the middle; failing here beats
        silently reading a broken history.
        """
        known = {line.id for line in [*messages, *compactions]}
        for line in messages:
            if line.parent is not None and line.parent not in known:
                raise ValueError(f"Unknown parent {line.parent!r} in {path.name}")
        for line in compactions:
            if line.parent not in known:
                raise ValueError(f"Unknown boundary {line.parent!r} in {path.name}")

    def _append_line(self, session_id: str, line: Line) -> None:
        """Append one validated line, flushing so a reader sees whole records."""
        text = json.dumps(line.model_dump(mode="json"), ensure_ascii=False, allow_nan=False, sort_keys=True)
        self.session_dir(session_id).mkdir(parents=True, exist_ok=True)
        with self.session_path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
            handle.flush()

    # -- the store API ------------------------------------------------------
    async def append(
        self,
        session_id: str,
        request_id: str,
        message: AnyMessage,
        timing: MessageTiming | None = None,
        parent_session_id: str | None = None,
        title: str | None = None,
        agent_name: str | None = None,
        metadata: Mapping[str, object] | None = None,
        tags: Mapping[str, object] | None = None,
        usage: ModelUsage | None = None,
        *,
        parent: str | None = None,
    ) -> str:
        """Append one raw message and return its id, linking it into the tree.

        The new message continues from ``parent`` when given, otherwise from the
        head. Passing an older node's id forks the session: the abandoned branch
        stays in the file and drops out of the active context, and later appends
        continue from the fork.
        """
        if title is not None and (not title.strip() or len(title) > MAX_TITLE):
            raise ValueError(f"Session title must contain between 1 and {MAX_TITLE} characters")
        if agent_name is not None and (not agent_name.strip() or len(agent_name) > MAX_AGENT_NAME):
            raise ValueError(f"Agent name must contain between 1 and {MAX_AGENT_NAME} characters")
        if usage is not None and not isinstance(message, AssistantMessage):
            raise ValueError("Model usage belongs only to assistant messages")
        session = self.read(session_id)
        self._write_header(session, session_id, parent_session_id, title, agent_name)
        if parent is None:
            parent = session.head_id
        elif session.message(parent) is None:
            raise ValueError(f"Unknown parent message: {parent!r}")
        node_id = new_uuid7()
        self._append_line(
            session_id,
            MessageLine(
                id=node_id,
                parent=parent,
                session_id=session_id,
                request_id=request_id,
                message=(message,),
                timing=timing or MessageTiming.instant(),
                usage=usage,
                metadata=_context(metadata, field="Message metadata"),
                tags=_context(tags, field="Message tags", nonempty_keys=True),
                created_at=now(),
            ),
        )
        return node_id

    async def checkpoint(
        self,
        session_id: str,
        summary: CompactedMessage,
        boundary_id: str,
        expected_version: int,
    ) -> CompactionLine:
        """Append a checkpoint summarizing the branch through one message."""
        session = self.read(session_id)
        latest = session.latest_compaction
        version = latest.version if latest is not None else 0
        if version != expected_version:
            raise ValueError("Checkpoint conflict; reload the session")
        if session.message(boundary_id) is None:
            raise ValueError("Checkpoint boundary must identify an existing message")
        if latest is not None:
            previous = session.index(latest.parent)
            if previous is not None and session.index(boundary_id) <= previous:
                raise ValueError("Checkpoint boundary must advance beyond the previous one")
        line = CompactionLine(
            id=new_uuid7(),
            parent=boundary_id,
            version=version + 1,
            message=(summary,),
            created_at=now(),
        )
        self._append_line(session_id, line)
        return line

    async def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[Session]:
        """Return sessions by latest activity, newest first."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        sessions = [
            session for session_id in self.session_ids() if (session := self.read(session_id)).header is not None
        ]
        sessions.sort(key=lambda session: (session.updated_at, session.session_id), reverse=True)
        return sessions[offset : offset + limit]

    async def close(self) -> None:
        """Release nothing; every append opens and closes its own handle."""

    def _write_header(
        self,
        session: Session,
        session_id: str,
        request_parent: str | None,
        title: str | None,
        agent_name: str | None,
    ) -> None:
        """Create the session line, rejecting a parent that changed after creation."""
        if session.header is not None:
            if session.header.parent_session_id != request_parent:
                raise ValueError("Session parent cannot change after creation")
            return
        self._append_line(
            session_id,
            SessionLine(
                version=STORE_VERSION,
                session_id=session_id,
                parent_session_id=request_parent,
                title=title,
                agent_name=agent_name,
                created_at=now(),
            ),
        )


class SessionStore(SessionPersistenceMixin, AgentExtension):
    """The agent plugin: restore and save a conversation through the mixin.

    ``SessionPersistenceMixin`` owns the files. This class adds the framework
    hooks — restore the model context on ``on_state``, append messages and write
    checkpoints from the event stream, and drop per-request bookkeeping on
    success, error, or cancellation.

    Args:
        root: Directory holding one ``<session_id>/`` folder per session, each
            with its own ``data.jsonl``; forwarded to the mixin. ``None`` uses
            ``~/.zettcode/sessions``.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._requests: WeakKeyDictionary[AgentRunContext, _Request] = WeakKeyDictionary()
        super().__init__(root)

    async def on_state(self, context: AgentRunContext) -> None:
        """Restore the conversation and map every context position to a message id."""
        checkpoint, tail = await self._restore(context)
        ids: list[str | None] = []
        if checkpoint is not None:
            ids.append(checkpoint.parent)
        ids.extend(
            line.id
            for line in tail
            if line.message[0].include_in_messages and not isinstance(line.message[0], SystemMessage)
        )
        self._requests[context] = _Request(
            request_id=context.config.request_id or new_uuid7(),
            checkpoint_version=checkpoint.version if checkpoint is not None else 0,
            context_ids=ids,
        )

    async def on_event(self, context: AgentRunContext, event: ExtensionEvent) -> None:
        """Append freshly produced messages and checkpoint completed compactions."""
        if isinstance(event, RunCancelledEvent):
            self._requests.pop(context, None)
            return
        request = self._requests.get(context)
        if request is None:
            return
        match event:
            case MessageAppendedEvent(message=message, timing=timing, usage=usage):
                node_id: str | None = None
                if message.persist:
                    node_id = await self.append(
                        context.config.session_id,
                        request.request_id,
                        message,
                        timing,
                        parent_session_id=context.state.parent_session_id,
                        metadata=context.metadata,
                        tags=context.tags,
                        usage=usage,
                    )
                if message.include_in_messages and not isinstance(message, SystemMessage):
                    request.context_ids.append(node_id)
            case CompactionEvent():
                await self._write_checkpoint(context, request, event)

    async def on_success(self, context: AgentRunContext, result: AssistantMessage) -> None:
        """Release the bookkeeping; messages were appended as they arrived."""
        self._requests.pop(context, None)

    async def on_error(self, context: AgentRunContext, error: Exception) -> None:
        """Release the bookkeeping; the append-only history remains available."""
        self._requests.pop(context, None)

    async def _restore(self, context: AgentRunContext) -> tuple[CompactionLine | None, tuple[MessageLine, ...]]:
        """Load the conversation and merge it with the current configuration."""
        session = self.read(context.config.session_id)
        stored_parent = session.parent_session_id
        configured_parent = context.state.parent_session_id
        session_exists = session.header is not None and bool(session.messages)
        if configured_parent is not None and session_exists and stored_parent != configured_parent:
            raise ValueError("Stored session belongs to a different parent session")
        context.state.parent_session_id = stored_parent or configured_parent
        checkpoint, tail = session.active()
        stored = [checkpoint.message[0]] if checkpoint is not None else []
        stored.extend(line.message[0] for line in tail)
        # Instructions come from the current configuration; stored context
        # contributes dialogue and checkpoints only.
        instructions = [message for message in context.state.messages if isinstance(message, SystemMessage)]
        context.replace_messages(
            [*instructions, *self._provider_safe_messages(stored)],
            emit_new=False,
        )
        return checkpoint, tail

    @staticmethod
    def _provider_safe_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        """Exclude interrupted tool batches from restored model context.

        A process may have stopped after persisting an assistant message with
        tool calls but before persisting every matching result; providers reject
        that sequence. Only the malformed batch is dropped, so the rest of the
        restored dialogue still reaches the model. Storage keeps everything.
        """
        restored: list[AnyMessage] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if isinstance(message, ToolMessage):
                index += 1  # an orphan result has no meaningful provider context
                continue
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                restored.append(message)
                index += 1
                continue
            tool_messages: list[ToolMessage] = []
            cursor = index + 1
            while cursor < len(messages) and isinstance(messages[cursor], ToolMessage):
                tool_messages.append(messages[cursor])
                cursor += 1
            expected = Counter(call.id for call in message.tool_calls)
            observed = Counter(result.tool_call_id for result in tool_messages)
            if expected == observed:
                restored.extend((message, *tool_messages))
            index = cursor
        return restored

    async def _write_checkpoint(
        self,
        context: AgentRunContext,
        request: _Request,
        event: CompactionEvent,
    ) -> None:
        """Store the summary and remap its context position to the compacted prefix."""
        if event.compressed_from != 1 or event.compressed_to > len(request.context_ids):
            raise ValueError("Compaction range does not match the restored context")
        compacted = [node_id for node_id in request.context_ids[: event.compressed_to] if node_id is not None]
        if not compacted:
            raise ValueError("Compaction must represent at least one stored message")
        boundary_id = compacted[-1]
        line = await self.checkpoint(
            context.config.session_id,
            CompactedMessage(content=event.summary),
            boundary_id,
            request.checkpoint_version,
        )
        request.checkpoint_version = line.version
        request.context_ids[:] = [boundary_id, *request.context_ids[event.compressed_to :]]
