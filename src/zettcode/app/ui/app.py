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

from ...config import DEFAULT_LOG, ModelConfig
from ...plugins import (
    Activity,
    ActivityState,
    DisplayState,
    ModelState,
    SessionState,
    ShellContext,
    UiRegion,
    UiRow,
    UiSide,
)
from ...tui import (
    DARK,
    ELLIPSIS,
    PROMPT,
    SEPARATOR,
    Anchor,
    AnyEvent,
    CompletionPopup,
    Host,
    Overlay,
    OverlaySlot,
    Screen,
    Span,
    StatusBar,
    Style,
    TaskPanel,
    TextLine,
    Theme,
    Toast,
    TuiApp,
    VBox,
    theme_named,
)
from ...tui.layout import Slot
from ...tui.widgets import Rule, Text

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator
from ..agent.agent import UNTITLED_SESSION, PromptPart, ZettCodeAgent, carries_image, mention_hint
from ..agent.mentions import MentionRegistry
from ..agent.projection import TranscriptProjector
from ..agent.rows import clock_text, elapsed_text
from ..agent.runtime import describe_error
from ..agent.transcript import Transcript
from ..agent.usage import UsageSnapshot
from ..commands import CommandList, CommandResult
from ..registry import Registry
from .clipboard import read_image
from .commands import ShellCommands
from .widgets import (
    WELCOME,
    ApprovalChoice,
    ApprovalPage,
    CommandCompleter,
    Composer,
    SteeringQueue,
    TranscriptView,
    ZettCodeRoot,
    bottom_panel,
)

#: Screen name used for a page a command presented; the shell checks it to know
#: that Ctrl-C and Ctrl-D belong to the page rather than the composer.
PAGE_SCREEN = "page"

#: Rows the approval panel takes from the bottom of the screen: the question,
#: up to three lines of command, and the numbered choices.
APPROVAL_ROWS = 16

#: Steering messages one run accepts. The agent's inbox is unbounded, so the
#: shell is what stops a reader from queueing more urgents than the run can
#: reasonably answer; the count resets when a new run starts.
MAX_STEERING = 8


