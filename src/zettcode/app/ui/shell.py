"""The state the shell's parts share.

:class:`~zettcode.app.ui.app.ZettCodeApp` is assembled from mixins so the class
itself stays the wiring and the turn loop; each mixin owns one concern — the
two rows, the keys, the sessions, the notices — and every one of them reads
the same attributes. This module is that shared surface: annotations plus the
signatures a part may call on another, never behaviour, so a mixin type-checks
on its own and the runtime class stays the only implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

#: Screen name used for a page a command presented; the shell checks it to know
#: that Ctrl-C and Ctrl-D belong to the page rather than the composer.
PAGE_SCREEN = "page"

#: Screen name of a question panel. It has its own name because the questions
#: stack: the model may ask several in one response, and each has to be answered
#: before the run continues, so the shell needs to tell them from other pages.
ASK_SCREEN = "ask"

#: Rows the approval panel takes from the bottom of the screen: the question,
#: up to three lines of command, and the numbered choices.
APPROVAL_ROWS = 16

#: Rows the "a newer release is out" panel takes: the title, its two rows, and
#: the hint under them.
UPDATE_ROWS = 8

#: Steering messages one run accepts; the shell caps what a reader can queue
#: for a single request, and the count resets when a new run starts.
MAX_STEERING = 8

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    import asyncio

    from ...plugins import Activity, UiRow
    from ...tui import CompletionPopup, StatusBar, TuiApp
    from ...update import UpdateState
    from ..agent.agent import ZettCodeAgent
    from ..agent.ask import AskUserQuestion
    from ..agent.mentions import MentionRegistry
    from ..agent.projection import TranscriptProjector
    from ..agent.transcript import Transcript
    from ..agent.usage import UsageSnapshot
    from ..commands import Command
    from .widgets import Composer, SteeringQueue, TranscriptView, ZettCodeRoot


class ShellState:
    """What one part of the shell may read from the others.

    The attributes are set by :meth:`ZettCodeApp.__init__` and the methods are
    implemented by one of the mixins; a mixin inherits this class only to be
    type-checked against the surface it shares with the rest.
    """

    #: The application agent: the only channel to the conversation.
    agent: ZettCodeAgent
    #: The mounted widget tree and the host services it offers.
    app: TuiApp
    #: The conversation model every view reads.
    transcript: Transcript
    #: The scrollable transcript, and the composer with its completion menu.
    view: TranscriptView
    composer: Composer
    completions: CompletionPopup
    #: Messages queued to steer the running turn.
    steering: SteeringQueue
    #: The two rows the plugin segments fill.
    header: StatusBar
    status: StatusBar
    #: The event projector that fills the transcript, and the root widget.
    projector: TranscriptProjector
    root: ZettCodeRoot
    #: The merged slash commands and the ``@`` resource registry.
    commands: tuple[Command, ...]
    mentions: MentionRegistry
    #: The plugin rows, in paint order.
    _plugin_rows: tuple[UiRow, ...]
    #: What the status line shows: the shell's state and a one-off note.
    _activity: Activity
    _note: str | None
    #: Whether shell commands are approved for the rest of the run.
    _auto_shell: bool
    #: The active session's title, if the store has one.
    _session_title: str | None
    #: Cumulative token counters for the active session.
    _usage: UsageSnapshot
    #: Whether a turn or a command is in flight.
    _busy: bool
    #: Steering messages queued for this run, and how many were queued in all.
    _steering: list[str]
    _steering_sent: int
    #: The in-flight request that names a session, if any.
    _title_task: asyncio.Task[None] | None
    #: The in-flight release check or upgrade, if any.
    _update_task: asyncio.Task[None] | None
    #: The question the model is waiting on, while its panel is up.
    _asks: list[AskUserQuestion]
    #: The turn or command currently in flight, if any.
    _task: asyncio.Task[None] | None

    def close_page(self) -> None:
        """Close the page a command presented."""

    def submit(self, value: str) -> bool | None:
        """Start a turn, steer the running one, or run a slash command."""

    def notify(self, message: str, *, level: str = "info") -> None:
        """Show a one-line toast."""

    def _cancel_ask(self, question: AskUserQuestion) -> None:
        """Decline one question the model is waiting on, and close its panel."""

    def start_update_check(self) -> asyncio.Task[None] | None:
        """Ask the index about newer releases in the background."""

    def offer_update(self) -> UpdateState | None:
        """Show the panel a stored newer version asks for, if there is one."""

    def _refresh_tasks(self) -> None:
        """Mirror the agent's plan into the panel above the composer."""
