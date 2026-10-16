"""The conversation's entries: plain data, one class for each way a row can look.

An entry says *what happened* — a user asked, a tool ran, the model is thinking —
and nothing about how that is drawn. The drawing is ``presenters.py``, which looks
an entry up by its :class:`EntryKind`; the list of entries, and what the agent
does to it, is ``transcript.py``.

Two base classes carry what the concrete ones share. :class:`Entry` is identity
and a place for the presenter to leave its rendered rows; :class:`TimedEntry`
is an entry that takes time — the wait row, a reasoning span, a tool call — and
so has a status, a start, and a duration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...._compat import StrEnum
from ....tui import LineSource, Markdown
from .rows import THINKING_LABEL


class EntryKind(StrEnum):
    """What a row is, which is what picks the presenter that draws it.

    The value is the word the rest of the application and its tests use for the
    row, so an entry's ``kind`` still compares equal to the plain string.

    Attributes:
        WELCOME: The banner shown once at startup.
        USER: A message the reader sent, or a side question.
        NOTICE: A muted one-off status line, or an error.
        ANNOUNCEMENT: A change worth a centred line between rules.
        ANSWER: The model's reply, streamed in as it is written.
        MESSAGE: Markdown that is not a reply, such as a command's output.
        WAIT: The pinned row that says a request is running, and settles into
            the line it ended on.
        THINKING: Reasoning, or a compaction's summary, with its own clock.
        TOOL: One tool call and its bounded result.
        CHANGES: The files a request changed, said once when it ends.
        RELAY: A message that crossed between two sessions, in either direction.
    """

    WELCOME = "welcome"
    USER = "user"
    NOTICE = "notice"
    ANNOUNCEMENT = "announcement"
    ANSWER = "answer"
    MESSAGE = "message"
    WAIT = "wait"
    THINKING = "thinking"
    TOOL = "tool"
    CHANGES = "changes"
    RELAY = "relay"


class EntryStatus(StrEnum):
    """Lifecycle of a row that takes time: a wait, a reasoning span, a tool call."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class NoticeLevel(StrEnum):
    """How a notice is meant: a remark, or a failure."""

    INFO = "info"
    ERROR = "error"


