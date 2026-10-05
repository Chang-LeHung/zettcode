"""Where sessions live: the workspace layout, the JSONL writer, and the plugin.

One store root is shared by every workspace the user opens, so it is grouped by
workspace first::

    ~/.zettcode/sessions/<base64 workspace path>/
    ├── metadata.jsonl              <- the index: title and activity times
    └── <session-id>/
        └── data.jsonl              <- the conversation tree

The folder name is the URL-safe base64 of the resolved workspace path, so a
path containing separators never turns into extra folders and two checkouts of
the same project stay apart.

File operations are plain blocking reads and writes: an append is one small
line, and the caller is the single process owning the session. The last line of
a file may be truncated by a crash, so an unparsable *final* line is ignored; a
corrupt line anywhere else raises, because that means real damage.

:class:`SessionPersistenceMixin` owns all of that — the layout, parsing and the
torn-last-line policy, the tree walk, ``read``, ``append``, ``checkpoint``, the
metadata log, and ``list_sessions``. :class:`SessionStore` adds the framework
hooks on top, so saving stays a mixin concern and the agent lifecycle stays a
plugin concern.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast
from weakref import WeakKeyDictionary

from pydantic import ValidationError
from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.extensions.events import (
    CompactionEvent,
    ExtensionEvent,
    MessageAppendedEvent,
    MessageTiming,
    RunCancelledEvent,
)
from zett_agent.ids import new_uuid7
from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage
from zett_agent.model import ModelUsage

from .metadata import (
    MAX_TITLE,
    METADATA_FILE,
    SessionActivity,
    SessionInfo,
    SessionStarted,
    SessionTitle,
    append_metadata,
    read_metadata,
)
from .records import (
    LINES,
    MAX_AGENT_NAME,
    SAFE_SESSION_ID,
    STORE_FILE,
    STORE_VERSION,
    CompactionLine,
    JsonValue,
    Line,
    MessageLine,
    Session,
    SessionLine,
    now,
)

#: Longest workspace folder name; longer paths keep a hash instead of the tail.
MAX_KEY_CHARS = 120


def workspace_key(workspace: str | Path) -> str:
    """Return the folder name that groups one workspace's sessions.

    The key is the URL-safe base64 of the resolved absolute path without
    padding, so the store reads as a plain directory tree and a path containing
    separators never turns into extra folders. A path too long for one file name
    keeps a short digest instead of its tail, which still keeps two long
    checkouts apart.
    """
    encoded = base64.urlsafe_b64encode(str(Path(workspace).expanduser().resolve()).encode()).decode().rstrip("=")
    if len(encoded) <= MAX_KEY_CHARS:
        return encoded
    digest = hashlib.sha256(encoded.encode()).hexdigest()[:12]
    return f"{encoded[: MAX_KEY_CHARS - 13]}-{digest}"


def message_context(
    value: Mapping[str, object] | None, *, field: str, nonempty_keys: bool = False
) -> dict[str, JsonValue]:
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
    # Pydantic validates the value when the line is built; this only tells the
    # checker what the runtime already guarantees.
    return cast("dict[str, JsonValue]", encoded)


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
    """Standalone mixin: read and write the conversation log and its metadata.

    It inherits nothing, so it can be combined with the framework's
    ``AgentExtension`` (see :class:`SessionStore`). It owns the storage: the
    workspace layout, parsing and the torn-last-line policy, the tree walk,
    ``read``, ``append``, ``checkpoint``, the metadata log with
    ``set_title``/``session_title``, and ``list_sessions``. It holds no
    framework behavior.

    Args:
        root: Directory holding one folder per workspace, and inside it one
            ``<session_id>/`` folder per session with its own ``data.jsonl``.
            ``None`` uses ``~/.zettcode/sessions``.
        workspace: Project the sessions belong to; its resolved absolute path,
            base64-encoded, names the workspace folder. ``None`` uses the
            current directory, which is only right for standalone use — the
            runtime always passes the configured workspace.

    Parent directories are created eagerly.
    """

    def __init__(self, root: str | Path | None = None, workspace: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".zettcode" / "sessions"
        self.workspace = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
        self.workspace_dir = self.root / workspace_key(self.workspace)
        self.metadata_path = self.workspace_dir / METADATA_FILE
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        super().__init__()

    def _record_activity(self, session_id: str, updated_at: datetime) -> None:
        """Stamp one session's activity, which is what a session list sorts on."""
        append_metadata(self.metadata_path, SessionActivity(session_id=session_id, updated_at=updated_at))

    # -- files --------------------------------------------------------------
    def session_dir(self, session_id: str) -> Path:
        """Return the directory of one session, refusing ids that leave the store."""
        if not SAFE_SESSION_ID.match(session_id) or ".." in session_id:
            raise ValueError(f"Unsafe session id: {session_id!r}")
        return self.workspace_dir / session_id

    def session_path(self, session_id: str) -> Path:
        """Return the conversation file of one session."""
        return self.session_dir(session_id) / STORE_FILE

    def session_ids(self) -> Iterator[str]:
        """Yield the id of every session folder this workspace owns."""
        for path in sorted(self.workspace_dir.glob(f"*/{STORE_FILE}")):
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
        lines: list[MessageLine | CompactionLine] = [*messages, *compactions]
        known = {line.id for line in lines}
        for line in messages:
            if line.parent is not None and line.parent not in known:
                raise ValueError(f"Unknown parent {line.parent!r} in {path.name}")
        for boundary in compactions:
            if boundary.parent not in known:
                raise ValueError(f"Unknown boundary {boundary.parent!r} in {path.name}")

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
        if agent_name is not None and (not agent_name.strip() or len(agent_name) > MAX_AGENT_NAME):
            raise ValueError(f"Agent name must contain between 1 and {MAX_AGENT_NAME} characters")
        if usage is not None and not isinstance(message, AssistantMessage):
            raise ValueError("Model usage belongs only to assistant messages")
        session = self.read(session_id)
        created_at = self._write_header(session, session_id, parent_session_id, agent_name)
        if created_at is not None:
            append_metadata(self.metadata_path, SessionStarted(session_id=session_id, created_at=created_at))
        if parent is None:
            parent = session.head_id
        elif session.message(parent) is None:
            raise ValueError(f"Unknown parent message: {parent!r}")
        node_id = new_uuid7()
        stamp = now()
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
                metadata=message_context(metadata, field="Message metadata"),
                tags=message_context(tags, field="Message tags", nonempty_keys=True),
                created_at=stamp,
            ),
        )
        self._record_activity(session_id, stamp)
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
            position = session.index(boundary_id)
            if previous is not None and position is not None and position <= previous:
                raise ValueError("Checkpoint boundary must advance beyond the previous one")
        line = CompactionLine(
            id=new_uuid7(),
            parent=boundary_id,
            version=version + 1,
            message=(summary,),
            created_at=now(),
        )
        self._append_line(session_id, line)
        self._record_activity(session_id, line.created_at)
        return line

    async def set_title(self, session_id: str, title: str) -> None:
        """Write one session's display title, replacing any earlier one.

        The title is metadata, not conversation, so renaming is one more line in
        the metadata log and never shows up in the message history. Naming a
        session that has not been used yet creates it: the header that marks a
        session is written first, so a name the user typed is never dropped for
        want of a conversation.
        """
        cleaned = title.strip()
        if not cleaned or len(cleaned) > MAX_TITLE:
            raise ValueError(f"Session title must contain between 1 and {MAX_TITLE} characters")
        if not any(info.session_id == session_id for info in read_metadata(self.metadata_path)):
            created_at = self._write_header(self.read(session_id), session_id, None, None)
            if created_at is not None:
                append_metadata(self.metadata_path, SessionStarted(session_id=session_id, created_at=created_at))
        append_metadata(self.metadata_path, SessionTitle(session_id=session_id, title=cleaned))

    def session_title(self, session_id: str) -> str | None:
        """Return one session's stored title, or ``None`` when it is unnamed."""
        return next(
            (info.title for info in read_metadata(self.metadata_path) if info.session_id == session_id),
            None,
        )

    async def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionInfo]:
        """Return session metadata by latest activity, newest first.

        The listing reads the metadata log alone: no conversation file is
        opened, and rows whose folder was deleted by hand are skipped rather
        than shown.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        sessions = [info for info in read_metadata(self.metadata_path) if self.session_path(info.session_id).is_file()]
        return sessions[offset : offset + limit]

    async def close(self) -> None:
        """Release nothing; every write opens and closes its own handle."""

    def _write_header(
        self,
        session: Session,
        session_id: str,
        request_parent: str | None,
        agent_name: str | None,
    ) -> datetime | None:
        """Create the session line, rejecting a parent that changed after creation.

        Returns:
            The new session's creation time, or ``None`` when the file already
            had a header — which is also what tells the caller whether to start
            the session's metadata row.
        """
        if session.header is not None:
            if session.header.parent_session_id != request_parent:
                raise ValueError("Session parent cannot change after creation")
            return None
        created_at = now()
        self._append_line(
            session_id,
            SessionLine(
                version=STORE_VERSION,
                session_id=session_id,
                parent_session_id=request_parent,
                agent_name=agent_name,
                created_at=created_at,
            ),
        )
        return created_at


class SessionStore(SessionPersistenceMixin, AgentExtension):
    """The agent plugin: restore and save a conversation through the mixin.

    ``SessionPersistenceMixin`` owns the files. This class adds the framework
    hooks — restore the model context on ``on_state``, append messages and write
    checkpoints from the event stream, and drop per-request bookkeeping on
    success, error, or cancellation.

    Args:
        root: Store root, grouped by workspace; forwarded to the mixin.
            ``None`` uses ``~/.zettcode/sessions``.
        workspace: Project whose sessions this store owns; forwarded to the
            mixin. ``None`` uses the current directory.
    """

    def __init__(self, root: str | Path | None = None, workspace: str | Path | None = None) -> None:
        self._requests: WeakKeyDictionary[AgentRunContext, _Request] = WeakKeyDictionary()
        super().__init__(root, workspace)

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
                        cast(str, context.config.session_id),
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
        session = self.read(cast(str, context.config.session_id))
        stored_parent = session.parent_session_id
        configured_parent = context.state.parent_session_id
        session_exists = session.header is not None and bool(session.messages)
        if configured_parent is not None and session_exists and stored_parent != configured_parent:
            raise ValueError("Stored session belongs to a different parent session")
        context.state.parent_session_id = stored_parent or configured_parent
        checkpoint, tail = session.active()
        stored: list[AnyMessage] = [checkpoint.message[0]] if checkpoint is not None else []
        # Instructions come from the current configuration; stored context
        # contributes dialogue and checkpoints only, which is what the runtime's
        # own ``include_in_messages`` flag means. Re-adding a persisted
        # instruction (the system prompt, the filesystem note, the tool snippets)
        # would duplicate it at the head of every request, bloating the prompt
        # and breaking the provider's prefix cache from that point on.
        stored.extend(line.message[0] for line in tail if line.message[0].include_in_messages)
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
            while cursor < len(messages) and isinstance(current := messages[cursor], ToolMessage):
                tool_messages.append(current)
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
            cast(str, context.config.session_id),
            CompactedMessage(content=event.summary),
            boundary_id,
            request.checkpoint_version,
        )
        request.checkpoint_version = line.version
        request.context_ids[:] = [boundary_id, *request.context_ids[event.compressed_to :]]
