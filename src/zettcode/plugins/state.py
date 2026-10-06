"""The shell snapshot and segment types a plugin draws against.

A segment builder is called once per paint with a :class:`ShellContext`: a
snapshot of everything the shell's own rows read, grouped by what it describes
(``session``, ``model``, ``activity``, ``display``) with the resolved ``config``
beside them. The same module carries the segment types a plugin registers, so a
builder and what it registers are described in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

from .._compat import StrEnum

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from pathlib import Path

    from ..app.agent.usage import UsageSnapshot
    from ..config import ModelConfig, ZettCodeConfig
    from ..tui import TextLine, Theme


#: Which row a plugin draws into: the header above the transcript, or the
#: status line under the composer.
UiRegion: TypeAlias = Literal["header", "status"]

#: Which side of a row a segment gathers on. A plugin never chooses it: the
#: registration method it calls, or the builtin segment it replaces, does.
UiSide: TypeAlias = Literal["left", "right"]

#: What one segment paints: a styled line, a plain string, or nothing. The
#: alias quotes its members because :class:`TextLine` is imported only for the
#: checker; an alias evaluates eagerly, so the names must stay strings.
UiSegmentValue: TypeAlias = "TextLine | str | None"

#: What a builder returns: a value, or ``(value, override)`` when the segment
#: wants its side to itself. With ``override`` the segments registered before it
#: are dropped for that paint, so the side shows this segment (and anything
#: registered after it) instead of what the builtins put there.
UiBuilderResult: TypeAlias = "UiSegmentValue | tuple[UiSegmentValue, bool]"

#: One plugin-drawn segment: the callable that paints it.
UiBuilder: TypeAlias = Callable[["ShellContext"], UiBuilderResult]


@dataclass(frozen=True, slots=True)
class SessionState:
    """Which conversation the shell is showing.

    Attributes:
        id: Active session identity.
        title: Stored session title, or ``None`` before the first reply.
        name: Title to show, falling back to ``"New session"``.
        workspace: Workspace directory the agent runs in.
    """

    id: str
    title: str | None
    name: str
    workspace: Path


@dataclass(frozen=True, slots=True)
class ModelState:
    """What the next request will ask for.

    Attributes:
        config: The active model, with its id, display name, context window, and
            multimodal flag.
        name: Display name, the short form of ``config.shown_name``.
        effort: Reasoning effort as its string value.
        efforts: Every reasoning level the runtime accepts, cheapest first.
    """

    config: ModelConfig
    name: str
    effort: str
    efforts: tuple[str, ...]


class Activity(StrEnum):
    """What the shell is doing between requests, as the status line words it."""

    READY = "ready"
    RUNNING = "running"


@dataclass(frozen=True, slots=True)
class ActivityState:
    """What the agent is doing right now, and what it has spent.

    Attributes:
        busy: Whether a turn or a command is in flight.
        status: The shell's own state next to the activity glyph.
        note: One-off text that takes the status word's place, such as the
            running command's name or ``"copied 12 characters"``; ``None``
            shows the status word itself.
        auto_shell: Whether shell commands are approved for the rest of the run.
        usage: Cumulative token counters for the active session.
        tasks: The session's plan as ``(status, content)`` pairs, empty when the
            model has not published one.
        frame: Animation frame counter; it advances only while something is
            busy, which is what a plugin animates against.
    """

    busy: bool
    status: Activity
    note: str | None
    auto_shell: bool
    usage: UsageSnapshot
    tasks: tuple[tuple[str, str], ...]
    frame: int

    @property
    def label(self) -> str:
        """Return the word the status line shows: the note, else the state."""
        return self.note or self.status


@dataclass(frozen=True, slots=True)
class DisplayState:
    """The terminal and the palette a shell row is drawn into.

    Attributes:
        theme: Active palette, so a plugin styles with the same colours as the
            rest of the shell instead of hardcoding its own.
        width: Current terminal width in columns.
        height: Current terminal height in rows.
        screen: Name of the topmost screen (``"main"``, ``"page"``, ``"toast"``),
            so a plugin can tell an overlay from the composer.
        scrolled_up: Whether the transcript is showing history rather than the
            newest line, which is what the "back to bottom" badge tracks.
    """

    theme: Theme
    width: int
    height: int
    screen: str
    scrolled_up: bool


@dataclass(frozen=True, slots=True)
class ShellContext:
    """What a plugin reads when it draws one header or status row.

    The state is rebuilt for every paint, so a builder always sees the current
    session, model, counters, and terminal size; it is a snapshot, not a
    subscription. It is deliberately everything the shell's own rows read —
    a plugin should not have to guess at the shell's state to draw beside it —
    grouped so a builder names the part it wants instead of one long field list.

    Attributes:
        config: Resolved settings the runtime was built from.
        session: The conversation on screen.
        model: What the next request will ask for.
        activity: What the agent is doing and what it has spent.
        display: The terminal, palette, and scroll position it draws into.
    """

    config: ZettCodeConfig
    session: SessionState
    model: ModelState
    activity: ActivityState
    display: DisplayState


@dataclass(frozen=True, slots=True)
class UiSegment:
    """One named piece of a shell row.

    Attributes:
        name: Identity within its row. Registering a segment under a name that
            already exists replaces that one in place, which is how a plugin
            takes a slot over from the builtin rows.
        builder: Called once per paint with the current :class:`ShellContext`.
    """

    name: str
    builder: UiBuilder


@dataclass(frozen=True, slots=True)
class UiRow:
    """One shell row: its two sides, each painted left to right.

    The sides are the shell's frame, not a plugin's choice; ``left`` is drawn at
    the left edge and ``right`` flush to the right, with ``StatusBar`` settling
    which one wins when the terminal is narrow.
    """

    region: UiRegion
    left: tuple[UiSegment, ...] = ()
    right: tuple[UiSegment, ...] = ()