class ZettCodeApp:
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
        self._busy = False
        self._steering: list[str] = []
        self._steering_sent = 0
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
        waits for it, and the first turn awaits the same task.
        """
        from ...tui import Terminal, TerminalRunner

        warm = self.agent.runtime.start()
        try:
            await TerminalRunner(self.app, terminal=Terminal(diagnostics=DEFAULT_LOG)).run()
        finally:
            await self._stop_title_task()
            # A start that failed is the first turn's error to report, not a
            # reason to keep the process alive or to raise on the way out.
            await asyncio.gather(warm, return_exceptions=True)

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
    def _install_keymap(self) -> None:
        """Register the global commands and their key bindings."""
        self.app.commands.add("interrupt", self._interrupt)
        self.app.commands.add("redraw", self._redraw)
        self.app.commands.add("toggle_thinking", self._toggle_thinking)
        self.app.commands.add("scroll_up", self._scroll_up)
        self.app.commands.add("scroll_down", self._scroll_down)
        self.app.commands.add("scroll_end", self._scroll_end)
        self.app.commands.add("attach_image", self._attach_image)
        self.app.commands.add("quit", self._quit)
        self.app.commands.add("complete_next", self._complete_next)
        self.app.commands.add("complete_previous", self._complete_previous)
        self.app.commands.add("complete_accept", self._complete_accept)
        self.app.commands.add("complete_dismiss", self._complete_dismiss)
        self.app.keymap.bind("ctrl_c", "interrupt", priority="capture")
        self.app.keymap.bind("ctrl_l", "redraw", priority="capture")
        self.app.keymap.bind("ctrl_t", "toggle_thinking", priority="capture")
        # Capture priority is what lets the predicate win: the composer would
        # otherwise swallow Ctrl-D as "delete forward" even on an empty draft.
        self.app.keymap.bind(
            "ctrl_d",
            "quit",
            priority="capture",
            when=lambda: self.app.screens.top.name != PAGE_SCREEN and not self._busy and not self.composer.text,
        )
        self.app.keymap.bind("page_up", "scroll_up")
        self.app.keymap.bind("page_down", "scroll_down")
        # Escape is the keyboard twin of the transcript's return badge; capture
        # priority lets it win, because the composer would otherwise swallow Esc.
        self.app.keymap.bind("escape", "scroll_end", priority="capture", when=self._transcript_scrolled_up)
        # The terminal cannot deliver a pasted image, so this asks the desktop.
        self.app.keymap.bind("ctrl_v", "attach_image", priority="capture")
        # Capture priority is what lets the menu win the keys it needs: the
        # composer would otherwise read Up and Down as history navigation and
        # would treat Tab as its own inline completion.
        self.app.keymap.bind("down", "complete_next", priority="capture", when=self._menu_open)
        self.app.keymap.bind("up", "complete_previous", priority="capture", when=self._menu_open)
        self.app.keymap.bind("tab", "complete_accept", priority="capture", when=self._menu_open)
        self.app.keymap.bind("escape", "complete_dismiss", priority="capture", when=self._menu_open)
        self.app.keymap.bind("enter", "complete_accept", priority="capture", when=self._accept_on_enter)

    def _menu_open(self) -> bool:
        """Return whether the slash-command menu is showing."""
        return self.app.screens.top.name != PAGE_SCREEN and self.completions.visible

    def _transcript_scrolled_up(self) -> bool:
        """Return whether Escape should jump the conversation back to its tail."""
        return self.app.screens.top.name != PAGE_SCREEN and self.view.scrolled_up

    def _scroll_end(self, event: AnyEvent, host: Host) -> bool:
        """Follow the newest line again, as the transcript's return badge does."""
        self.view.scroll_end()
        return True

    def _redraw(self, event: AnyEvent, host: Host) -> bool:
        """Repaint the frame, for a terminal that lost its contents."""
        host.refresh()
        return True

    def _scroll_up(self, event: AnyEvent, host: Host) -> bool:
        """Move the transcript one page toward older lines."""
        self.view.scroll_by(-3)
        return True

    def _scroll_down(self, event: AnyEvent, host: Host) -> bool:
        """Move the transcript one page toward newer lines."""
        self.view.scroll_by(3)
        return True

    def _quit(self, event: AnyEvent, host: Host) -> bool:
        """Leave the application."""
        host.exit()
        return True

    def _attach_image(self, event: AnyEvent, host: Host) -> bool:
        """Attach the clipboard's image to the draft, or say there is none.

        Ctrl-V rather than the terminal's paste key: an image never reaches the
        program as input, so the shell has to go and look for it.
        """
        image = read_image()
        if image is None:
            self.transcript.notice("no image on the clipboard")
        elif not self.agent.active_model.multimodal:
            self.transcript.error(f"{self.agent.active_model.shown_name} does not take images")
        else:
            label = self.composer.attach_image(*image)
            self._note = f"attached {label}"
        host.request_layout()
        return True

    def _accept_on_enter(self) -> bool:
        """Return whether Enter should complete the draft instead of running it.

        Completing is only useful while the highlighted command differs from
        what was typed; once the draft already spells it, Enter runs it instead
        of filling in the same text twice.
        """
        item = self.completions.current
        return item is not None and item.value != self.composer.text.strip()

    def _refresh_completions(self) -> None:
        """Mirror the composer's slash-command candidates into the menu."""
        candidates = self.composer.completion_candidates()
        if candidates == self.completions.items:
            return
        self.completions.set_items(candidates, selected=0)
        self.app.request_layout()

    def _complete_next(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the next command."""
        self.completions.move(1)
        host.invalidate()
        return True

    def _complete_previous(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the previous command."""
        self.completions.move(-1)
        host.invalidate()
        return True

    def _complete_accept(self, event: AnyEvent, host: Host) -> bool:
        """Drop the highlighted command into the composer and close the menu."""
        item = self.completions.current
        if item is None:
            return False
        # The trailing space is what closes the menu: the draft is no longer a
        # bare command token, so the next Enter runs the command.
        self.composer.replace_token(item.value, suffix=" ")
        host.request_layout()
        return True

    def _complete_dismiss(self, event: AnyEvent, host: Host) -> bool:
        """Hide the menu until the draft changes again."""
        self.completions.set_items(())
        host.request_layout()
        return True

    def _interrupt(self, event: AnyEvent, host: Host) -> bool:
        """Copy a selection, otherwise stop the running turn or clear the draft."""
        selected = self.view.selected_text() or host.screen_selection_text()
        if selected:
            host.copy(selected)
            self.view.clear_selection()
            host.clear_screen_selection()
            self._note = f"copied {len(selected)} characters"
            host.invalidate()
            return True
        if self.app.screens.top.name == PAGE_SCREEN:
            self.close_page()
            host.invalidate()
            return True
        if self._busy and self._task is not None and not self._task.done():
            self._task.cancel()
        elif self.composer.text:
            self.composer.clear()
        host.invalidate()
        return True

    def _toggle_thinking(self, event: AnyEvent, host: Host) -> bool:
        """Show or hide the newest reasoning block."""
        if self.transcript.toggle_latest_thinking():
            host.invalidate()
        return True

    def submit(self, value: str) -> bool | None:
        """Start a turn or a slash command, steering while one is running.

        Plain text typed during a turn is not refused: it is queued as a
        steering message, which the agent adopts at its next model or tool
        boundary and which the queue widget shows until then. A slash command
        still waits, because there is no running request to steer.

        Args:
            value: Draft text from the composer; a leading ``/`` selects the
                slash-command branch.

        Returns:
            False when the draft was refused; returning a true value also
            clears the composer.
        """
        if self._busy:
            if value.startswith("/") or not value.strip():
                self._refuse_busy()
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
            self._clear_steering()
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self._refresh_tasks()
            self.app.invalidate()

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
        name, _, argument = value.partition(" ")
        argument = argument.strip()
        self._activity = Activity.RUNNING
        self._note = f"{name} {ELLIPSIS}"
        # A command may take a while — `/compact` summarizes the conversation —
        # so it holds the same busy flag a turn does: the status glyph spins,
        # another submit is refused, and Ctrl-C cancels what is running.
        self._set_busy(True)
        self.app.invalidate()
        try:
            previous_session = self.agent.session_id
            command = next((item for item in self.commands if item.name == name), None)
            if command is None:
                self.transcript.error(f"Unknown command: {name}. Try /help.")
            else:
                try:
                    result = await command.handler(argument)
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

    def _apply_result(self, result: CommandResult) -> None:
        """Show what a command returned: Markdown, a toast, a widget, a re-layout.

        The order mirrors how the screen stack paints: transcript content and
        the toast go up first, then the widget is stacked on top of them, and
        the re-layout happens last so it measures what was actually added.
        """
        if result.message:
            self.transcript.markdown(result.message)
        if result.notification:
            self._notify(result.notification, level="success")
        if result.widget is not None:
            self.app.push_screen(Screen(result.widget, name=PAGE_SCREEN, modal=True))
        if result.relayout:
            self.app.request_layout()

    def close_page(self) -> None:
        """Return to the composer, restoring its focus and layout."""
        self.app.pop_screen()
        self.app.request_layout()

    def select_model(self, name: ModelConfig) -> None:
        """Apply the highlighted model and return to the composer."""
        try:
            self.change_model(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()

    def change_model(self, name: ModelConfig | str) -> ModelConfig:
        """Switch models and announce the change in the transcript."""
        previous = self.agent.active_model
        selected = self.agent.use_model(name)
        if selected is not previous:
            self.transcript.model_changed(previous.shown_name, selected.shown_name)
        self.app.request_layout()
        return selected

    def select_theme(self, name: str) -> None:
        """Apply the palette picked in the panel and return to the composer."""
        try:
            self.apply_theme(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()

    async def rename_session(self, title: str) -> str:
        """Name the active session and show it in the status line.

        Args:
            title: Name the user typed; the store rejects a blank or over-long
                one, which the command turns into a notice.

        Returns:
            The stored title, so the command can confirm it.
        """
        renamed = await self.agent.rename_session(title)
        self._session_title = renamed
        self.app.invalidate()
        return renamed

    def select_effort(self, name: str) -> None:
        """Apply the reasoning level picked in the panel and return to the composer."""
        try:
            self.change_effort(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()
        self.app.request_layout()

    def change_effort(self, name: str) -> str:
        """Switch reasoning effort and announce the change in the transcript."""
        previous = self.agent.effort
        selected = self.agent.use_effort(name)
        if selected != previous:
            self.transcript.effort_changed(previous, selected)
        return selected

    def apply_theme(self, name: str) -> Theme:
        """Switch the palette and repaint.

        Widgets read ``theme`` while painting, so nothing has to be rebuilt;
        the invalidate is what makes the new colours land, and the re-layout
        covers the caches a size-only change would have missed.
        """
        theme = theme_named(name)
        self.app.theme = theme
        self.app.request_layout()
        return theme

    def select_session(self, session_id: str) -> None:
        """Switch to the session picked in the panel and return to the composer."""
        try:
            self.restore_session(session_id)
        except ValueError as error:
            self.transcript.error(str(error))
            self.close_page()
            return
        # Close the panel first: the toast is its own screen, and closing it
        # instead of the panel would leave the picker on top.
        self.close_page()
        self._notify(f"using session {session_id[:8]}", level="success")

    def restore_session(self, session_id: str) -> None:
        """Replace the visible history with the chosen persisted branch."""
        self.agent.restore_session(session_id, self.transcript)
        if not self.transcript.entries:
            self.transcript.welcome(WELCOME)
        self.view.follow_tail = True
        self.view.clear_selection()
        self._remember_session_title()
        self._usage = self.agent.usage
        self._refresh_tasks()
        self.app.request_layout()

    def _usage_updated(self, event: AgentEvent) -> None:
        """Mirror the usage extension's cumulative counters into the status line."""
        self._usage = UsageSnapshot.from_payload(event.payload or {})
        self.app.invalidate()

    # -- titles -------------------------------------------------------------
    def _remember_session_title(self) -> None:
        """Cache the active session's title, which the status line paints per frame."""
        self._session_title = self.agent.session_title

    def _title_session_later(self, session_id: str) -> None:
        """Ask the agent to name a session once, off the composer's critical path."""
        if self._title_task is not None and not self._title_task.done():
            return
        self._title_task = asyncio.create_task(self._name_session(session_id))

    async def _name_session(self, session_id: str) -> None:
        """Store the title the agent summarizes and show it in the status line."""
        try:
            title = await self.agent.title_session(session_id)
        except Exception:
            return  # naming a session is a nicety; never report its failure
        if title is None:
            return
        if session_id == self.agent.session_id:
            self._session_title = title
            self.app.invalidate()

    async def _stop_title_task(self) -> None:
        """Stop a title request that is still in flight when the app exits."""
        if self._title_task is None or self._title_task.done():
            return
        self._title_task.cancel()
        await asyncio.gather(self._title_task, return_exceptions=True)

    # -- approvals ----------------------------------------------------------
    def _approval_requested(self, event: AgentEvent) -> None:
        """Show the approval panel for one pending shell command.

        The panel is an :class:`ApprovalPage` in a bottom strip: the question,
        the command with its shell highlighting, and the numbered choices, so
        the transcript above stays readable while the command is reviewed.
        """
        payload = event.payload if isinstance(event.payload, dict) else {}
        call_id = str(payload.get("tool_call_id", ""))
        session_id = str(payload.get("session_id") or self.agent.session_id)
        command = str(payload.get("command", ""))
        page = ApprovalPage(
            command,
            on_choice=lambda choice: self._respond(session_id, call_id, choice),
            remember_supported=bool(payload.get("remember_supported")),
        )
        panel = bottom_panel(page, rows=APPROVAL_ROWS)
        self.app.push_screen(Screen(panel, name=PAGE_SCREEN, modal=True))

    def _respond(self, session_id: str, call_id: str, choice: ApprovalChoice) -> None:
        """Dismiss the panel and answer the suspended agent run.

        Args:
            session_id: Session the approval belongs to, echoed back to the agent.
            call_id: Tool call the decision applies to.
            choice: What the user picked; ``auto`` also silences every later
                request this run.
        """
        decision = "abort" if choice is ApprovalChoice.ABORT else "execute"
        remember = choice is ApprovalChoice.ALWAYS
        self.close_page()
        try:
            self.agent.respond_approval(session_id, call_id, decision, remember)
        except Exception as error:
            self.transcript.error(f"approval failed: {error}")
        else:
            if choice is ApprovalChoice.RUN_AUTO:
                self.agent.approve_all_shell_commands()
                self._auto_shell = True
                self.transcript.notice("auto mode on: approving every shell command this run")
        self.app.invalidate()

    # -- notifications ------------------------------------------------------
    def _notify(self, message: str, *, level: str = "info") -> None:
        """Show a toast, replacing any toast that is still on screen.

        Args:
            message: Text shown in the toast.
            level: Colour key understood by ``Toast``.
        """
        while len(self.app.screens) > 1 and self.app.screens.top.name == "toast":
            self.app.pop_screen()
        toast = Toast(message, level=level, duration=2)
        overlay = Overlay([OverlaySlot(toast, Anchor(horizontal="end", vertical="end", offset_x=-1, offset_y=-1))])
        # A paint-only layer: the toast shows over the shell but must not take
        # input, or scrolling the transcript under it would stop working.
        self.app.push_screen(Screen(overlay, name="toast", interactive=False))

    # -- rows ---------------------------------------------------------------
    def _terminal_title(self) -> str:
        """Return what the terminal's window or tab should say this is."""
        return self._session_title or f"zettcode {SEPARATOR} {self.agent.workspace.name}"

    def _header_left(self) -> TextLine:
        """Return the header's left side, whatever the plugins put there."""
        return self._side("header", "left")

    def _header_right(self) -> TextLine:
        """Return the header's right side, whatever the plugins put there."""
        return self._side("header", "right")

    def _status_left(self) -> TextLine:
        """Return the status line's left side, whatever the plugins put there."""
        return self._side("status", "left")

    def _status_right(self) -> TextLine:
        """Return the status line's right side, whatever the plugins put there."""
        return self._side("status", "right")

    def _side(self, region: UiRegion, side: UiSide) -> TextLine:
        """Paint one side of one row from the segments the plugins registered.

        The shell owns only this loop: the builtin rows are a plugin like any
        other, and a plugin that overrode one of its slots already sits in its
        place. A segment that returns nothing is skipped, one that raises is
        dropped for that frame only, and one that returns ``(line, True)`` takes
        the side over — the segments painted before it are dropped.
        """
        row = next((row for row in self._plugin_rows if row.region == region), None)
        segments = () if row is None else (row.left if side == "left" else row.right)
        style = Style(foreground=self.app.theme.muted)
        spans: list[Span] = []
        context: ShellContext | None = None
        for segment in segments:
            if context is None:
                context = self._shell_context()
            try:
                value = segment.builder(context)
            except Exception:
                continue
            overrides = False
            if isinstance(value, tuple):
                value, overrides = value
            line = value if isinstance(value, TextLine) else TextLine((Span(str(value)),)) if value else None
            if overrides:
                spans.clear()
            if line is None or not line.width:
                continue
            if spans:
                spans.append(Span(f" {SEPARATOR} ", style))
            spans.extend(line.spans)
        return TextLine(tuple(spans))

    def _shell_context(self) -> ShellContext:
        """Snapshot what a plugin's segment builder reads, rebuilt for one paint."""
        return ShellContext(
            config=self.agent.runtime.config,
            session=SessionState(
                id=self.agent.session_id,
                title=self._session_title,
                name=self._session_title or UNTITLED_SESSION,
                workspace=self.agent.workspace,
            ),
            model=ModelState(
                config=self.agent.active_model,
                name=self.agent.active_model.shown_name,
                effort=self.agent.effort,
                efforts=self.agent.efforts,
            ),
            activity=ActivityState(
                busy=self._busy,
                status=self._activity,
                note=self._note,
                auto_shell=self._auto_shell,
                usage=self._usage,
                tasks=self.agent.tasks(),
                frame=self.transcript.frame,
            ),
            display=DisplayState(
                theme=self.app.theme,
                width=self.app.width,
                height=self.app.height,
                screen=self.app.screens.top.name,
                scrolled_up=self.view.scrolled_up,
            ),
        )
