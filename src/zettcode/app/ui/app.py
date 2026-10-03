"""The ZettCode application shell: the controller behind the terminal UI.

It owns the agent, the widget tree, the keymap, and the slash commands, and it
is the only place that decides what a command result looks like on screen. The
widgets themselves live in :mod:`zettcode.app.ui.widgets`.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from pathlib import Path
from time import monotonic

from zett_agent import AgentEvent

from ...config import ModelConfig
from ...tui import (
    DARK,
    Anchor,
    CompletionPopup,
    Host,
    KeyEvent,
    Overlay,
    OverlaySlot,
    Screen,
    StatusBar,
    TaskPanel,
    TextArea,
    Theme,
    Toast,
    TuiApp,
    VBox,
)
from ...tui.layout import Slot
from ...tui.render import display_width
from ...tui.widgets import Rule
from ..agent.agent import ZettCodeAgent
from ..agent.projection import TranscriptProjector
from ..agent.transcript import Transcript, activity_glyph, clock_text, elapsed_text
from ..commands import CommandResult
from .commands import ShellCommands
from .widgets import WELCOME, ApprovalChoice, ApprovalPage, CommandCompleter, TranscriptView, ZettCodeRoot, bottom_panel

#: Screen name used for a page a command presented; the shell checks it to know
#: that Ctrl-C and Ctrl-D belong to the page rather than the composer.
PAGE_SCREEN = "page"

#: Rows the approval panel takes from the bottom of the screen: the question,
#: up to three lines of command, and the numbered choices.
APPROVAL_ROWS = 16


class ZettCodeApp:
    """Own the application agent, widget tree, keymap, and slash commands."""

    def __init__(self, agent: ZettCodeAgent, *, theme: Theme = DARK) -> None:
        """Wire the agent into the transcript, composer, panel, and keymap.

        Args:
            agent: Application agent that owns turns, sessions, and models.
            theme: Initial palette; ``/theme`` replaces it at runtime.
        """
        self.agent = agent
        self.transcript = Transcript()
        self.transcript.welcome(WELCOME)
        self.projector = TranscriptProjector(self.transcript, on_approval=self._approval_requested)
        self.agent.set_event_dispatcher(self.projector)
        self.commands = ShellCommands(self).build(agent.commands)

        self.view = TranscriptView(self.transcript, theme=theme)
        self.composer = TextArea(
            prompt="\u203a ",
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
                Slot(Rule(), size=1),
                Slot(self.completions, size=lambda available: self.completions.visible_height),
                Slot(self.composer, size=lambda width: self.composer.preferred_height(width)),
                Slot(self.status, size=1),
            ]
        )
        self.root = ZettCodeRoot(self, body)
        self.app = TuiApp(self.root, theme=theme, reduced_motion=agent.reduced_motion)
        self._task: asyncio.Task[None] | None = None
        self._title_task: asyncio.Task[None] | None = None
        self._busy = False
        self._status = "ready"
        self._auto_shell = False
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
        """Own the terminal until the application exits."""
        from ...tui import TerminalRunner

        try:
            await TerminalRunner(self.app).run()
        finally:
            await self._stop_title_task()

    # -- commands -----------------------------------------------------------
    def _install_keymap(self) -> None:
        """Register the global commands and their key bindings."""
        self.app.commands.add("interrupt", self._interrupt)
        self.app.commands.add("redraw", lambda event, host: (host.refresh(), True)[1])
        self.app.commands.add("toggle_thinking", self._toggle_thinking)
        self.app.commands.add("scroll_up", lambda event, host: (self.view.scroll_by(-3), True)[1])
        self.app.commands.add("scroll_down", lambda event, host: (self.view.scroll_by(3), True)[1])
        self.app.commands.add("quit", lambda event, host: (host.exit(), True)[1])
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

    def _complete_next(self, event: KeyEvent, host: Host) -> bool:
        """Highlight the next command."""
        self.completions.move(1)
        host.invalidate()
        return True

    def _complete_previous(self, event: KeyEvent, host: Host) -> bool:
        """Highlight the previous command."""
        self.completions.move(-1)
        host.invalidate()
        return True

    def _complete_accept(self, event: KeyEvent, host: Host) -> bool:
        """Drop the highlighted command into the composer and close the menu."""
        item = self.completions.current
        if item is None:
            return False
        # The trailing space is what closes the menu: the draft is no longer a
        # bare command token, so the next Enter runs the command.
        self.composer.set_text(f"{item.value} ")
        host.request_layout()
        return True

    def _complete_dismiss(self, event: KeyEvent, host: Host) -> bool:
        """Hide the menu until the draft changes again."""
        self.completions.set_items(())
        host.request_layout()
        return True

    def _interrupt(self, event: KeyEvent, host: Host) -> bool:
        """Copy a selection, otherwise stop the running turn or clear the draft."""
        if self.app.screens.top.name == PAGE_SCREEN:
            self.close_page()
            host.invalidate()
            return True
        selected = self.view.selected_text()
        if selected:
            host.copy(selected)
            self.view.clear_selection()
            self._status = f"copied {len(selected)} characters"
            host.invalidate()
            return True
        if self._busy and self._task is not None and not self._task.done():
            self._task.cancel()
        elif self.composer.text:
            self.composer.clear()
        host.invalidate()
        return True

    def _toggle_thinking(self, event: KeyEvent, host: Host) -> bool:
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
            self._task = asyncio.create_task(self._run_prompt(value))
        return True

    async def _run_prompt(self, prompt: str) -> None:
        """Stream one agent turn, keeping the task panel and transcript current."""
        self.projector.begin_turn(prompt)
        started = monotonic()
        self._busy = True
        self._status = "running"
        self.app.scheduler.animate("stream")
        self.app.invalidate()
        try:
            self._refresh_tasks()
            async with aclosing(self.agent.stream(prompt)) as events:
                async for _event in events:
                    self._refresh_tasks()
                    self.app.invalidate()
        except asyncio.CancelledError:
            self.transcript.complete_thinking()
            self.transcript.notice("stopped")
        except Exception as error:
            self.transcript.complete_thinking()
            self.transcript.notice(f"error: {error}")
        else:
            self._title_session_later(self.agent.session_id)
        finally:
            took = elapsed_text(monotonic() - started)
            self.transcript.notice(f"Processed {took} \u00b7 {clock_text()}")
            self._busy = False
            self._status = "ready"
            self.app.scheduler.animate("stream", active=False)
            self._refresh_tasks()
            self.app.invalidate()

    def _refresh_tasks(self) -> None:
        """Mirror the agent's current plan into the panel above the composer."""
        if self.panel.set_tasks(self.agent.tasks()):
            self.app.request_layout()

    async def _run_command(self, value: str) -> None:
        """Execute the matching command's handler and present its result."""
        name, _, argument = value.partition(" ")
        argument = argument.strip()
        self._status = f"{name} \u2026"
        command = next((item for item in self.commands if item.name == name), None)
        if command is None:
            self.transcript.notice(f"Unknown command: {name}. Try /help.")
        else:
            try:
                result = await command.handler(argument)
            except ValueError as error:
                self.transcript.notice(str(error))
            else:
                self._apply_result(result)
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
            selected = self.agent.use_model(name)
        except ValueError as error:
            self.transcript.notice(str(error))
            self.close_page()
        else:
            self.close_page()
            self._notify(f"using model {selected.shown_name}", level="success")

    def select_session(self, session_id: str) -> None:
        """Switch to the session picked in the panel and return to the composer."""
        try:
            self.agent.use_session(session_id)
        except ValueError as error:
            self.transcript.notice(str(error))
            self.close_page()
            return
        # Close the panel first: the toast is its own screen, and closing it
        # instead of the panel would leave the picker on top.
        self.close_page()
        self._notify(f"using session {session_id[:8]}", level="success")

    # -- titles -------------------------------------------------------------
    def _title_session_later(self, session_id: str) -> None:
        """Ask the agent to name a session once, off the composer's critical path."""
        if self._title_task is not None and not self._title_task.done():
            return
        self._title_task = asyncio.create_task(self._name_session(session_id))

    async def _name_session(self, session_id: str) -> None:
        """Store the title the agent summarizes and show it as a notice."""
        try:
            title = await self.agent.title_session(session_id)
        except Exception:
            return  # naming a session is a nicety; never report its failure
        if title is None:
            return
        self.transcript.notice(f"session title: {title}")
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
        panel = bottom_panel(page, rows=APPROVAL_ROWS, color=self.app.theme.border)
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
            self.transcript.notice(f"approval failed: {error}")
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
    def _header_left(self) -> str:
        """Label the app and the workspace it is running in."""
        return f"  \u25c8 zettcode  {compact_path(self.agent.workspace)}"

    def _header_right(self) -> str:
        """Show the model the agent is configured to use."""
        return f"{self.agent.active_model.shown_name}  "

    def _status_left(self) -> str:
        """Show the activity glyph, the status word, the mode, and the session id."""
        icon = activity_glyph(self.transcript.frame) if self._busy else "\u25cf"
        # The mode sits before the session id because the right-hand hint wins
        # the space fight, truncating the tail of this segment.
        mode = " \u00b7 auto" if self._auto_shell else ""
        return f"  {icon} {self._status}{mode}  session {self.agent.session_id[:8]}"

    def _status_right(self) -> str:
        """List the keys worth remembering while the composer has focus."""
        return "  ^C stop  ^T thinking  ^D exit  "


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
    return "\u2026" + tail