@dataclass(slots=True, kw_only=True)
class Entry:
    """Identity, a kind, and the slots a presenter caches its rendered rows in.

    ``block`` and ``block_key`` belong to ``presenters.block_for``: it keeps the
    rows it last produced here, with the key they were produced under, so a row
    that has not changed is not rendered again. They live on the entry only
    because an entry's lifetime is exactly the cache's; nothing else reads them.
    """

    id: int
    kind: EntryKind
    block: LineSource | None = field(default=None, init=False, repr=False)
    block_key: tuple[object, ...] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Accept a kind as its plain word, reject one that is not a kind."""
        self.kind = EntryKind(self.kind)
        self.validate()

    def validate(self) -> None:
        """Convert and check what a subclass adds; the base has nothing to check."""


@dataclass(slots=True, kw_only=True)
class TimedEntry(Entry):
    """An entry that takes time, and so has a status, a start, and a duration.

    ``started_at`` is the clock reading the row opened on and ``duration`` how long
    it has run, which is what the row's timer shows: the transcript brings both up
    while a row is :attr:`running` and stops when it is not.
    """

    status: EntryStatus = EntryStatus.RUNNING
    started_at: float | None = None
    duration: float | None = None

    def validate(self) -> None:
        """Accept a status as its plain word, reject one that is not a status."""
        self.status = EntryStatus(self.status)

    @property
    def running(self) -> bool:
        """Return whether the row is still going, which is what its timer follows."""
        return self.status is EntryStatus.RUNNING

    def tick(self, now: float) -> None:
        """Bring the duration up to ``now``; a row that never recorded a start has none."""
        if self.started_at is not None:
            self.duration = now - self.started_at

    def finish(self, status: EntryStatus, now: float) -> None:
        """End the row with an outcome, and stamp how long it ran.

        Args:
            status: How it ended: completed, failed, or skipped.
            now: The clock reading it ended on.
        """
        self.status = status
        self.tick(now)


_TEXT_KINDS = frozenset({EntryKind.WELCOME, EntryKind.USER, EntryKind.NOTICE, EntryKind.ANNOUNCEMENT})
_MARKDOWN_KINDS = frozenset({EntryKind.ANSWER, EntryKind.MESSAGE})


@dataclass(slots=True, kw_only=True)
class TextEntry(Entry):
    """A row of plain text: the welcome banner, a user message, a notice, an announcement."""

    text: str
    level: NoticeLevel = NoticeLevel.INFO
    #: Side question: an answer that never joined the conversation.
    side: bool = False

    def validate(self) -> None:
        """Keep the kind to the plain-text ones, and the level to a known one."""
        if self.kind not in _TEXT_KINDS:
            raise ValueError(f"A {self.kind.value} row is not plain text")
        self.level = NoticeLevel(self.level)


@dataclass(slots=True, kw_only=True)
class MarkdownEntry(Entry):
    """The model's reply as it streams in, or Markdown command output.

    The parsed ``markdown`` is the row's own state: it is appended to as the reply
    arrives and serves its lines incrementally, so a token landing costs one row's
    work instead of a re-render of the answer.
    """

    text: str = ""
    markdown: Markdown = field(default_factory=Markdown)

    def validate(self) -> None:
        """Keep the kind to the Markdown ones."""
        if self.kind not in _MARKDOWN_KINDS:
            raise ValueError(f"A {self.kind.value} row is not Markdown")


@dataclass(slots=True, kw_only=True)
class WaitEntry(TimedEntry):
    """The pinned wait row: a model call is running, and how long it has taken.

    It is the last entry of the transcript for as long as the request runs, and
    the first one written when the request is over: the line it is settled with
    says what happened — ``Processed for 12s · 22:53`` — so a stopped request
    leaves a record instead of an empty place where a row used to be.
    """

    kind: EntryKind = field(default=EntryKind.WAIT, init=False)
    title: str = "Processing"
    started_at: float
    #: The clock reading of the last thing the agent said (a delta, a tool, a step), which is when the model
    #: was last heard from; ``None`` until it has said anything.
    heard_at: float | None = None
    #: Seconds the model has said nothing while nothing else was running, brought up with the timers. Zero
    #: while a tool, a reasoning row or a compaction is the thing being waited for: a ``pytest`` that takes two
    #: minutes is not the model going quiet.
    quiet: float = 0.0
    #: The tips this request may show, in the order it shows them (see :mod:`.tips`); none when they are off.
    tips: tuple[str, ...] = ()
    #: The line the request ended on, written when the row is settled.
    text: str = ""


@dataclass(slots=True, kw_only=True)
class ThinkingEntry(TimedEntry):
    """Expandable reasoning with its own clock and completion state.

    The same row carries a compaction: the summarizer is a model call whose
    progress deserves the same row and timer, so the label is part of the entry
    rather than something the presenter decides.
    """

    kind: EntryKind = field(default=EntryKind.THINKING, init=False)
    title: str = THINKING_LABEL
    text: str = ""
    expanded: bool = False


@dataclass(slots=True, kw_only=True)
class ToolEntry(TimedEntry):
    """One tool call and its bounded result: what every tool has, and nothing only some do.

    A tool whose row shows something of its own has an entry of its own that adds it
    (:class:`ReadEntry`, :class:`WriteEntry`, :class:`EditEntry`); they are all ``tool`` rows,
    folded and timed alike, and the presenter registry finds the one that draws each by its class.
    Which class a call gets is decided by the render handler that describes it
    (:class:`~.rendering.ToolRow`), so nothing here, and nothing in the transcript, names a tool.
    """

    kind: EntryKind = field(default=EntryKind.TOOL, init=False)
    call_id: str
    tool: str
    title: str
    text: str = ""
    expanded: bool = False

    @property
    def foldable(self) -> bool:
        """Return whether there is a body to expand and collapse."""
        return not self.running and bool(self.text)


@dataclass(slots=True, kw_only=True)
class ReadEntry(ToolEntry):
    """A file that was read: its body is source code, drawn as the language it is.

    ``language`` names the scanner for the output, or is ``None`` for a file that is not code.
    """

    language: str | None = None


@dataclass(slots=True, kw_only=True)
class FileChangeEntry(ToolEntry):
    """A tool that changed a file, and the change it made, as rows.

    ``path`` is the file, as the call named it. ``added`` is the number of lines the change adds, drawn
    beside the title in the colour an addition has. ``diff`` is the change itself (see :data:`~.rendering.DiffRow`), which the row shows in place
    of the tool's one-line answer once the call has succeeded: the answer says "Wrote 120 bytes", the
    diff says what was written.
    """

    path: str = ""
    added: int = 0
    diff: tuple[tuple[str, str], ...] = ()

    @property
    def shows_diff(self) -> bool:
        """Return whether the row's body is its diff: there is one, and the call succeeded.

        A call that failed did not change the file, so a diff of what it meant to do would
        describe something that did not happen; its error is the body then.
        """
        return bool(self.diff) and self.status is EntryStatus.COMPLETED

    @property
    def foldable(self) -> bool:
        """Return whether there is a body to expand: the tool's answer, or the diff."""
        return not self.running and (bool(self.text) or self.shows_diff)


