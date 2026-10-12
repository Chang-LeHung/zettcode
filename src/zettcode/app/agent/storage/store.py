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

import asyncio
import base64
import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
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

from ..dialogue.side import SIDE, is_side
from .metadata import (
    MAX_TITLE,
    METADATA_FILE,
    SESSION_METADATA_FILE,
    SessionInfo,
    SessionMetadata,
    info_of,
    read_metadata,
    read_session_metadata,
    write_session_metadata,
)
from .records import (
    FORK_SUFFIX,
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
    #: Whether this request is a side question (see ``app.agent.side``): its
    #: messages are written for the record but never replayed into a context.
    side: bool = False
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
        #: The log older versions kept for the whole workspace. Read, never written: see
        #: :mod:`zettcode.app.agent.storage.metadata`.
        self.legacy_metadata_path = self.workspace_dir / METADATA_FILE
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        # Parsed sessions, keyed by the file stamp that produced them. Appending
        # is the hot path — one call per message — so it must not re-parse the
        # whole log; the cache makes a read O(1) and a write a tuple copy.
        self._sessions: dict[str, tuple[tuple[int, int] | None, Session]] = {}
        #: The old log folded into rows, with the stamp of the file it came from, so a
        #: workspace with several old sessions folds it once instead of once per session.
        self._legacy: tuple[tuple[int, int] | None, dict[str, SessionInfo]] | None = None
        super().__init__()

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

    def exists(self, session_id: str) -> bool:
        """Say whether a session was started, by reading the one line that says so.

        A session file opens with its header, so that line answers the question.
        :meth:`read` is the call that checks the whole file, and it is the wrong one
        to ask a yes-or-no question with: on a long session it parses every message
        to report what the first line already says, and a command line that did so
        before resuming paid for the parse twice — once to be told the session was
        there, and again, in a store that had not kept the first, to open it.

        Args:
            session_id: The session to look for.

        Returns:
            ``True`` when the file exists and its first record is a session header.
        """
        return self._header(session_id) is not None

    def _header(self, session_id: str) -> SessionLine | None:
        """Return a session's header, read from the first line of its file and nothing more."""
        try:
            with self.session_path(session_id).open("rb") as handle:
                for line in handle:
                    if line.strip():
                        record = LINES.validate_json(line)
                        return record if isinstance(record, SessionLine) else None
        except (OSError, ValidationError):
            return None
        return None

    def read(self, session_id: str) -> Session:
        """Parse one session file, tolerating a half-written final line."""
        path = self.session_path(session_id)
        if not path.is_file():
            session = Session(header=None, messages=(), compactions=(), head_id=None)
            self._sessions[session_id] = (None, session)
            return session
        stamp = self._stamp(path)
        cached = self._sessions.get(session_id)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        # Bytes, not text: the parser takes them as they are, so the file is not
        # decoded to a string only to be encoded again, and a line is only ever split
        # where the file's own newline is. ``str.splitlines`` also breaks at U+2028,
        # U+2029, and U+0085, which JSON writes into a string as they are — a
        # message that held one was cut in half and the file called corrupt.
        lines = path.read_bytes().splitlines()
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
        session = Session(header=header, messages=tuple(messages), compactions=tuple(compactions), head_id=head_id)
        self._sessions[session_id] = (stamp, session)
        return session

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        """Return the file's identity as mtime and size, the cache's validity key."""
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)

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
        path = self.session_path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
            handle.flush()
        self._remember(session_id, line)

    def _remember(self, session_id: str, line: Line) -> None:
        """Fold a line this process just wrote into the cache, without re-reading.

        A session that was never read has no entry to update, and the next read
        parses the file once; when there is one, the new line is spliced into the
        parsed model and the stamp refreshed, so the append that just happened
        never pays for the parse the cache exists to avoid.
        """
        cached = self._sessions.get(session_id)
        if cached is None:
            return
        _, session = cached
        match line:
            case SessionLine():
                session = replace(session, header=line)
            case MessageLine():
                session = replace(session, messages=(*session.messages, line), head_id=line.id)
            case CompactionLine():
                session = replace(session, compactions=(*session.compactions, line))
        self._sessions[session_id] = (self._stamp(self.session_path(session_id)), session)

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
            self._begin_metadata(session_id, created_at)
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
        # Nothing is written about the session itself: the conversation file's own
        # modification time moved with the line above, and that is the activity a list shows.
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
        return line

    async def set_title(self, session_id: str, title: str) -> None:
        """Write one session's display title, replacing any earlier one.

        The title is metadata, not conversation, so renaming rewrites the session's small
        metadata file and never shows up in the message history. Naming a session that has
        not been used yet creates it: the header that marks a session is written first, so a
        name the user typed is never dropped for want of a conversation.
        """
        cleaned = title.strip()
        if not cleaned or len(cleaned) > MAX_TITLE:
            raise ValueError(f"Session title must contain between 1 and {MAX_TITLE} characters")
        metadata = self._metadata(session_id)
        if metadata is None:
            created_at = self._write_header(self.read(session_id), session_id, None, None)
            metadata = (
                self._begin_metadata(session_id, created_at) if created_at is not None else self._metadata(session_id)
            )
        if metadata is not None:
            write_session_metadata(self._metadata_file(session_id), metadata.model_copy(update={"title": cleaned}))

    def fork(self, session_id: str) -> str:
        """Copy the context one session carries into a new session, and return its id.

        What is copied is the context, not the file: the newest checkpoint's summary
        and the messages after it — the part a request would carry. A session that has
        been compacted therefore forks into the part of it that still matters, and the
        messages the summary replaced stay behind with the session they belong to. That
        is what makes a fork worth having rather than a copy of the file: a long
        conversation continues from what the model is actually working with.

        The new session records where it came from and takes the source's title with
        ``(fork)`` after it, so a picker shows the two apart. A session holding nothing
        is refused rather than forked empty.

        This is file work, like :meth:`read`, and not part of the persistence
        extension's async contract: the shell runs it on a thread, so copying a long
        conversation does not hold the event loop.

        Args:
            session_id: The session whose context is copied.

        Raises:
            ValueError: There is nothing to copy — the session holds no messages, or
                never reached the store at all, which for a fork of the session the
                reader is already in are the same answer to the same question.
        """
        source = self.read(session_id)
        checkpoint, tail = source.active() if source.header is not None else (None, ())
        if checkpoint is None and not tail:
            raise ValueError("Nothing to fork yet: this session has no messages")
        new_id = new_uuid7()
        created_at = self._write_header(self.read(new_id), new_id, session_id, None)
        if created_at is not None:
            title = self.session_title(session_id)
            carried = (
                f"{title}{FORK_SUFFIX}" if title is not None and len(f"{title}{FORK_SUFFIX}") <= MAX_TITLE else None
            )
            self._begin_metadata(new_id, created_at, title=carried)
        parent: str | None = None
        if checkpoint is not None:
            # The summary is copied as a message of its own. As a checkpoint it would
            # need a boundary message to sit on, and the boundary it was taken at
            # belongs to the conversation being left behind; as a message it reaches
            # the next request exactly as the checkpoint body did.
            parent = self._copy_message(new_id, None, cast("AnyMessage", checkpoint.message[0]), request_id="fork")
        for line in tail:
            parent = self._copy_message(
                new_id,
                parent,
                line.message[0],
                request_id=line.request_id,
                timing=line.timing,
                usage=line.usage,
                metadata=line.metadata,
                tags=line.tags,
                created_at=line.created_at,
            )
        return new_id

    def _copy_message(
        self,
        session_id: str,
        parent: str | None,
        message: AnyMessage,
        *,
        request_id: str,
        timing: MessageTiming | None = None,
        usage: ModelUsage | None = None,
        metadata: Mapping[str, object] | None = None,
        tags: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> str:
        """Append one message copied from another session, and return its id.

        Everything the line carried travels with it — its request, its timings, the
        usage its reply reported, and the tags that mark a side question — so a forked
        conversation reads, and counts, the way the one it came from did.
        """
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
                metadata=dict(metadata or {}),
                tags=dict(tags or {}),
                created_at=created_at or now(),
            ),
        )
        return node_id

    def session_title(self, session_id: str) -> str | None:
        """Return one session's stored title, or ``None`` when it is unnamed."""
        metadata = self._metadata(session_id)
        return metadata.title if metadata is not None else None

    async def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionInfo]:
        """Return session metadata by latest activity, newest first.

        Each row is read from the session's own metadata file, so no conversation is parsed
        and the cost is one small file per session. A session with no file of its own is one
        an older version made: its row is carried over from the old log, written into its
        folder, and read from there from then on. A folder deleted by hand has no row.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        # On a thread: the cost is a file per session, which is a few milliseconds for the
        # hundred a person has and a fifth of a second for five thousand, and this is awaited
        # from the interface. The first listing after an upgrade also writes a file per old
        # session, once.
        return await asyncio.to_thread(self._listing, limit, offset)

    def _listing(self, limit: int, offset: int) -> list[SessionInfo]:
        """Read every session's row and return one page of them, newest activity first."""
        rows: list[SessionInfo] = []
        for session_id in self.session_ids():
            metadata = self._metadata(session_id)
            if metadata is not None:
                rows.append(info_of(metadata, self.session_path(session_id)))
        rows.sort(key=lambda info: (info.updated_at, info.session_id), reverse=True)
        return rows[offset : offset + limit]

    # -- metadata -------------------------------------------------------------
    def _metadata_file(self, session_id: str) -> Path:
        """Return the file that holds one session's own metadata."""
        return self.session_dir(session_id) / SESSION_METADATA_FILE

    def _begin_metadata(self, session_id: str, created_at: datetime, *, title: str | None = None) -> SessionMetadata:
        """Write the metadata of a session that has just been created, and return it."""
        metadata = SessionMetadata(session_id=session_id, created_at=created_at, updated_at=created_at, title=title)
        write_session_metadata(self._metadata_file(session_id), metadata)
        return metadata

    def _metadata(self, session_id: str) -> SessionMetadata | None:
        """Return one session's metadata, from its own file when it has one.

        The common case is one small read. A session with a conversation but no file — one an
        older version made, or one whose file was lost — is carried over: the old log is asked
        what it knew, the answer is written into the session's folder, and the next look reads
        it from there. A session with no conversation has nothing to describe.

        Returns:
            The metadata, or ``None`` when the session has no conversation.
        """
        found = read_session_metadata(self._metadata_file(session_id), session_id)
        if found is not None:
            return found
        header = self._header(session_id)
        if header is None:
            return None
        old = self._legacy_rows().get(session_id)
        metadata = SessionMetadata(
            session_id=session_id,
            created_at=old.created_at if old is not None else header.created_at,
            updated_at=old.updated_at if old is not None else header.created_at,
            title=old.title if old is not None else None,
        )
        write_session_metadata(self._metadata_file(session_id), metadata)
        return metadata

    def _legacy_rows(self) -> dict[str, SessionInfo]:
        """Return what the old workspace log says about each session, folded once per change.

        Raises:
            ValueError: The old log has a damaged line other than its last. That is reported
                rather than skipped: a session carried over from a log that could not be read
                would lose its title for good.
        """
        path = self.legacy_metadata_path
        try:
            stat = path.stat()
        except OSError:
            self._legacy = (None, {})
            return {}
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._legacy is None or self._legacy[0] != stamp:
            self._legacy = (stamp, {info.session_id: info for info in read_metadata(path)})
        return self._legacy[1]

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

        A later append that names no parent leaves the one already written alone: the
        header's parent is set when the session is created — by a delegation, or by a
        fork, which records the conversation it was taken from — and the runtime hands
        it back on every append of that run. Naming a *different* parent is the mistake
        this rejects.

        Returns:
            The new session's creation time, or ``None`` when the file already
            had a header — which is also what tells the caller whether to start
            the session's metadata row.
        """
        if session.header is not None:
            if request_parent is not None and session.header.parent_session_id != request_parent:
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
                if is_side(message):
                    request.side = True
                if request.side:
                    # A side question is recorded, never replayed: the same flag
                    # the runtime uses for a message that must not re-enter a
                    # context. The live transcript is untouched — this is the
                    # store's own copy of the message.
                    message = replace(message, include_in_messages=False)
                node_id: str | None = None
                if message.persist:
                    node_id = await self.append(
                        cast(str, context.config.session_id),
                        request.request_id,
                        message,
                        timing,
                        parent_session_id=context.state.parent_session_id,
                        metadata=context.metadata,
                        # A side question's lines are tagged as well as flagged:
                        # the tag is what a replay or an export reads, since the
                        # flag alone would also match an instruction.
                        tags={**context.tags, SIDE: True} if request.side else context.tags,
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
