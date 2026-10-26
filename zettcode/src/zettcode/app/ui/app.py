"""The ZettCode application shell: the controller behind the terminal UI.

It owns the agent, the widget tree, the keymap, and the slash commands, and it
is the only place that decides what a command result looks like on screen. The
widgets themselves live in :mod:`zettcode.app.ui.widgets`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from time import monotonic
from typing import TYPE_CHECKING, Any

from zettcode.app.plugins.state import (
    Activity,
    TurnContext,
    UiRow,
)
from zettcode.config_edit import ConfigEditError
from zettcode.paths import DEFAULT_LOG
from zettcode.tui import (
    DARK,
    DONE,
    ELLIPSIS,
    PROMPT,
    SEPARATOR,
    CompletionPopup,
    Rect,
    RichText,
    Screen,
    Span,
    StatusBar,
    Style,
    TaskPanel,
    TextArea,
    TextLine,
    Theme,
    TuiApp,
    VBox,
    walk,
)
from zettcode.tui.clipboard import copy_route
from zettcode.tui.layout import Slot
from zettcode.tui.render import display_width
from zettcode.tui.widgets import Rule

if TYPE_CHECKING:  # pragma: no cover - annotations only
    pass
from zettcode.error_text import describe_error
from zettcode.mentions import MentionRegistry, SessionMentions
from zettcode.prompt import PromptPart, carries_image, mention_parts
from zettcode.registry import Registry
from zettcode.relay import Relayed
from zettcode.sdk.events import QuestionAsked
from zettcode.sdk.types import IncomingMessage, Usage

from ..agent.agent import SessionLink, TerminalAgent
from ..agent.conversation.effort_gauge import EFFORT_SECONDS, EffortFrame, effort_frame
from ..agent.conversation.projection import TranscriptProjector
from ..agent.conversation.shimmer import (
    SHIMMER_LEVELS,
    ShimmerFrame,
    shimmer_frame,
    shimmer_seconds,
    shimmer_width,
)
from ..agent.conversation.text import clock_text, elapsed_text
from ..agent.conversation.tips import TipDeck
from ..agent.conversation.transcript import Transcript
from ..commands import COMMAND_ERRORS, Command, CommandContext, CommandList, CommandResult
from ..pets import DEFAULT_PET_NAME, Pet
from .bars import BarsMixin
from .commands import ShellCommands
from .followups import FollowUp, FollowUpsMixin
from .gc_policy import CollectorPolicy, freeze_long_lived
from .keys import KeysMixin
from .messaging import MessagingMixin
from .notices import NoticesMixin
from .providers import ConfigMixin
from .sessions import SessionMixin
from .settings import SettingsMixin
from .shell import EFFORT_TOKEN, EMPTY_REPLY, FLASH_SECONDS, PAGE_SCREEN
from .turns import TurnTally, failure_line, plan_rows, prompt_pieces, turn_parts
from .updating import UpdateMixin
from .widgets import (
    WELCOME,
    CommandCompleter,
    Composer,
    FollowUpQueue,
    PetView,
    SteeringQueue,
    TranscriptView,
    ZettCodeRoot,
)


class ZettCodeApp(
    BarsMixin,
    KeysMixin,
    FollowUpsMixin,
    MessagingMixin,
    NoticesMixin,
    SessionMixin,
    SettingsMixin,
    ConfigMixin,
    UpdateMixin,
):
    """Own the application agent, widget tree, keymap, and slash commands."""

    def __init__(self, agent: TerminalAgent, *, theme: Theme = DARK, auto_theme: bool = True) -> None:
        """Wire the agent into the transcript, composer, panel, and keymap.

        Args:
            agent: Application agent that owns turns, sessions, and models.
            theme: Initial palette; ``/theme`` replaces it at runtime.
            auto_theme: Let the terminal's own background choose between the
                light and dark palettes at startup; a configured theme file
                passes ``False``, because then the palette was a choice.
        """
        self.agent = agent
        self.client = agent.client
        self._plugin_rows: tuple[UiRow, ...] = agent.plugin_rows
        # The program's own plugins come first, then the shell's commands, then the agent's, and the installed
        # plugins last: the first to claim a name owns it, so an installed plugin can add a command and can never
        # shadow one the program has.
        self.commands = Registry(
            [
                CommandList(agent.builtin_plugin_commands),
                ShellCommands(self),
                CommandList(agent.commands),
                CommandList(agent.plugin_commands),
            ]
        ).items()
        # The plugins' commands reach the shell through the context they are run with, and the words their menus
        # offer through this link; the shell is built enough by now that either may follow it.
        agent.attach_host(self)
        #: The line to the other sessions, when the configuration has one; a session name it offers for ``@``
        #: comes first, so it wins over a file or plugin resource of the same name.
        self.messenger: SessionLink | None = agent.messenger
        self.mentions = MentionRegistry(
            agent.plugin_mentions
            if self.messenger is None
            else (SessionMentions(self.messenger.peers), *agent.plugin_mentions)
        )
        self.transcript = Transcript(
            presenters=agent.presenters, max_entries=agent.runtime.config.transcript_max_entries
        )
        if agent.runtime.config.tips:
            self.transcript.tip_deck = TipDeck()
        self.transcript.welcome(WELCOME)
        for failure in agent.plugin_failures:
            self.transcript.error(f"plugin: {failure}")
        self.projector = TranscriptProjector(
            self.transcript,
            on_usage=self._usage_updated,
            on_steering_started=self._steering_started,
            on_steering_interrupted=self._steering_interrupted,
        )
        self.agent.set_event_dispatcher(self.projector)
        self.view = TranscriptView(self.transcript, theme=theme, wheel_speed=agent.runtime.config.mouse_scroll_speed)
        self.composer = Composer(
            prompt=f"{PROMPT} ",
            placeholder="Ask ZettCode to do anything",
            completer=CommandCompleter(self.commands, self.mentions),
            max_height=8,
            on_submit=self.submit,
            on_change=self._composer_changed,
            surface=True,
        )
        # What is painted and taken whole as a command or a reference is only what exists.
        self.composer.is_command = lambda name: self._lookup(name)[0] is not None
        self.composer.is_mention = lambda token: self.mentions.expand_token(token) is not None
        self.composer.on_locked_enter = self._retry_lock
        #: The row between the conversation and the composer: blank until something
        #: the reader just did needs saying, then a centred line that expires.
        self.flash_line = RichText(self._flash_line, align="center", wrap=False)
        self.completions = CompletionPopup(max_height=6)
        self.steering = SteeringQueue()
        self.follow_ups = FollowUpQueue()
        self.header = StatusBar(self._header_left, self._header_right)
        self.status = StatusBar(self._status_left, self._status_right)
        self.panel = TaskPanel()
        #: The companion over the conversation and the composer, which the reader can drag, choose with ``/pet`` and
        #: switch off in ``/statusline``.
        self._pet_before: Pet | None = None
        #: Whether the pet's place failed to be saved and the reader was told, so it is said once.
        self._pet_unsaved = False
        self.pet = PetView(
            self._starting_pet(),
            area=self._pet_area,
            shown=lambda: "pet" not in self.agent.statusline_hidden,
            busy=lambda: self._busy,
            forward=self.view,
            position=self.agent.runtime.config.pet_position,
            on_moved=self._remember_pet_position,
        )
        body = VBox(
            [
                Slot(self.header, size=1),
                Slot(Rule(), size=1),
                Slot(self.view, flex=1),
                Slot(self.panel, size=lambda width: self.panel.preferred_height()),
                Slot(self.flash_line, size=1),
                Slot(self.completions, size=lambda available: self.completions.visible_height),
                Slot(self.steering, size=lambda width: self.steering.preferred_height()),
                Slot(self.follow_ups, size=lambda width: self.follow_ups.preferred_height()),
                Slot(self.composer, size=lambda width: self.composer.preferred_height(width)),
                Slot(self.status, size=1),
            ]
        )
        self.root = ZettCodeRoot(self, body, self.pet)
        # The listener is installed here for a shell that runs its own app, and
        # again by :meth:`adopt` for one that hands its tree to the boot frame's:
        # the copy is handled by whichever app ends up running. Installing it
        # twice is a no-op, because a handler is not chained onto itself.
        self.app = TuiApp(
            self.root,
            theme=theme,
            reduced_motion=agent.reduced_motion,
            auto_theme=auto_theme,
            on_copy=self._copied,
        )
        # The terminal tab says what this session is about, like any editor tab.
        self.app.title = self._terminal_title
        self._task: asyncio.Task[None] | None = None
        self._title_task: asyncio.Task[None] | None = None
        #: A short-lived message for the row above the composer: the text and the
        #: moment it stops being true. It lives here rather than in the status line
        #: because the status line is a standing report of what the shell is doing,
        #: while this answers something the reader just did.
        self._flash: tuple[str, float, str] | None = None
        self._effort_animation: tuple[str, str, float] | None = None
        #: The context re-measure a restore started, replaced by the next restore.
        self._measure_task: asyncio.Task[None] | None = None
        #: The release check or upgrade in flight. Set here, not only where one is
        #: started: the shutdown drops it whatever the configuration, and a shell
        #: that never started one — because the update check is off, or because it
        #: is leaving before the background work began — has nothing else to drop.
        self._update_task: asyncio.Task[None] | None = None
        self._updating = False
        self._theme_before = None
        self._previewing = None
        #: The runtime warm-up this shell started, released on the way out.
        self._warm: asyncio.Task[object] | None = None
        self._busy = False
        #: When the garbage collector may run: while work is in flight, and not while the reader types.
        self.collector = CollectorPolicy()
        self._steering: list[str] = []
        self._steering_meta: list[tuple[str, tuple[PromptPart, ...]]] = []
        self._steering_sent = 0
        self._follow_ups: list[FollowUp] = []
        self._follow_up_selected: int | None = None
        self._editing_slot: int | None = None
        self._follow_ups_held = False
        self._turn_running = False
        self._inbox: list[Relayed] = []
        self._lock_watch: asyncio.Task[None] | None = None
        self._lock_said: str | None = None
        self._messaging_live = False
        self._messaging_trouble = False
        self._messaging_session: str | None = None
        self._messaging_start: asyncio.Future[None] | None = None
        self._asks: list[QuestionAsked] = []
        self._ask_total = 0
        #: Drafts typed while a request was in flight, in arrival order: only
        #: commands that declare ``when_busy="queue"`` land here.
        self._pending: list[str] = []
        #: Commands running beside a request (``when_busy="now"``), held so they are not collected
        #: while they run and can be cancelled when the shell leaves.
        self._now_tasks: set[asyncio.Task[None]] = set()
        self._activity = Activity.READY
        self._note: str | None = None
        self._session_title: str | None = None
        self._usage = Usage()
        self._install_keymap()

    @property
    def busy(self) -> bool:
        """Return whether a turn or command is in flight."""
        return self._busy

    def _pet_area(self) -> Rect:
        """Return where the pet may stand: from the top of the conversation to the bottom of the composer.

        That takes in the rows between them (the flash line, the menu, the queued messages) and the composer itself,
        so the pet can sit on the box the reader types in, in the empty space to the right of the draft. It stops at
        the bars: the header and the status line are not its ground. A panel that is open covers it, as it covers
        everything under it, because the panel is a screen above this one.
        """
        view, composer = self.view.rect, self.composer.rect
        if composer.empty or composer.bottom <= view.y:
            return view
        return Rect(view.x, view.y, view.width, max(view.height, composer.bottom - view.y))

    def _remember_pet_position(self, across: float, down: float) -> None:
        """Keep where the pet was left in the config file, so the next start puts it back.

        A pet is not worth an error, so a failure is a notice and not an error row, and it is said once a session: a
        reader whose configuration is the environment has no file to write it to, and a file that cannot be edited
        safely is theirs to fix by hand. Said nothing, they would only find the pet at its usual place the next
        time and not know why.
        """
        try:
            self.agent.remember_pet_position(across, down)
        except ConfigEditError as error:
            if not self._pet_unsaved:
                self._pet_unsaved = True
                self.transcript.notice(f"The pet's place was not saved: {error}")
                self.app.invalidate()

    def _starting_pet(self) -> Pet:
        """Return the pet the configuration names, or the default one when it names none that exists.

        A name nobody offers is the reader's typo, or a plugin that was uninstalled; it is said in the conversation
        rather than ending the start, because a pet is not worth a refusal to run.
        """
        catalog = self.agent.pets
        wanted = self.agent.runtime.config.pet
        if wanted:
            try:
                return catalog.load(wanted)
            except ValueError as error:
                self.transcript.error(f"pet: {error}")
        return catalog.load(DEFAULT_PET_NAME)

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Return the command or turn currently in flight, if any."""
        return self._task

    async def run(self) -> None:
        """Own the terminal until the application exits.

        The runtime is started in the background as the first frame appears:
        its provider SDK costs a few hundred milliseconds, nothing on screen
        waits for it, and the first turn awaits the same task. The release
        check is a background task for the same reason, and the panel it may
        deserve is drawn from the file the *last* check left, so no start waits
        on the network.
        """
        from zettcode.tui import Terminal, TerminalRunner

        self.start_background()
        try:
            await TerminalRunner(self.app, terminal=Terminal(diagnostics=DEFAULT_LOG)).run()
        finally:
            await self.stop_background()

    def _copied(self, text: str) -> None:
        """Say how much was copied, wherever the copy came from.

        Every copy passes through the host: a drag that selects and releases, a
        drag over a panel's painted cells, and Ctrl-C all end in ``copy``.
        Announcing it from there is what keeps them from drifting — the first
        version of this spoke only on the key, so a reader who dragged, which is
        the way the guide teaches, saw nothing at all.

        Over ``ssh`` it says "sent", and to the terminal's clipboard, rather than
        "copied": the text was handed to the terminal, which puts it on the clipboard
        of the machine the reader is sitting at — and a terminal may refuse, which the
        program cannot see. "Copied to clipboard" would be a claim about a machine this
        program is not on and a result it cannot check; "sent" is only what it did.
        """
        n = len(text)
        if copy_route() == "terminal":
            self.flash(f"sent {n} chars to your terminal's clipboard", level="success")
        else:
            self.flash(f"copied {n} chars to clipboard", level="success")

    def start_effort_animation(self, previous: str, current: str) -> None:
        """Animate the effort slot for a second, when the moment is right for it.

        Skipped while a request runs, because the waiting row already owns the
        motion — one row owns it in this shell — and skipped under reduced motion,
        which asks for none at all. That flag is read from the running app rather
        than from the config it came from, so this reads the same snapshot every
        other animation in the tree reads; `adopt` is what keeps them in step. The
        transcript's own row reports the change either way, so nothing is lost when
        the gauge does not appear.
        """
        if self.app.reduced_motion or self._busy:
            self._effort_animation = None
            return
        self._effort_animation = (previous, current, monotonic())
        self.app.scheduler.animate(EFFORT_TOKEN, active=True)
        self.app.request_layout()

    def _effort_gauge(self) -> EffortFrame | ShimmerFrame | None:
        """Return the gauge for this paint, or None when the switch is over.

        The clock and the state are read here, in the module that set them: an
        animation whose start and whose frame come from two import sites is one
        clock in a running shell and two in a test. Progress is a fraction of
        elapsed time, not a frame count, so the motion is as smooth as the loop
        that paints it and a slow terminal drops frames instead of slowing down.
        A switch to the top of the scale is a different animation, and a longer one:
        light crossing the whole row from right to left, which needs to know how wide
        the row is, so it is told where the gauge starts.
        """
        animation = self._effort_animation
        if animation is None:
            return None
        previous, current, started = animation
        if current in SHIMMER_LEVELS:
            lead = display_width(self.client.model.name) + len(f" {SEPARATOR} ")
            reach = max(self.app.width, shimmer_width(lead, len(self.client.efforts), current))
            progress = (monotonic() - started) / shimmer_seconds(current, reach)
            return shimmer_frame(current, self.client.efforts, lead=lead, reach=reach, progress=progress)
        progress = (monotonic() - started) / EFFORT_SECONDS
        return effort_frame(previous, current, self.client.efforts, progress=progress)

    def settle_effort_animation(self) -> None:
        """Repaint while the switch animates, and release the token when it ends."""
        if self._effort_animation is None:
            return
        if self._effort_gauge() is None:
            # Past the last frame: the header goes back to the segments a plugin
            # registered, and the token goes with the animation.
            self._effort_animation = None
            self.app.scheduler.animate(EFFORT_TOKEN, active=False)
            self.app.request_layout()
            return
        self.app.invalidate()

    def flash(self, message: str, *, seconds: float = FLASH_SECONDS, level: str = "info") -> None:
        """Say something in the row above the composer, for a few seconds.

        Args:
            message: One line, drawn centred; the row is blank again when it ends.
            seconds: How long it stays.
            level: ``"info"`` is plain accent text, the way a hint reads. ``"success"`` is a
                pill — the text on a raised fill with a check in front — for the one kind of
                message that answers something the reader just did and should be seen to
                have worked.
        """
        self._flash = (message, monotonic() + seconds, level)
        self.app.request_layout()

    def _flash_line(self) -> TextLine:
        """Return the flash as a styled line, which is what that row paints.

        A plain flash is the accent rather than the muted grey the hints use, and
        nothing more: bold would make the row shout for two seconds. A success is the
        one that has to be *seen* — a copy leaves nothing else on screen to show it
        happened — so it is a pill: the text on the theme's emphasis fill, with a check
        in front. The row's width is the text's, so the fill covers the words and the
        space around them and stops there, which is what makes it a pill rather than a
        stripe across the screen.
        """
        message = self._flash_text()
        if not message:
            return TextLine(())
        theme = self.app.theme
        if self._flash is not None and self._flash[2] == "success":
            fill = theme.selection
            return TextLine(
                (
                    Span(f" {DONE} ", Style(foreground=theme.accent_bright, background=fill, bold=True)),
                    Span(f"{message} ", Style(foreground=theme.text, background=fill)),
                )
            )
        return TextLine((Span(message, Style(foreground=theme.accent)),))

    def _flash_text(self) -> str:
        """Return the flash while it lasts, which is what that row paints."""
        if self._flash is None:
            return ""
        message, expires, _ = self._flash
        if monotonic() >= expires:
            self._flash = None
            return ""
        return message

    def settle_flash(self) -> None:
        """Ask for a repaint while a flash is alive, so it can expire on its own."""
        if self._flash is not None and self._flash_text():
            self.app.invalidate()

    def start_background(self) -> None:
        """Begin the work that belongs behind the first frame.

        The runtime warms — its provider SDK costs a few hundred milliseconds,
        and it starts loading its token counter with it — and the release check
        runs, nothing on screen waits for either, and the first turn awaits the
        same task. Called once the interface is up, whether :meth:`run` put it
        there or the command line painted a frame before this application
        existed.
        """
        self.collector.rest()
        self._warm = asyncio.ensure_future(self.agent.runtime.start())
        # Once the SDKs are loaded and the client is built, that heap is permanent: the collector has
        # no reason to walk it again. A warm-up that failed freezes what it did load, which is as true.
        self._warm.add_done_callback(lambda _: freeze_long_lived())
        self.start_update_check()
        self.offer_update()
        if self.client.session.locked:
            self._start_lock_watch()
        self._start_messaging()

    async def stop_background(self) -> None:
        """Release what :meth:`start_background` began, and end a request still in flight."""
        await self._stop_messaging()
        self._stop_lock_watch()
        await self._stop_title_task()
        await self._stop_update_task()
        self.collector.close()
        self._effort_animation = None
        self.app.scheduler.animate(EFFORT_TOKEN, active=False)
        measure, self._measure_task = self._measure_task, None
        if measure is not None:
            # A re-measure still in flight is a wait for the counter, which S8
            # says nothing on screen may pay for and nothing on the way out may
            # hold on to.
            measure.cancel()
            await asyncio.gather(measure, return_exceptions=True)
        await self._stop_turn()
        warm, self._warm = self._warm, None
        if warm is not None:
            # A warm-up still in flight is not worth waiting for: it is a launch
            # that ends before its first turn, and the imports it is running
            # belong to that turn. Cancelling reaches the runtime's own shutdown,
            # which asks the import thread to give up at its next module.
            warm = asyncio.ensure_future(warm)
            warm.cancel()
            # A start that failed is the first turn's error to report, not a
            # reason to keep the process alive or to raise on the way out.
            await asyncio.gather(warm, return_exceptions=True)

    async def _stop_turn(self) -> None:
        """End the turn in flight, if there is one, without waiting for the answer.

        The shell exits when the reader says so, whether or not a request is still
        streaming: that turn was for someone who has already left, and the session
        keeps everything it had already written. Letting it run on is what makes
        leaving feel like it did not work.
        """
        turn, self._task = self._task, None
        if turn is not None and not turn.done():
            turn.cancel()
        if turn is not None:
            await asyncio.gather(turn, return_exceptions=True)
        beside = list(self._now_tasks)
        for task in beside:
            task.cancel()
        await asyncio.gather(*beside, return_exceptions=True)

    def adopt(self, tui: TuiApp) -> None:
        """Move this application's interface into a shell that is already running.

        The command line paints the composer through a ``TuiApp`` it owns, then
        hands that same app here: the tree, the keymap, the command registry,
        and the title move over, so the widgets built here drive the terminal
        that is already taken. The palette is left alone when this application
        lets the terminal choose it, because the runner has already adopted the
        one the terminal asked for.

        What the reader typed into the placeholder's composer comes with it. The box on
        screen is the placeholder's until the swap, a keystroke lands wherever the box is,
        and the application takes a few hundred milliseconds to build — seven hundred to
        twelve hundred on a first run after an install — so a reader who starts typing the
        moment the frame appears would otherwise watch their words vanish when it is replaced.
        The swap happens on the event loop, so no key can arrive between reading the draft and
        writing it.

        Args:
            tui: Running app whose placeholder this application replaces.
        """
        placeholder = self.app
        typed = self._typed_into(tui)
        self.app = tui
        tui.commands = placeholder.commands
        tui.keymap = placeholder.keymap
        # The copy listener travels too: this application installs one to say what
        # was copied, the placeholder carries none, and a copy is handled by the
        # app that ends up running rather than by the one that built the tree.
        tui.set_copy_handler(self._copied)
        tui.title = self._terminal_title
        tui.reduced_motion = placeholder.reduced_motion
        tui.auto_theme = placeholder.auto_theme
        if not placeholder.auto_theme:
            tui.theme = placeholder.theme
        tui.set_root(self.root)
        if typed:
            self.composer.set_text(typed)

    @staticmethod
    def _typed_into(tui: TuiApp) -> str:
        """Return the draft in the composer the placeholder tree has, or nothing if it has none."""
        for widget in walk(tui.root):
            if isinstance(widget, TextArea):
                return widget.text
        return ""

    async def dry_run(self, *, width: int = 120, height: int = 40) -> None:
        """Run the whole start, paint one frame, and return.

        Profiling the shell means paying for everything the first frame pays
        for — the widget tree, the keymap, the runtime warming in the
        background, and one paint — without a terminal to sit in. The frame
        goes to a canvas that is thrown away; nothing reaches the screen.

        Args:
            width: Columns to lay the discarded frame out at.
            height: Rows to lay the discarded frame out at.
        """
        warm = self.agent.runtime.start()
        self.app.resize(width, height)
        self.app.mount()
        self.app.render()
        # A warm-up that failed is the first turn's to report, exactly as it is
        # when the shell really runs.
        await asyncio.gather(warm, return_exceptions=True)

    # -- commands -----------------------------------------------------------
    async def run_side_question(self, question: str) -> None:
        """Stream one ``/btw`` question, marking it in the transcript as one.

        The run needs the whole conversation to be useful, so it goes through
        the same session; it is the store that keeps the exchange out of the
        context afterwards (see :mod:`zettcode.engine.dialogue.side`). The side
        mechanics are the extension's, started and ended around this stream;
        what the shell adds is the marker on the turn, so the rows read as a
        question of the reader's rather than as part of the conversation.

        This is a run, not a query: the handler that owns ``/btw`` awaits it, so
        the busy flag, the request slot, and Ctrl-C are the command path's — a
        second ``/btw`` waits its turn like any queued command.
        """
        question = question.strip()
        if not question:
            self.transcript.notice("ask something: /btw <question>")
            return
        self.projector.begin_turn(question, side=True)
        started = monotonic()
        self.app.invalidate()
        outcome = ""
        try:
            async with self.client.session.ask_stream(question) as run:
                async for _event in run:
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            took = elapsed_text(monotonic() - started)
            outcome = f"btw stopped after {took} {SEPARATOR} {clock_text()}"
            raise
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.error(f"error: {describe_error(error)}")
            took = elapsed_text(monotonic() - started)
            outcome = f"btw failed after {took} {SEPARATOR} {clock_text()}"
        else:
            took = elapsed_text(monotonic() - started)
            outcome = f"btw answered for {took} {SEPARATOR} {clock_text()}"
        finally:
            # The same order as a turn: close what the run left open, then write
            # the line it ended on. A ``BaseException`` that is not caught above
            # leaves the outcome unset, and the running rows are still closed.
            self._close_run()
            if outcome:
                self._settle_wait(outcome)

    async def prompt(self, text: str, *, shown: str | None = None) -> bool:
        """Run ``text`` as one turn of this conversation, as if the reader had typed it.

        The draft path is taken whole — the echo, ``@`` references, the transcript, the session, the row the
        request ends on — rather than a run of its own, so a command that asks the model something produces a turn
        a reader could have produced. What the command decides is the text; everything after that is the ordinary
        one.

        With ``shown``, the reader sees one thing and the model reads another: the shown text is what the turn
        draws in the transcript, and the text is the instructions the model reads after it. Both are in the message
        the session keeps — the instructions are not dropped, they are only kept out of what is displayed — so a
        later turn, and a restored session, still have them in front of the model.

        The turn is awaited, so the request slot stays the command's until the answer is in: a second draft cannot
        start behind it, and the command reports what it did once it is done.
        """
        if not text.strip():
            return False
        if self._updating:
            self.flash("updating ZettCode \u2014 this window takes no input until it is done", level="info")
            return False
        if self.client.session.locked:
            self.flash("this session is open in another ZettCode process; it is read-only here", level="error")
            return False
        display = (shown if shown is not None else text).strip() or text.strip()
        if display == text.strip():
            # No `@` pass here: the SDK resolves the references itself (it is asked for them below), and doing
            # both is how the same instructions once reached the model twice.
            await self._run_prompt(text, (), advance=False)
        else:
            # The brief is not the reader's message: it rides after the shown text, which is what the transcript
            # draws. The SDK keeps both in the message and shows the reader the first.
            await self._run_prompt(display, (), instructions=text, advance=False)
        return True

    async def run_continue(self) -> None:
        """Pick up the request that was interrupted, where it stopped, as a turn of the conversation.

        A request can end without finishing: the connection dropped, the reader pressed Esc, the process was killed,
        the model hit its output limit. The history says which, and the library knows what each calls for (see
        :class:`zett_agent.resume.ResumeKind`), so this asks it, tells the reader what it is about to do, and runs
        it. A tool is never run again on its own: the model is told which ones were cut short and decides.

        Like ``/btw`` this is run by the command that owns it, so the busy flag and the request slot are the command
        path's. Unlike ``/btw`` it is part of the conversation, so it may be steered and what it ends on is a reply:
        the follow-ups a stop held go out behind it.
        """
        info = await self.client.session.resumable()
        if info is None:
            self.transcript.notice(await self.agent.resume_blocker() or "There is nothing to continue.")
            return
        self.transcript.notice(info.description)
        self.transcript.wait_for_model()
        started = monotonic()
        completed = False
        tally = TurnTally(self.client.usage)
        self._turn_running = True
        self.app.invalidate()
        try:
            self._refresh_tasks()
            async with self.client.session.resume_stream(**self._answers()) as run:
                async for event in run:
                    tally.see(event)
                    self._refresh_tasks()
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            self.transcript.notice("stopped")
            raise
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.error(failure_line(error))
        else:
            completed = True
            self._follow_ups_held = False
            if self.transcript.turn_said_nothing():
                self.transcript.notice(EMPTY_REPLY)
            self._title_session_later(self.client.session.id)
        finally:
            self._close_run()
            if completed:
                self.transcript.summarize_changes(self.client.workspace)
            seconds = monotonic() - started
            self._settle_wait(
                f"Continued for {elapsed_text(seconds)} {SEPARATOR} {clock_text()}",
                tally.context(self.client.usage, label="Continued", seconds=seconds, clock=clock_text()),
            )
            self._drop_ask()
            self._turn_running = False
            self._refresh_tasks()
            self.app.invalidate()

    def _lookup(self, value: str) -> tuple[Command | None, str]:
        """Split a typed line into the command it names and its argument.

        The one place a draft is cut apart, so the composer, the router, and the
        queue all agree on what ``/name argument`` means. An unknown name answers
        ``None`` and the whole tail as the argument.
        """
        name, argument = (value.split(None, 1) + [""])[:2] if value.strip() else ("", "")
        return next((item for item in self.commands if item.name == name), None), argument.strip()

    def _is_command(self, value: str) -> bool:
        """Return whether a draft is a command: it opens with the name of one the shell really has.

        ``/usr/bin`` or ``/tmp is full`` or a typo is not one. It is text, and goes to the model like any other.
        This is the same test the composer paints a command by, so what is drawn as a command is what runs as one.
        """
        return value.startswith("/") and self._lookup(value)[0] is not None

    def _run_command_now(self, command: Command, argument: str) -> None:
        """Run a command beside the request in flight, without taking the busy state.

        ``_run_command`` owns everything about a run being in progress: it sets the busy flag,
        the activity and the task, and when it ends it clears them and settles the waiting
        messages. Done for a command typed during a request, that would end the request's
        busy state under it and hand the unread steering back as if the request were over. So
        this does none of that. The handler runs on a task of its own, its result is shown the
        way any command's is, and Ctrl-C and Escape still mean the request.

        A failure is reported in the conversation: a command that did nothing and said nothing is
        worse than one that failed.

        Args:
            command: The command, whose ``when_busy`` is ``"now"``.
            argument: What followed its name.
        """
        task = asyncio.create_task(self._execute_now(command, argument))
        self._now_tasks.add(task)
        task.add_done_callback(self._now_tasks.discard)

    async def _execute_now(self, command: Command, argument: str) -> None:
        """Await one handler and show what it returned, or why it could not."""
        try:
            result = await command.handler(CommandContext(argument=argument, ui=self, host=self))
        except COMMAND_ERRORS as error:
            self.transcript.error(str(error))
        except Exception as error:  # noqa: BLE001 - a command's bug is reported, never swallowed
            self.transcript.error(f"{command.name}: {describe_error(error)}")
        else:
            self._apply_result(result)
        self.app.invalidate()

    def _queue_command(self, value: str) -> None:
        """Hold one typed command until the request in flight is done."""
        self._pending.append(value)
        self.transcript.notice(f"queued for after this request ({len(self._pending)} waiting)")
        self.app.invalidate()

    def _start_next_command(self) -> None:
        """Run what was typed while the finished request was busy: a command, then follow-ups.

        A queued command goes first. It was typed as a command, and a command such as
        ``/btw`` does not join the conversation, so it cannot put a follow-up's answer out of
        order. Follow-ups then go out one at a time: each is a turn of its own, and the next
        waits for that turn to end. They go out only while the list is not held: after a
        request that was stopped or failed it is, and it stays so until a reply completes.
        """
        if self._busy:
            return
        if self._pending:
            self._task = asyncio.create_task(self._run_command(self._pending.pop(0)))
        elif self._follow_ups and not self._follow_ups_held:
            self._start_follow_up()
        else:
            self._start_next_relayed()

    def submit(self, value: str, *, command: bool | None = None) -> bool | None:
        """Start a turn or a slash command, or take a message typed while one runs.

        Plain text typed during a request is not refused. The reader is asked
        whether it should steer — handed to the agent now, adopted at its next
        model or tool boundary — or follow up, held and sent as a turn of its own
        when the request ends; either way a list above the composer shows it until
        then. A slash command is refused while one runs, because there is no
        running request to steer — unless the command itself says otherwise with
        ``when_busy``: ``"queue"`` holds the draft and runs it the moment the request
        in flight ends, and ``"now"`` runs it at once, beside the request.

        Args:
            value: Draft text from the composer.
            command: Whether the draft is a slash command. Only a command is looked up and run as one; any
                other text, whatever it starts with, is a message and is never checked against the commands.
                Left out, it is worked out from the draft (see :meth:`_is_command`).

        Returns:
            False when the draft was refused; returning a true value also
            clears the composer.
        """
        if command is None:
            command = self._is_command(value)
        if self._updating:
            # The installation is being replaced under this process: nothing typed now can be run against it, and a
            # half-installed package is not a thing to hand a prompt to.
            self.flash("updating ZettCode \u2014 this window takes no input until it is done", level="info")
            return False
        if self.client.session.locked and not command:
            # Only commands are taken, which is how a reader leaves: the composer does not let anything else be
            # typed, and this is for what arrives some other way (a draft that was there already, a recall).
            self.flash("this session is open in another ZettCode process; it is read-only here", level="error")
            return False
        if self._busy:
            if command:
                # Which commands are taken mid-request is the command's own
                # decision, not a name the shell knows: a queued one runs the
                # moment the request in flight ends.
                chosen, argument = self._lookup(value)
                if chosen is None or chosen.when_busy == "refuse":
                    self._refuse_busy()
                    return False
                if chosen.when_busy == "now":
                    self._run_command_now(chosen, argument)
                    return True
                self._queue_command(value)
                return True
            if not value.strip():
                self._refuse_busy()
                return False
            # Plain text during a request is one of two things, and the text does not say
            # which: see :mod:`zettcode.app.ui.followups`.
            return self._send_while_busy(value)
        if command:
            self._task = asyncio.create_task(self._run_command(value))
        else:
            # The parts are taken before the composer is cleared, and keep the
            # order the chips sit in, so text and pictures stay interleaved.
            parts = mention_parts(self.composer.parts(), self.mentions)
            if carries_image(parts) and not self.client.model.multimodal:
                # A pasted base64 image reaches the composer without the shell
                # having seen the clipboard, so the model's own limits are
                # checked again here rather than only when Ctrl-V runs.
                self.transcript.error(f"{self.client.model.name} does not take images")
                self.app.invalidate()
                return False
            self._task = asyncio.create_task(self._run_prompt(value, parts, instructions=None))
        return True

    def _queue_steering(self, value: str, key: str | None = None, parts: Sequence[PromptPart] = ()) -> None:
        """Show one message waiting for the agent to adopt it.

        Args:
            value: The message as the list shows it.
            key: What the agent will call it when it adopts it. For text that is the text; for a
                message with pictures it is not, because the pictures split the text into runs
                that the agent's own ``text`` joins with line breaks, and matching on the typed
                text would leave the row in the list for good.
            parts: The message as the parts of a turn, kept so that a message the agent never
                read can be handed back with its pictures.
        """
        self._steering.append(value)
        self._steering_meta.append((value if key is None else key, tuple(parts)))
        self._steering_sent += 1
        self.steering.set_messages(self._steering)
        self.app.request_layout()
        self.app.invalidate()

    def _refuse_busy(self) -> None:
        """Tell the reader a draft cannot be taken while a request runs."""
        self.transcript.notice("busy \u2014 Ctrl-C stops the current request")
        self.app.invalidate()

    def _close_run(self) -> None:
        """Close any row the request left open when it ended.

        A tool call whose result never arrives — the reader stopped the request,
        or it failed — would otherwise keep saying ``Running…`` for the rest of
        the session, with a timer an animation step keeps bringing up.
        """
        self.transcript.finish_running_rows("Result unavailable (request ended)")

    def _settle_wait(self, text: str, turn: TurnContext | None = None) -> None:
        """Leave the line a request ended on in the pinned row, or as a notice.

        The wait row is the last line of the transcript while the request runs,
        so it is where a reader looks for the outcome, and it is settled whether
        the run answered, failed, or was stopped. A run that never opened one —
        a command working on its own — still gets the line, as a notice.

        Args:
            text: The line to leave behind, such as ``Processed for 12s · 22:53``.
            turn: What the request came to. The line is then made of the items the plugins registered for it
                (the program's own, and any a plugin added), less the ones switched off in ``/statusline``;
                ``text`` stands when no item is left to say anything.
        """
        parts = turn_parts(self.agent.turn_segments, turn, self.agent.statusline_hidden) if turn else ()
        if not self.transcript.settle_wait(text, parts):
            self.transcript.notice(f" {SEPARATOR} ".join(parts) or text)

    def _clear_steering(self) -> None:
        """Drop the queue, for instance when the turn it belonged to ended."""
        self._steering_sent = 0
        if not self._steering:
            return
        self._steering.clear()
        self._steering_meta.clear()
        self.steering.set_messages(())
        self.app.request_layout()

    def _steering_index(self, text: str) -> int | None:
        """Return the place in the queue of the message the agent reports by ``text``, if it is there."""
        for index, value in enumerate(self._steering):
            key = self._steering_meta[index][0] if index < len(self._steering_meta) else value
            if key == text:
                return index
        return None

    def _drop_steering(self, text: str) -> None:
        """Take one message out of the queue, wherever the agent's name for it puts it."""
        index = self._steering_index(text)
        if index is not None:
            del self._steering[index]
            if index < len(self._steering_meta):
                del self._steering_meta[index]
            self.steering.set_messages(self._steering)
            self.app.request_layout()
        self.app.invalidate()

    def _steering_started(self, text: str) -> None:
        """Drop a message the agent just adopted; the projector echoes its row."""
        self._drop_steering(text)

    def _steering_interrupted(self, text: str) -> None:
        """Drop a queued message a newer steering message superseded."""
        self._drop_steering(text)

    def _answers(self) -> dict[str, Any]:
        """Return what a run is started with so that the shell's panels answer for it.

        The panels open from the handlers and the reader chooses later, from the panel, so the requests are left open
        past their event (``defer_answers``) and answered with the event's own ``approve``, ``deny``, ``answer`` and
        ``decline``. The projector draws the transcript; it does not ask.
        """
        return {
            "on_approval": self._approval_requested,
            "on_question": self._ask_requested,
            "defer_answers": True,
        }

    async def _run_prompt(
        self,
        prompt: str,
        parts: Sequence[PromptPart] = (),
        *,
        instructions: str | None = None,
        relayed: Relayed | None = None,
        advance: bool = True,
    ) -> None:
        """Stream one agent turn, keeping the task panel and transcript current.

        Args:
            prompt: What the user typed, image chips included, as it is echoed
                into the transcript.
            parts: The same turn as ordered text and image parts; an empty
                sequence falls back to the prompt alone.
            instructions: What the model reads after the prompt but the reader does not: the SDK resolves the
                draft's ``@`` references itself, so this carries only what a command adds (see
                :meth:`CommandHost.prompt`). The stored message keeps ``prompt``.
            relayed: The turn answers a message another session sent, which the transcript draws as
                that, the model is told where it came from, and the session stores as that.
        """
        if relayed is None:
            self.projector.begin_turn(prompt)
        else:
            self.projector.begin_turn(prompt, relayed=relayed)
        if self.messenger is not None:
            # What this turn answers decides how many hops an answer sent from it carries.
            self.messenger.answering = relayed
        started = monotonic()
        completed = False
        tally = TurnTally(self.client.usage)
        self._turn_running = True
        self._set_busy(True)
        self._activity = Activity.RUNNING
        self._note = None
        self.app.invalidate()
        try:
            self._refresh_tasks()
            # A turn is a message the reader wrote (text, pictures, and ``@`` references the SDK resolves with the same
            # registry the composer completes from), or one another session sent.
            if relayed is not None:
                run = self.client.session.relay(
                    IncomingMessage(
                        sender_id=relayed.sender_id,
                        sender=relayed.sender,
                        text=relayed.text,
                        via=relayed.via,
                        hops=relayed.hops,
                    ),
                    **self._answers(),
                )
            else:
                run = self.client.session.prompt(
                    prompt_pieces(parts or (prompt,)),
                    mentions=True,
                    instructions=instructions,
                    **self._answers(),
                )
            async with run:
                async for event in run:
                    tally.see(event)
                    self._refresh_tasks()
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            self.transcript.notice("stopped")
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.error(failure_line(error))
        else:
            completed = True
            if self.transcript.turn_said_nothing():
                self.transcript.notice(EMPTY_REPLY)
            self._title_session_later(self.client.session.id)
        finally:
            seconds = monotonic() - started
            took = elapsed_text(seconds)
            if self.messenger is not None:
                self.messenger.answering = None
            # Before the pinned row is settled, not after: what happened to the waiting
            # messages is part of how the request ended, and the line that says how long it
            # ran stays the last thing in the transcript, where a reader looks for it.
            self._settle_queues(completed, turn=True)
            self._close_run()
            # Which files this request changed, said once and only when there are any, above the
            # line that says how long it took.
            self.transcript.summarize_changes(self.client.workspace)
            self._settle_wait(
                f"Processed for {took} {SEPARATOR} {clock_text()}",
                tally.context(self.client.usage, label="Processed", seconds=seconds, clock=clock_text()),
            )
            self._drop_ask()
            self._turn_running = False
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self._refresh_tasks()
            self.app.invalidate()
            if advance:
                # A turn a command asked for leaves this to the command: it is still running, and what was queued
                # waits for it to end, not for the turn inside it.
                self._start_next_command()

    def _set_busy(self, busy: bool) -> None:
        """Track in-flight work and keep the frame loop alive while it runs.

        Rows that are still waiting animate from the frame counter: the sweep
        travels through their label and the status dot blinks. Frames only
        arrive while something asks for them, and work can be started by a plain
        command — `/compact` summarizes for seconds before its row is done — so
        the flag that says "busy" is what holds the animation token.
        """
        self._busy = busy
        self._sync_messaging()
        # The collector runs while there is work and is off while there is none, so an idle shell
        # and the reader's typing are never interrupted by it.
        if busy:
            self.collector.work_started()
        else:
            self.collector.work_ended()
        self.app.scheduler.animate("activity", active=busy)
        if self._follow_ups:
            # The list's keys line says what it is waiting for, which is a different thing
            # while a request runs and while none does.
            self._sync_follow_ups()

    def _refresh_tasks(self) -> None:
        """Mirror the agent's current plan into the panel above the composer."""
        if self.panel.set_tasks(plan_rows(self.client.session.tasks())):
            self.app.request_layout()

    async def _run_command(self, value: str) -> None:
        """Execute the matching command's handler and present its result."""
        command, argument = self._lookup(value)
        # An unknown name still needs one for the status note and the error, and
        # there is no command to borrow it from.
        name = command.name if command is not None else value.partition(" ")[0]
        self._activity = Activity.RUNNING
        self._note = f"{name} {ELLIPSIS}"
        # A command may take a while — `/compact` summarizes the conversation —
        # so it holds the same busy flag a turn does: the status glyph spins,
        # another submit is refused, and Ctrl-C cancels what is running.
        self._set_busy(True)
        self.app.invalidate()
        completed = False
        try:
            previous_session = self.client.session.id
            if command is None:
                self.transcript.error(f"Unknown command: {name}. Try /help.")
            else:
                try:
                    result = await command.handler(CommandContext(argument=argument, ui=self, host=self))
                    if name == "/new" and self.client.session.id != previous_session:
                        self.transcript.clear()
                        self.transcript.welcome(WELCOME)
                        self.view.scroll_end()
                        self.view.clear_selection()
                        self._remember_session_title()
                        self._sync_lock()
                        self._usage = self.client.usage
                        self._refresh_tasks()
                        self._return_follow_ups_to_draft()
                        self.app.request_layout()
                except COMMAND_ERRORS as error:
                    self.transcript.error(str(error))
                else:
                    self._apply_result(result)
            completed = True
        finally:
            # A command stopped part-way is stopped like a turn is: what was queued behind
            # it was written for something that did not finish, and goes back to the draft.
            self._settle_queues(completed, turn=False)
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self.app.invalidate()
            # A queued command waited for whatever was running; with the busy
            # flag down again, this is where it starts.
            self._start_next_command()

    def _apply_result(self, result: CommandResult) -> None:
        """Show what a command returned: Markdown, a toast, a widget, a re-layout.

        The order mirrors how the screen stack paints: transcript content and
        the toast go up first, then the widget is stacked on top of them, and
        the re-layout happens last so it measures what was actually added.
        """
        if result.message:
            self.transcript.markdown(result.message)
        if result.notification:
            self.notify(result.notification, level="success")
        if result.widget is not None:
            self.app.push_screen(Screen(result.widget, name=PAGE_SCREEN, modal=True))
        if result.relayout:
            self.app.request_layout()
