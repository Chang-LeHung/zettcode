"""The ZettCode application shell: the controller behind the terminal UI.

It owns the agent, the widget tree, the keymap, and the slash commands, and it
is the only place that decides what a command result looks like on screen. The
widgets themselves live in :mod:`zettcode.app.ui.widgets`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import aclosing
from time import monotonic
from typing import TYPE_CHECKING, cast

from zett_agent.events import AgentEvent

from ...paths import DEFAULT_LOG
from ...plugins import (
    Activity,
    UiRow,
)
from ...tui import (
    DARK,
    DONE,
    ELLIPSIS,
    PROMPT,
    SEPARATOR,
    CompletionPopup,
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
from ...tui.clipboard import copy_route
from ...tui.layout import Slot
from ...tui.widgets import Rule

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator
from ..agent.agent import ZettCodeAgent
from ..agent.agent.prompt import PromptPart, carries_image, mention_hint, mention_parts
from ..agent.conversation.projection import TranscriptProjector
from ..agent.conversation.rows import EFFORT_SECONDS, EffortFrame, clock_text, effort_frame, elapsed_text
from ..agent.conversation.transcript import Transcript
from ..agent.dialogue.ask import AskUserQuestion
from ..agent.dialogue.mentions import MentionRegistry, SessionMentions
from ..agent.dialogue.relay import Relayed
from ..agent.errors import describe_error
from ..agent.extensions.messenger import Messenger
from ..agent.extensions.usage import UsageSnapshot
from ..commands import Command, CommandContext, CommandList, CommandResult
from ..registry import Registry
from .commands import ShellCommands
from .followups import FollowUp, FollowUpsMixin
from .gc_policy import CollectorPolicy, freeze_long_lived
from .keys import KeysMixin
from .messaging import MessagingMixin
from .notices import NoticesMixin
from .providers import ConfigMixin
from .rows import RowsMixin
from .sessions import SessionMixin
from .settings import SettingsMixin
from .shell import EFFORT_TOKEN, EMPTY_REPLY, FLASH_SECONDS, PAGE_SCREEN
from .updating import UpdateMixin
from .widgets import (
    WELCOME,
    CommandCompleter,
    Composer,
    FollowUpQueue,
    SteeringQueue,
    TranscriptView,
    ZettCodeRoot,
)


class ZettCodeApp(
    RowsMixin,
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

    def __init__(self, agent: ZettCodeAgent, *, theme: Theme = DARK, auto_theme: bool = True) -> None:
        """Wire the agent into the transcript, composer, panel, and keymap.

        Args:
            agent: Application agent that owns turns, sessions, and models.
            theme: Initial palette; ``/theme`` replaces it at runtime.
            auto_theme: Let the terminal's own background choose between the
                light and dark palettes at startup; a configured theme file
                passes ``False``, because then the palette was a choice.
        """
        self.agent = agent
        self._plugin_rows: tuple[UiRow, ...] = agent.plugin_rows
        self.commands = Registry(
            [
                ShellCommands(self),
                CommandList(agent.commands),
                CommandList(agent.plugin_commands),
            ]
        ).items()
        #: The line to the other sessions, when the configuration has one; the session names it offers
        #: for ``@`` come first, because a draft that begins with one is a message to that session.
        self.messenger: Messenger | None = agent.runtime.messenger
        self.mentions = MentionRegistry(
            agent.plugin_mentions
            if self.messenger is None
            else (SessionMentions(self.messenger.peers), *agent.plugin_mentions)
        )
        self.transcript = Transcript(max_entries=agent.runtime.config.transcript_max_entries)
        self.transcript.welcome(WELCOME)
        for failure in agent.plugin_failures:
            self.transcript.error(f"plugin: {failure}")
        self.projector = TranscriptProjector(
            self.transcript,
            on_approval=self._approval_requested,
            on_ask=self._ask_requested,
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
        self.root = ZettCodeRoot(self, body)
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
        self._sends: set[asyncio.Task[None]] = set()
        self._lock_watch: asyncio.Task[None] | None = None
        self._lock_said: str | None = None
        self._messaging_live = False
        self._messaging_trouble = False
        self._messaging_session: str | None = None
        self._messaging_start: asyncio.Future[None] | None = None
        self._asks: list[AskUserQuestion] = []
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
        self._usage = UsageSnapshot()
        self._install_keymap()

    @property
    def busy(self) -> bool:
        """Return whether a turn or command is in flight."""
        return self._busy

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
        from ...tui import Terminal, TerminalRunner

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

    def _effort_gauge(self) -> EffortFrame | None:
        """Return the gauge for this paint, or None when the switch is over.

        The clock and the state are read here, in the module that set them: an
        animation whose start and whose frame come from two import sites is one
        clock in a running shell and two in a test. Progress is a fraction of
        elapsed time, not a frame count, so the motion is as smooth as the loop
        that paints it and a slow terminal drops frames instead of slowing down.
        """
        animation = self._effort_animation
        if animation is None:
            return None
        previous, current, started = animation
        progress = (monotonic() - started) / EFFORT_SECONDS
        return effort_frame(previous, current, self.agent.efforts, progress=progress)

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
        if self.agent.session_locked:
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
        context afterwards (see :mod:`zettcode.app.agent.dialogue.side`). The side
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
        self.agent.runtime.sides.begin()
        outcome = ""
        try:
            async with aclosing(
                cast("AsyncGenerator[AgentEvent]", self.agent.stream((question,), side=True))
            ) as events:
                async for _event in events:
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
            self.agent.runtime.sides.end()

    def _lookup(self, value: str) -> tuple[Command | None, str]:
        """Split a typed line into the command it names and its argument.

        The one place a draft is cut apart, so the composer, the router, and the
        queue all agree on what ``/name argument`` means. An unknown name answers
        ``None`` and the whole tail as the argument.
        """
        name, _, argument = value.partition(" ")
        return next((item for item in self.commands if item.name == name), None), argument.strip()

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
            result = await command.handler(CommandContext(argument=argument, ui=self))
        except ValueError as error:
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

    def submit(self, value: str) -> bool | None:
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
            value: Draft text from the composer; a leading ``/`` selects the
                slash-command branch.

        Returns:
            False when the draft was refused; returning a true value also
            clears the composer.
        """
        if self.agent.session_locked and not value.startswith("/"):
            # Only commands are taken, which is how a reader leaves: the composer does not let anything else be
            # typed, and this is for what arrives some other way (a draft that was there already, a recall).
            self.flash("this session is open in another ZettCode process; it is read-only here", level="error")
            return False
        if not value.startswith("/"):
            # A draft that begins with the name of an active session is a message to it: sent whatever this
            # session is doing, because it is not a request to this session's model.
            sent = self._send_session_message(self.composer.parts())
            if sent is not None:
                return sent
        if self._busy:
            if value.startswith("/"):
                # Which commands are taken mid-request is the command's own
                # decision, not a name the shell knows: a queued one runs the
                # moment the request in flight ends.
                command, argument = self._lookup(value)
                if command is None or command.when_busy == "refuse":
                    self._refuse_busy()
                    return False
                if command.when_busy == "now":
                    self._run_command_now(command, argument)
                    return True
                self._queue_command(value)
                return True
            if not value.strip():
                self._refuse_busy()
                return False
            # Plain text during a request is one of two things, and the text does not say
            # which: see :mod:`zettcode.app.ui.followups`.
            return self._send_while_busy(value)
        if value.startswith("/"):
            self._task = asyncio.create_task(self._run_command(value))
        else:
            # The parts are taken before the composer is cleared, and keep the
            # order the chips sit in, so text and pictures stay interleaved.
            parts = mention_parts(self.composer.parts(), self.mentions)
            if carries_image(parts) and not self.agent.active_model.multimodal:
                # A pasted base64 image reaches the composer without the shell
                # having seen the clipboard, so the model's own limits are
                # checked again here rather than only when Ctrl-V runs.
                self.transcript.error(f"{self.agent.active_model.shown_name} does not take images")
                self.app.invalidate()
                return False
            self._task = asyncio.create_task(self._run_prompt(value, parts, mention_hint(parts, self.mentions)))
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

    def _settle_wait(self, text: str) -> None:
        """Leave the line a request ended on in the pinned row, or as a notice.

        The wait row is the last line of the transcript while the request runs,
        so it is where a reader looks for the outcome, and it is settled whether
        the run answered, failed, or was stopped. A run that never opened one —
        a command working on its own — still gets the line, as a notice.

        Args:
            text: The line to leave behind, such as ``Processed for 12s · 22:53``.
        """
        if not self.transcript.settle_wait(text):
            self.transcript.notice(text)

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

    async def _run_prompt(
        self,
        prompt: str,
        parts: Sequence[PromptPart] = (),
        hint: str | None = None,
        *,
        relayed: Relayed | None = None,
    ) -> None:
        """Stream one agent turn, keeping the task panel and transcript current.

        Args:
            prompt: What the user typed, image chips included, as it is echoed
                into the transcript.
            parts: The same turn as ordered text and image parts; an empty
                sequence falls back to the prompt alone.
            hint: Instructions the draft's ``@`` references contribute; the
                stored message keeps ``prompt``.
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
        self._turn_running = True
        self._set_busy(True)
        self._activity = Activity.RUNNING
        self._note = None
        self.app.invalidate()
        try:
            self._refresh_tasks()
            # A turn without ``@`` references is sent exactly as it was written,
            # without the keyword argument a reference-carrying turn adds; the
            # cast lets aclosing close the stream when the turn is cancelled.
            turn = parts or (prompt,)
            if relayed is not None:
                stream = self.agent.stream(turn, relayed=relayed)
            elif hint is None:
                stream = self.agent.stream(turn)
            else:
                stream = self.agent.stream(turn, hint=hint)
            async with aclosing(cast("AsyncGenerator[AgentEvent]", stream)) as events:
                async for _event in events:
                    self._refresh_tasks()
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            self.transcript.notice("stopped")
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.error(f"error: {describe_error(error)}")
        else:
            completed = True
            if self.transcript.turn_said_nothing():
                self.transcript.notice(EMPTY_REPLY)
            self._title_session_later(self.agent.session_id)
        finally:
            took = elapsed_text(monotonic() - started)
            if self.messenger is not None:
                self.messenger.answering = None
            # Before the pinned row is settled, not after: what happened to the waiting
            # messages is part of how the request ended, and the line that says how long it
            # ran stays the last thing in the transcript, where a reader looks for it.
            self._settle_queues(completed, turn=True)
            self._close_run()
            # Which files this request changed, said once and only when there are any, above the
            # line that says how long it took.
            self.transcript.summarize_changes(self.agent.workspace)
            self._settle_wait(f"Processed for {took} {SEPARATOR} {clock_text()}")
            self._drop_ask()
            self._turn_running = False
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self._refresh_tasks()
            self.app.invalidate()
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
        if self.panel.set_tasks(self.agent.tasks()):
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
            previous_session = self.agent.session_id
            if command is None:
                self.transcript.error(f"Unknown command: {name}. Try /help.")
            else:
                try:
                    result = await command.handler(CommandContext(argument=argument, ui=self))
                    if name == "/new" and self.agent.session_id != previous_session:
                        self.transcript.clear()
                        self.transcript.welcome(WELCOME)
                        self.view.scroll_end()
                        self.view.clear_selection()
                        self._remember_session_title()
                        self._sync_lock()
                        self._usage = self.agent.usage
                        self._refresh_tasks()
                        self._return_follow_ups_to_draft()
                        self.app.request_layout()
                except ValueError as error:
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