@dataclass(slots=True, kw_only=True)
class WriteEntry(FileChangeEntry):
    """A file that was written whole: every line of it is an addition.

    The tool overwrites, and what it overwrote is not in the call, so there is nothing to take away
    from: the diff is the new content as additions, and there is no ``removed`` to count.
    """


@dataclass(slots=True, kw_only=True)
class EditEntry(FileChangeEntry):
    """A file that was edited in place: the lines the edits add and remove, and the change.

    ``removed`` is counted from the call's arguments when the row opens, as ``added`` is.
    """

    removed: int = 0


@dataclass(slots=True, kw_only=True)
class DeleteEntry(ToolEntry):
    """A file that was deleted; ``path`` is the file, as the call named it."""

    path: str = ""


@dataclass(slots=True, kw_only=True)
class MessageEntry(ToolEntry):
    """A message the agent sent to another session: who it was for, and every word of it.

    The tool's own answer is one line (``Delivered to work …``); what the reader wants to see is what
    was said, which the call's arguments hold and a one-line title cannot, so the entry keeps it and the
    row shows it — a few lines folded, the whole message expanded.
    """

    to: str = ""
    message: str = ""

    @property
    def foldable(self) -> bool:
        """Return whether there is more to see once the call is over: what was said, or how it ended."""
        return not self.running and bool(self.message or self.text)


@dataclass(frozen=True, slots=True)
class FileSummary:
    """What one request did to one file, in total.

    Attributes:
        path: The file, relative to the workspace when it is inside it.
        added: Lines added across every edit and write of it.
        removed: Lines removed across every edit of it.
        deleted: The file's last change was its deletion.
    """

    path: str
    added: int = 0
    removed: int = 0
    deleted: bool = False


@dataclass(slots=True, kw_only=True)
class ChangesEntry(Entry):
    """The files a request changed, listed once when it ends.

    Never made for a request that changed nothing: a row that says "no changes" would be said after
    every question.
    """

    kind: EntryKind = field(default=EntryKind.CHANGES, init=False)
    files: tuple[FileSummary, ...] = ()


@dataclass(slots=True, kw_only=True)
class RelayEntry(Entry):
    """A message between two sessions: one this session received, or one its reader sent.

    Attributes:
        peer: The other session's handle.
        text: The message.
        outgoing: This session sent it; otherwise it arrived.
        by_agent: The other session's agent wrote it (received), or this session's reader chose to
            send it with ``@`` (sent, so ``False``).
        external: It came from a program that is not a ZettCode session, whose name nobody has checked.
        note: What became of a sent message, such as ``queued``; empty for a received one.
    """

    kind: EntryKind = field(default=EntryKind.RELAY, init=False)
    peer: str
    text: str
    outgoing: bool = False
    by_agent: bool = True
    external: bool = False
    note: str = ""
