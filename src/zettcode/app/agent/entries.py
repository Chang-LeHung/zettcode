"""Typed transcript entries and their width-dependent render caches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias, cast

from ..._compat import StrEnum
from ...tui import LineSource, Markdown, StaticLines, Theme
from ...tui.widgets.markdown import MarkdownSource
from .rows import THINKING_LABEL

if TYPE_CHECKING:
    from .blocks import EntryProcessors


class EntryStatus(StrEnum):
    """Lifecycle of a reasoning or tool row."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True, kw_only=True)
class BaseEntry:
    """Identity and render cache shared by all transcript entries."""

    id: int
    kind: str
    block: LineSource | None = field(default=None, init=False, repr=False)
    block_key: tuple[object, ...] | None = field(default=None, init=False, repr=False)

    def block_for(
        self, width: int, theme: Theme, frame: int, *, processors: EntryProcessors | None = None
    ) -> LineSource:
        """Return cached presentation lines, rebuilding only when state changes."""
        from .blocks import DEFAULT_PROCESSORS, render_entry
        from .transcript import CONTENT_INDENT, Indented

        chosen = DEFAULT_PROCESSORS if processors is None else processors
        key: tuple[object, ...] = (width, theme, chosen, self.kind, self.render_state(frame))
        if self.block is None or self.block_key != key:
            margin = min(CONTENT_INDENT, max(0, width - 1))
            content_width = width if isinstance(self, TextEntry) and self.kind == "user" else max(1, width - margin)
            # Only the union members below are ever instantiated; the base class
            # exists to share this cache, so the cast is exact at runtime.
            rendered = StaticLines(render_entry(cast(Entry, self), content_width, theme, frame, processors=chosen))
            self.block = rendered if isinstance(self, TextEntry) and self.kind == "user" else Indented(rendered)
            self.block_key = key
        return self.block

    def render_state(self, frame: int) -> object:
        """Return state that changes how this entry looks when painted."""
        return ()


@dataclass(slots=True, kw_only=True)
class TextEntry(BaseEntry):
    """Welcome banner, user message, or muted notice."""

    kind: Literal["welcome", "notice", "user", "announcement"]
    text: str
    level: Literal["info", "error"] = "info"

    def render_state(self, frame: int) -> object:
        """Include the text so replacing it cannot reuse stale rendered lines."""
        return (self.text, self.level)


@dataclass(slots=True, kw_only=True)
class MarkdownEntry(BaseEntry):
    """Streaming assistant answer or Markdown command output."""

    kind: Literal["answer", "message"]
    text: str = ""
    markdown: Markdown = field(default_factory=Markdown)

    def block_for(
        self, width: int, theme: Theme, frame: int, *, processors: EntryProcessors | None = None
    ) -> LineSource:
        """Keep streamed Markdown virtualized instead of re-rendering it per frame."""
        from .transcript import Indented, LeadingGap

        self.markdown.theme = theme
        if self.block is None:
            self.block = Indented(LeadingGap(MarkdownSource(self.markdown)))
        return self.block


@dataclass(slots=True, kw_only=True)
class ProcessingEntry(BaseEntry):
    """Placeholder shown while waiting for a model response."""

    # mypy cannot model a dataclass field re-declared as a fixed class
    # value; the runtime drops it from __init__, which the test pins.
    kind: ClassVar[Literal["pending"]] = "pending"  # type: ignore[misc]
    title: str = "Processing"
    status: EntryStatus = EntryStatus.RUNNING
    started_at: float
    duration: float | None = None

    def __post_init__(self) -> None:
        """Keep externally constructed entries on the same status enum as the transcript."""
        self.status = EntryStatus(self.status)

    def render_state(self, frame: int) -> object:
        """The waiting row advances its sweep and timer while running."""
        return (self.title, frame, self.duration)


@dataclass(slots=True, kw_only=True)
class ThinkingEntry(BaseEntry):
    """Expandable reasoning with its own clock and completion state.

    The same row carries a compaction: the summarizer is a model call whose
    progress deserves the same animation, so the label is part of the entry
    rather than something the renderer decides.
    """

    kind: ClassVar[Literal["thinking"]] = "thinking"  # type: ignore[misc]
    title: str = THINKING_LABEL
    text: str = ""
    expanded: bool = False
    status: EntryStatus = EntryStatus.RUNNING
    started_at: float | None = None
    duration: float | None = None

    def __post_init__(self) -> None:
        """Reject unknown reasoning states before a row reaches the renderer."""
        self.status = EntryStatus(self.status)

    def render_state(self, frame: int) -> object:
        """Expansion, reasoning text, and running animation affect presentation."""
        return (
            self.title,
            self.expanded,
            self.text,
            self.status,
            self.duration,
            frame if self.status is EntryStatus.RUNNING else 0,
        )


@dataclass(slots=True, kw_only=True)
class ToolEntry(BaseEntry):
    """Expandable tool invocation and bounded result."""

    kind: ClassVar[Literal["tool"]] = "tool"  # type: ignore[misc]
    call_id: str
    tool: str
    title: str
    language: str | None = None
    text: str = ""
    expanded: bool = False
    status: EntryStatus = EntryStatus.RUNNING
    started_at: float | None = None
    duration: float | None = None

    def __post_init__(self) -> None:
        """Reject unknown tool states before a row reaches the renderer."""
        self.status = EntryStatus(self.status)

    def render_state(self, frame: int) -> object:
        """A tool body, expansion, and running label each affect its rendered rows."""
        return (
            self.title,
            self.expanded,
            self.text,
            self.status,
            self.duration,
            self.language,
            frame if self.status is EntryStatus.RUNNING else 0,
        )


@dataclass(slots=True, kw_only=True)
class PlainEntry(BaseEntry):
    """Fallback for entry kinds introduced outside the built-in UI."""

    text: str

    def render_state(self, frame: int) -> object:
        """A fallback row changes only when its text changes."""
        return self.text


Entry: TypeAlias = TextEntry | MarkdownEntry | ProcessingEntry | ThinkingEntry | ToolEntry | PlainEntry
