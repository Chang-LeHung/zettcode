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
    ELLIPSIS,
    PROMPT,
    SEPARATOR,
    CompletionPopup,
    Screen,
    StatusBar,
    TaskPanel,
    Theme,
    TuiApp,
    VBox,
)
from ...tui.layout import Slot
from ...tui.widgets import Rule, Text

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator
from ..agent.agent import PromptPart, ZettCodeAgent, carries_image, mention_hint
from ..agent.ask import AskUserQuestion
from ..agent.mentions import MentionRegistry
from ..agent.projection import TranscriptProjector
from ..agent.rows import clock_text, elapsed_text
from ..agent.runtime import describe_error
from ..agent.transcript import Transcript
from ..agent.usage import UsageSnapshot
from ..commands import Command, CommandContext, CommandList, CommandResult
from ..registry import Registry
from .commands import ShellCommands
from .keys import KeysMixin
from .notices import NoticesMixin
from .rows import RowsMixin
from .sessions import SessionMixin
from .settings import SettingsMixin
from .shell import MAX_STEERING, PAGE_SCREEN
from .updating import UpdateMixin
from .widgets import (
    WELCOME,
    CommandCompleter,
    Composer,
    SteeringQueue,
    TranscriptView,
    ZettCodeRoot,
)


class ZettCodeApp(RowsMixin, KeysMixin, NoticesMixin, SessionMixin, SettingsMixin, UpdateMixin):
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
        self.mentions = MentionRegistry(agent.plugin_mentions)
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
        self.view = TranscriptView(self.transcript, theme=theme)
        self.composer = Composer(
            prompt=f"{PROMPT} ",
            placeholder="Ask ZettCode to do anything",
            completer=CommandCompleter(self.commands, self.mentions),
            max_height=8,
            on_submit=self.submit,
            on_change=self._refresh_completions,
            surface=True,
        )
        self.completions = CompletionPopup(max_height=6)
        self.steering = SteeringQueue()
        self.header = StatusBar(self._header_left, self._header_right)
        self.status = StatusBar(self._status_left, self._status_right)
        self.panel = TaskPanel()

        body = VBox(
            [
                Slot(self.header, size=1),
                Slot(Rule(), size=1),
                Slot(self.view, flex=1),
                Slot(self.panel, size=lambda width: self.panel.preferred_height()),
                Slot(Text(""), size=1),
                Slot(self.completions, size=lambda available: self.completions.visible_height),
                Slot(self.steering, size=lambda width: self.steering.preferred_height()),
                Slot(self.composer, size=lambda width: self.composer.preferred_height(width)),
                Slot(self.status, size=1),
            ]
        )
        self.root = ZettCodeRoot(self, body)
        self.app = TuiApp(self.root, theme=theme, reduced_motion=agent.reduced_motion, auto_theme=auto_theme)
        # The terminal tab says what this session is about, like any editor tab.
        self.app.title = self._terminal_title
        self._task: asyncio.Task[None] | None = None
        self._title_task: asyncio.Task[None] | None = None
        #: The runtime warm-up this shell started, released on the way out.
        self._warm: asyncio.Task[object] | None = None
        self._busy = False
        self._steering: list[str] = []
        self._steering_sent = 0
        self._asks: list[AskUserQuestion] = []
        self._ask_total = 0
        #: Drafts typed while a request was in flight, in arrival order: only
        #: commands that declare ``when_busy="queue"`` land here.
        self._pending: list[str] = []
        self._activity = Activity.READY
        self._note: str | None = None
        self._auto_shell = False
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

    def start_background(self) -> None:
        """Begin the work that belongs behind the first frame.

        The runtime warms — its provider SDK costs a few hundred milliseconds —
        and the release check runs, nothing on screen waits for either, and the
        first turn awaits the same task. Called once the interface is up,
        whether :meth:`run` put it there or the command line painted a frame
        before this application existed.
        """
        self._warm = self.agent.runtime.start()
        self.start_update_check()
        self.offer_update()

    async def stop_background(self) -> None:
        """Release what :meth:`start_background` began."""
        await self._stop_title_task()
        await self._stop_update_task()
        warm, self._warm = self._warm, None
        if warm is not None:
            # A start that failed is the first turn's error to report, not a
            # reason to keep the process alive or to raise on the way out.
            await asyncio.gather(warm, return_exceptions=True)

    def adopt(self, tui: TuiApp) -> None:
        """Move this application's interface into a shell that is already running.

        The command line paints the composer through a ``TuiApp`` it owns, then
        hands that same app here: the tree, the keymap, the command registry,
        and the title move over, so the widgets built here drive the terminal
        that is already taken. The palette is left alone when this application
        lets the terminal choose it, because the runner has already adopted the
        one the terminal asked for.

        Args:
            tui: Running app whose placeholder this application replaces.
        """
        placeholder = self.app
        self.app = tui
        tui.commands = placeholder.commands
        tui.keymap = placeholder.keymap
        tui.title = self._terminal_title
        tui.reduced_motion = placeholder.reduced_motion
        tui.auto_theme = placeholder.auto_theme
        if not placeholder.auto_theme:
            tui.theme = placeholder.theme
        tui.set_root(self.root)

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
        context afterwards (see :mod:`zettcode.app.agent.side`). The side
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
        try:
            async with aclosing(
                cast("AsyncGenerator[AgentEvent]", self.agent.stream((question,), side=True))
            ) as events:
                async for _event in events:
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            self.transcript.notice("stopped the side question")
            raise
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.error(f"error: {describe_error(error)}")
        else:
            took = elapsed_text(monotonic() - started)
            self.transcript.notice(f"btw answered for {took} {SEPARATOR} {clock_text()}")
        finally:
            self.agent.runtime.sides.end()

    def _lookup(self, value: str) -> tuple[Command | None, str]:
        """Split a typed line into the command it names and its argument.

        The one place a draft is cut apart, so the composer, the router, and the
        queue all agree on what ``/name argument`` means. An unknown name answers
        ``None`` and the whole tail as the argument.
        """
        name, _, argument = value.partition(" ")
        return next((item for item in self.commands if item.name == name), None), argument.strip()

    def _queue_command(self, value: str) -> None:
        """Hold one typed command until the request in flight is done."""
        self._pending.append(value)
        self.transcript.notice(f"queued for after this request ({len(self._pending)} waiting)")
        self.app.invalidate()

    def _start_next_command(self) -> None:
        """Run the command that was typed while the finished request was busy."""
        if not self._pending or self._busy:
            return
        self._task = asyncio.create_task(self._run_command(self._pending.pop(0)))

    def submit(self, value: str) -> bool | None:
        """Start a turn or a slash command, steering while one is running.

        Plain text typed during a turn is not refused: it is queued as a
        steering message, which the agent adopts at its next model or tool
        boundary and which the queue widget shows until then. A slash command is
        refused while one runs, because there is no running request to steer —
        unless the command itself declares ``when_busy="queue"``, which holds the
        draft and runs it the moment the request in flight ends.

        Args:
            value: Draft text from the composer; a leading ``/`` selects the
                slash-command branch.

        Returns:
            False when the draft was refused; returning a true value also
            clears the composer.
        """
        if self._busy:
            if value.startswith("/"):
                # Which commands are taken mid-request is the command's own
                # decision, not a name the shell knows: a queued one runs the
                # moment the request in flight ends.
                command, _ = self._lookup(value)
                if command is None or command.when_busy == "refuse":
                    self._refuse_busy()
                    return False
                self._queue_command(value)
                return True
            if not value.strip():
                self._refuse_busy()
                return False
            if self._side_question_running:
                # Steering folds into the running request, and a side question's
                # messages are recorded but never replayed — so a steered message
                # sent now would disappear from the conversation. The draft is
                # left in the composer instead.
                self.transcript.notice("a btw question is being answered; send that when it finishes")
                self.app.invalidate()
                return False
            if carries_image(self.composer.parts()):
                self.transcript.error("steering takes text only")
                self.app.invalidate()
                return False
            if self._steering_sent >= MAX_STEERING:
                self.transcript.error(f"steering limit reached ({MAX_STEERING}) \u2014 wait for this reply")
                self.app.invalidate()
                return False
            if self.agent.steer(value):
                self._queue_steering(value)
                return True
            self._refuse_busy()
            return False
        if value.startswith("/"):
            self._task = asyncio.create_task(self._run_command(value))
        else:
            # The parts are taken before the composer is cleared, and keep the
            # order the chips sit in, so text and pictures stay interleaved.
            parts = self.composer.parts()
            if carries_image(parts) and not self.agent.active_model.multimodal:
                # A pasted base64 image reaches the composer without the shell
                # having seen the clipboard, so the model's own limits are
                # checked again here rather than only when Ctrl-V runs.
                self.transcript.error(f"{self.agent.active_model.shown_name} does not take images")
                self.app.invalidate()
                return False
            self._task = asyncio.create_task(self._run_prompt(value, parts, mention_hint(parts, self.mentions)))
        return True

    @property
    def _side_question_running(self) -> bool:
        """Return whether the request in flight is a side question."""
        task = self._task
        return bool(task is not None and not task.done() and self.agent.runtime.sides.pending)

    def _queue_steering(self, value: str) -> None:
        """Show one message waiting for the agent to adopt it."""
        self._steering.append(value)
        self._steering_sent += 1
        self.steering.set_messages(self._steering)
        self.app.request_layout()
        self.app.invalidate()

    def _refuse_busy(self) -> None:
        """Tell the reader a draft cannot be taken while a request runs."""
        self.transcript.notice("busy \u2014 Ctrl-C stops the current request")
        self.app.invalidate()

    def _clear_steering(self) -> None:
        """Drop the queue, for instance when the turn it belonged to ended."""
        self._steering_sent = 0
        if not self._steering:
            return
        self._steering.clear()
        self.steering.set_messages(())
        self.app.request_layout()

    def _steering_started(self, text: str) -> None:
        """Drop a message the agent just adopted; the projector echoes its row."""
        if text in self._steering:
            self._steering.remove(text)
            self.steering.set_messages(self._steering)
            self.app.request_layout()
        self.app.invalidate()

    def _steering_interrupted(self, text: str) -> None:
        """Drop a queued message a newer steering message superseded."""
        if text in self._steering:
            self._steering.remove(text)
            self.steering.set_messages(self._steering)
            self.app.request_layout()
        self.app.invalidate()

    async def _run_prompt(self, prompt: str, parts: Sequence[PromptPart] = (), hint: str | None = None) -> None:
        """Stream one agent turn, keeping the task panel and transcript current.

        Args:
            prompt: What the user typed, image chips included, as it is echoed
                into the transcript.
            parts: The same turn as ordered text and image parts; an empty
                sequence falls back to the prompt alone.
            hint: Instructions the draft's ``@`` references contribute; the
                stored message keeps ``prompt``.
        """
        self.projector.begin_turn(prompt)
        started = monotonic()
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
            stream = self.agent.stream(turn) if hint is None else self.agent.stream(turn, hint=hint)
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
            self._title_session_later(self.agent.session_id)
        finally:
            took = elapsed_text(monotonic() - started)
            self.transcript.notice(f"Processed for {took} {SEPARATOR} {clock_text()}")
            self._drop_ask()
            self._clear_steering()
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
        self.app.scheduler.animate("activity", active=busy)

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
                        self._usage = self.agent.usage
                        self._refresh_tasks()
                        self.app.request_layout()
                except ValueError as error:
                    self.transcript.error(str(error))
                else:
                    self._apply_result(result)
        finally:
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
