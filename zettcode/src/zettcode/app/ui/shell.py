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

#: The animation token the effort gauge registers: one token, held for its second
#: and released when the gauge is over, so the frame loop goes back to sleep.
EFFORT_TOKEN = "effort"

#: How long a flash stays in the row above the composer: long enough to read a
#: count of characters, short enough that the next thing typed is not typed into
#: something the reader is still reading.
FLASH_SECONDS = 1.5

#: What the conversation says when a request ends having produced nothing: the model was asked and sent back an
#: empty reply, which the stream reports as a request that completed.
EMPTY_REPLY = "The model sent back an empty reply. Try again, or check the model and address with /config."

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

#: Follow-up messages that may wait at once. They are held by the shell and each takes a row
#: above the composer, so the list is bounded the way the steering one is.
MAX_FOLLOW_UPS = 8

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    import asyncio
    from collections.abc import Sequence

    from zettcode.app.plugins.state import Activity, UiRow
    from zettcode.config import ModelConfig
    from zettcode.engine.agent.prompt import PromptPart
    from zettcode.engine.dialogue.mentions import MentionRegistry
    from zettcode.engine.messenger import Messenger
    from zettcode.engine.relay import Relayed
    from zettcode.sdk.client import Client
    from zettcode.sdk.events import QuestionAsked
    from zettcode.sdk.types import Usage
    from zettcode.tui import CompletionPopup, StatusBar, Theme, TuiApp
    from zettcode.update import UpdateState

    from ..agent.agent import TerminalAgent
    from ..agent.conversation.effort_gauge import EffortFrame
    from ..agent.conversation.projection import TranscriptProjector
    from ..agent.conversation.shimmer import ShimmerFrame
    from ..agent.conversation.transcript import Transcript
    from ..commands import Command
    from ..pets import Pet
    from .followups import FollowUp
    from .gc_policy import CollectorPolicy
    from .widgets import Composer, FollowUpQueue, PetView, SteeringQueue, TranscriptView, ZettCodeRoot


