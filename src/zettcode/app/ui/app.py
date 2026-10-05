"""The ZettCode application shell: the controller behind the terminal UI.

It owns the agent, the widget tree, the keymap, and the slash commands, and it
is the only place that decides what a command result looks like on screen. The
widgets themselves live in :mod:`zettcode.app.ui.widgets`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import aclosing
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, cast

from zett_agent.events import AgentEvent

from ...config import DEFAULT_LOG, ModelConfig
from ...tui import (
    DARK,
    ELLIPSIS,
    HEADER,
    PROMPT,
    SEPARATOR,
    STATUS,
    Anchor,
    AnyEvent,
    CompletionPopup,
    Host,
    Overlay,
    OverlaySlot,
    Screen,
    StatusBar,
    TaskPanel,
    Theme,
    Toast,
    TuiApp,
    VBox,
    theme_named,
)
from ...tui.layout import Slot
from ...tui.render import display_width
from ...tui.widgets import Rule, Text

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator

from ..agent.agent import UNTITLED_SESSION, PromptPart, ZettCodeAgent
from ..agent.projection import TranscriptProjector
from ..agent.rows import activity_glyph, clock_text, elapsed_text
from ..agent.runtime import describe_error
from ..agent.transcript import Transcript
from ..agent.usage import UsageSnapshot, usage_text
from ..commands import CommandResult
from .clipboard import read_image
from .commands import ShellCommands
from .widgets import (
    WELCOME,
    ApprovalChoice,
    ApprovalPage,
    CommandCompleter,
    Composer,
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
        self.transcript = Transcript()
        self.transcript.welcome(WELCOME)
        self.projector = TranscriptProjector(
            self.transcript,
            on_approval=self._approval_requested,
            on_usage=self._usage_updated,
        )
        self.agent.set_event_dispatcher(self.projector)
        self.commands = ShellCommands(self).build(agent.commands)

        self.view = TranscriptView(self.transcript, theme=theme)
        self.composer = Composer(
            prompt=f"{PROMPT} ",
            placeholder="Ask ZettCode to do anything",
            completer=CommandCompleter(self.commands),
            max_height=8,
            on_submit=self.submit,
            on_change=self._refresh_completions,
            surface=True,
        )
        self.completions = CompletionPopup(max_height=6)
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
        self._status = "ready"
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
            self._status = f"attached {label}"
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
        self.composer.set_text(f"{item.value} ")
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
            self._status = f"copied {len(selected)} characters"
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
        """Start a turn or a slash command, refusing while one is running.

        Args:
            value: Draft text from the composer; a leading ``/`` selects the
                slash-command branch.

        Returns:
            False when the draft was refused because a request is in flight;
            returning a true value also clears the composer.
        """
        if self._busy:
            self.transcript.notice("busy \u2014 Ctrl-C stops the current request")
            self.app.invalidate()
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
            self._task = asyncio.create_task(self._run_prompt(value, parts))
        return True

    async def _run_prompt(self, prompt: str, parts: Sequence[PromptPart] = ()) -> None:
        """Stream one agent turn, keeping the task panel and transcript current.

        Args:
            prompt: What the user typed, image chips included, as it is echoed
                into the transcript.
            parts: The same turn as ordered text and image parts; an empty
                sequence falls back to the prompt alone.
        """
        self.projector.begin_turn(prompt)
        started = monotonic()
        self._set_busy(True)
        self._status = "running"
        self.app.invalidate()
        try:
            self._refresh_tasks()
            # The agent's stream is an async generator; the cast lets aclosing
            # close it when the turn is cancelled.
            stream = cast("AsyncGenerator[AgentEvent]", self.agent.stream(parts or (prompt,)))
            async with aclosing(stream) as events:
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
            self._set_busy(False)
            self._status = "ready"
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
        self._status = f"{name} {ELLIPSIS}"
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
                    if name == "/use" and self.agent.session_id != previous_session:
                        self.restore_session(self.agent.session_id)
                    elif name == "/new" and self.agent.session_id != previous_session:
                        self.transcript.clear()
                        self.transcript.welcome(WELCOME)
                        self.view.scroll_end()
                        self.view.clear_selection()
                        self._remember_session_title()
                        self._usage = self.agent.usage
                        self._refresh_tasks()
                        self.app.request_layout()
                except ValueError as error:
                    if name == "/use" and self.agent.session_id != previous_session:
                        self.agent.use_session(previous_session)
                    self.transcript.error(str(error))
                else:
                    self._apply_result(result)
        finally:
            self._set_busy(False)
            self._status = "ready"
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
        toast = Toast(message, level=level, duration=2.5)
        overlay = Overlay([OverlaySlot(toast, Anchor(horizontal="end", vertical="end", offset_x=-1, offset_y=-1))])
        self.app.push_screen(Screen(overlay, name="toast"))

    # -- chrome -------------------------------------------------------------
    def _terminal_title(self) -> str:
        """Return what the terminal's window or tab should say this is."""
        return self._session_title or f"zettcode {SEPARATOR} {self.agent.workspace.name}"

    def _header_left(self) -> str:
        """Label the app and the workspace it is running in."""
        return f"  {HEADER} zettcode  {compact_path(self.agent.workspace)}"

    def _header_right(self) -> str:
        """Show the model and the reasoning effort the next request will use."""
        return f"{self.agent.active_model.shown_name} {SEPARATOR} {self.agent.effort}  "

    def _status_left(self) -> str:
        """Show the activity glyph, status word, mode, session title, and token use."""
        icon = activity_glyph(self.transcript.frame) if self._busy else STATUS
        # The mode sits before the title because the right-hand hint wins
        # the space fight, truncating the tail of this segment.
        mode = f" {SEPARATOR} auto" if self._auto_shell else ""
        title = f"  {self._session_title or UNTITLED_SESSION}"
        return f"  {icon} {self._status}{mode}{title}{usage_text(self._usage)}"

    def _status_right(self) -> str:
        """List the keys worth remembering while the composer has focus."""
        return "  ^C stop  ^T thinking  ^D exit  "


def carries_image(parts: Sequence[PromptPart]) -> bool:
    """Return whether one turn holds an image beside its text."""
    return any(not isinstance(part, str) for part in parts)


def compact_path(path: Path, *, limit: int = 38) -> str:
    """Shorten a workspace path for the header.

    Args:
        path: Absolute path to display.
        limit: Most columns to keep; the home directory collapses to ``~``, and
            anything longer keeps a leading ellipsis plus its tail. The budget
            counts display columns, so a path with wide characters is measured
            the way the header draws it.
    """
    value = str(path)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        value = "~" + value[len(home) :]
    width = display_width(value)
    if width <= limit:
        return value
    # Count the tail from the end so a wide glyph is dropped whole rather than
    # overhanging the budget, which the ellipsis also has to fit inside.
    budget = limit - 1
    tail = ""
    for character in reversed(value):
        if display_width(character) > budget:
            break
        tail = character + tail
        budget -= display_width(character)
    return ELLIPSIS + tail
