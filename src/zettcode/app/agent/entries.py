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

from ..._compat import StrEnum
from ...tui import LineSource, Markdown
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
    """Expandable tool invocation and bounded result.

    ``added`` and ``removed`` are the lines an edit changes, counted from the call's
    arguments when the row opens; they ride beside the title because the presenter
    paints them in colours of their own.
    """

    kind: EntryKind = field(default=EntryKind.TOOL, init=False)
    call_id: str
    tool: str
    title: str
    language: str | None = None
    added: int = 0
    removed: int = 0
    text: str = ""
    expanded: bool = False