class ShellState:
    """What one part of the shell may read from the others.

    The attributes are set by :meth:`ZettCodeApp.__init__` and the methods are
    implemented by one of the mixins; a mixin inherits this class only to be
    type-checked against the surface it shares with the rest.
    """

    #: The application agent: the only channel to the conversation.
    agent: TerminalAgent
    #: The SDK client over that agent: what the shell asks of the agent goes through it as it moves off the agent.
    client: Client
    #: The mounted widget tree and the host services it offers.
    app: TuiApp
    #: The conversation model every view reads.
    transcript: Transcript
    #: The scrollable transcript, and the composer with its completion menu.
    view: TranscriptView
    composer: Composer
    completions: CompletionPopup
    #: Messages queued to steer the running turn, and the ones held to follow it.
    steering: SteeringQueue
    follow_ups: FollowUpQueue
    #: The two rows the plugin segments fill.
    header: StatusBar
    status: StatusBar
    #: The event projector that fills the transcript, and the root widget.
    projector: TranscriptProjector
    root: ZettCodeRoot
    #: The line to the other sessions, or ``None`` when sessions are switched off.
    messenger: Messenger | None
    #: The merged slash commands and the ``@`` resource registry.
    commands: tuple[Command, ...]
    mentions: MentionRegistry
    #: The palette in force before the ``/theme`` menu started showing others, or ``None`` when nothing is previewed.
    _theme_before: Theme | None
    #: The pet in front of the one the ``/pet`` menu is previewing, or ``None`` when nothing is previewed.
    _pet_before: Pet | None
    #: The pet over the conversation.
    pet: PetView
    #: The command whose menu is showing its words as it is walked (see ``Command.preview``).
    _previewing: Command | None
    #: The plugin rows, in paint order.
    _plugin_rows: tuple[UiRow, ...]
    #: What the status line shows: the shell's state and a one-off note.
    _activity: Activity
    _note: str | None
    #: The active session's title, if the store has one.
    _session_title: str | None
    #: Cumulative token counters for the active session.
    _usage: Usage
    #: Whether a turn or a command is in flight.
    _busy: bool
    #: When the garbage collector may run: while work is in flight, and not while the reader types.
    collector: CollectorPolicy
    #: Steering messages queued for this run, and how many were queued in all.
    _steering: list[str]
    #: What each queued steering message was made of, in step with :attr:`_steering`: the text the
    #: agent will report it by when it adopts it, and the parts it was sent as.
    _steering_meta: list[tuple[str, tuple[PromptPart, ...]]]
    _steering_sent: int
    #: The follow-ups waiting in send order, the highlighted one, and the slot a message
    #: taken out for editing will return to.
    _follow_ups: list[FollowUp]
    _follow_up_selected: int | None
    _editing_slot: int | None
    #: Whether the list is held: a request was stopped or failed with follow-ups waiting, and
    #: no reply has completed since.
    _follow_ups_held: bool
    #: Whether the work in flight is a turn, which can be steered, rather than a command.
    _turn_running: bool
    #: The in-flight request that names a session, if any.
    _title_task: asyncio.Task[None] | None
    #: The in-flight re-measure of a context figure, if any.
    _measure_task: asyncio.Task[None] | None
    #: The in-flight release check or upgrade, if any.
    _update_task: asyncio.Task[None] | None
    #: A short-lived message for the row above the composer: its text and the
    #: moment it stops being true.
    _flash: tuple[str, float, str] | None
    #: The effort switch being animated: the level it came from, the level it is
    #: reaching, and the moment it started.
    _effort_animation: tuple[str, str, float] | None
    #: The question the model is waiting on, while its panel is up.
    _asks: list[QuestionAsked]
    #: The turn or command currently in flight, if any.
    _task: asyncio.Task[None] | None

    def close_page(self) -> None:
        """Close the page a command presented."""

    def change_model(self, name: ModelConfig | str) -> ModelConfig:
        """Switch models and announce the change in the transcript."""
        raise NotImplementedError

    async def resume_session(self, session_id: str) -> None:
        """Restore a stored session behind the interface rather than in front of it."""

    def _set_busy(self, busy: bool) -> None:
        """Track in-flight work and keep the frame loop alive while it runs."""

    def _start_next_command(self) -> None:
        """Run the command that was typed while the finished request was busy."""

    def _return_follow_ups_to_draft(self) -> None:
        """Hand the held follow-ups back as text, because their conversation is over."""

    @property
    def _follow_up_selecting(self) -> bool:
        """Return whether a follow-up is highlighted."""
        return False

    def _select_follow_up(self, step: int) -> None:
        """Move the follow-up highlight."""

    def _deselect_follow_up(self) -> None:
        """Take the follow-up highlight off."""

    def _move_follow_up(self, step: int) -> None:
        """Swap the highlighted follow-up with its neighbour."""

    def _edit_follow_up(self) -> bool:
        """Take the highlighted follow-up out and into the composer."""
        return False

    def _delete_follow_up(self) -> None:
        """Remove the highlighted follow-up from the list."""

    def _steer_follow_up(self) -> bool:
        """Send the highlighted follow-up to the running request as steering."""
        raise NotImplementedError

    def _queue_steering(self, value: str, key: str | None = None, parts: Sequence[PromptPart] = ()) -> None:
        """Show one message waiting for the agent to adopt it."""

    def _clear_steering(self) -> None:
        """Drop the steering list."""

    def _refuse_busy(self) -> None:
        """Tell the reader a draft cannot be taken while a request runs."""

    def _refresh_completions(self) -> None:
        """Mirror the composer's slash-command candidates into the menu."""

    async def _run_prompt(
        self,
        prompt: str,
        parts: Sequence[PromptPart] = (),
        hint: str | None = None,
        *,
        relayed: Relayed | None = None,
    ) -> None:
        """Stream one agent turn."""

    def _sync_messaging(self) -> None:
        """Tell the other sessions what this one is now."""

    def _sync_lock(self) -> None:
        """Make the composer and the messaging agree with who holds the active session's lock."""

    def _start_next_relayed(self) -> bool:
        """Start the oldest message another session sent, if one waits and nothing runs."""
        return False

    async def run_continue(self) -> None:
        """Pick up the interrupted request where it stopped."""

    def submit(self, value: str, *, command: bool | None = None) -> bool | None:
        """Start a turn, steer the running one, or run a slash command (``command``: whether the draft is one)."""

    def flash(self, message: str, *, seconds: float = FLASH_SECONDS, level: str = "info") -> None:
        """Say something in the row above the composer, for a few seconds."""

    def change_permission(self, name: str, *, remember: bool = True) -> str:
        """Set how much of the shell may run unasked, and announce the change."""
        return name

    def start_effort_animation(self, previous: str, current: str) -> None:
        """Animate the effort slot of the header for a second."""

    def _effort_gauge(self) -> EffortFrame | ShimmerFrame | None:
        """Return the effort gauge for this paint, or None when the switch is over."""

    def settle_effort_animation(self) -> None:
        """Repaint while an effort switch animates, and release its token at the end."""

    def notify(self, message: str, *, level: str = "info") -> None:
        """Show a one-line toast."""

    def _remeasure_context_later(self) -> None:
        """Measure the context again, when a figure needs replacing."""

    def _cancel_ask(self, question: QuestionAsked) -> None:
        """Decline one question the model is waiting on, and close its panel."""

    def start_update_check(self) -> asyncio.Task[None] | None:
        """Ask the index about newer releases in the background."""

    def offer_update(self) -> UpdateState | None:
        """Show the panel a stored newer version asks for, if there is one."""

    def _refresh_tasks(self) -> None:
        """Mirror the agent's plan into the panel above the composer."""
