"""The ZettCode application: transcript, composer, commands, and approvals."""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from pathlib import Path

from zett_agent import AgentEvent

from ...tui import (
    DARK,
    Anchor,
    Completer,
    CompletionItem,
    CompletionPopup,
    Dialog,
    DialogAction,
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
    Widget,
    centered,
    theme_named,
)
from ...tui.layout import Slot
from ...tui.widgets import Rule, Text
from ..agent.agent import ZettCodeAgent
from ..agent.projection import TranscriptProjector
from ..agent.transcript import Transcript, activity_glyph
from .transcript import TranscriptView

COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "show the commands and the keys"),
    ("/new", "start a fresh session"),
    ("/sessions", "list persisted sessions"),
    ("/model", "list or switch models: /model <name>"),
    ("/use", "switch to a session: /use <id>"),
    ("/theme", "switch the palette: /theme dark|light"),
    ("/clear", "clear the transcript"),
    ("/quit", "exit"),
    ("/exit", "exit, same as /quit"),
)

KEY_HELP = (
    "  Enter send \u00b7 Alt-Enter newline \u00b7 Ctrl-C stop or clear\n"
    "  Ctrl-T thinking \u00b7 PgUp/PgDn scroll \u00b7 Ctrl-L redraw \u00b7 Ctrl-D exit"
)


class CommandCompleter(Completer):
    """Complete the slash commands matching the line the cursor sits on.

    A space ends the suggestion: ``/use abc`` has moved on to a session id, so
    the menu steps aside instead of filtering the commands down to nothing.
    """

    def __call__(self, text: str, position: int) -> tuple[CompletionItem, ...]:
        """Return the matching commands for the token ending at ``position``.

        Args:
            text: Full draft, newlines included.
            position: Cursor as a code-point index into ``text``.
        """
        start = text.rfind("\n", 0, position) + 1
        token = text[start:position]
        if not token.startswith("/") or any(character.isspace() for character in token):
            return ()
        return tuple(
            CompletionItem(name, description=description) for name, description in COMMANDS if name.startswith(token)
        )


def help_text() -> str:
    """Return the ``/help`` body, generated from the command table."""
    width = max(len(name) for name, _ in COMMANDS) + 2
    rows = [f"  {name:<{width}}{description}" for name, description in COMMANDS]
    return "\n".join(["Commands", *rows, "", "Keys", KEY_HELP])


WELCOME = (
    "     ╭─────┬─────╮\n"
    "     │     ✦     │   ZettCode\n"
    "     ╰─────┴─────╯   A focused coding agent\n"
    "\n"
    "  Type a task below, or /help for commands."
)


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

        self.view = TranscriptView(self.transcript, theme=theme)
        self.composer = TextArea(
            prompt="\u203a ",
            placeholder="Ask ZettCode to do anything",
            completer=CommandCompleter(),
            max_height=8,
            on_submit=self.submit,
            on_change=self._refresh_completions,
            surface=True,
        )
        self.completions = CompletionPopup(max_height=len(COMMANDS))
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
        self._busy = False
        self._status = "ready"
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

        await TerminalRunner(self.app).run()

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
            when=lambda: not self._busy and not self.composer.text,
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
        return self.completions.visible

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
        finally:
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
        """Dispatch one slash command and report its result."""
        command, _, argument = value.partition(" ")
        argument = argument.strip()
        self._status = f"{command} \u2026"
        match command:
            case "/new":
                session = self.agent.new_session()
                self._notify(f"started session {session[:8]}", level="success")
            case "/use" if argument:
                self.agent.use_session(argument)
                self._notify(f"using session {self.agent.session_id[:8]}", level="success")
            case "/use":
                self.transcript.notice("Usage: /use <session-id>")
            case "/sessions":
                sessions = await self.agent.list_sessions(limit=20)
                if not sessions:
                    self.transcript.notice("No persisted sessions.")
                for session in sessions:
                    marker = "*" if session.session_id == self.agent.session_id else " "
                    self.transcript.notice(f"{marker} {session.session_id}  {session.message_count} messages")
            case "/model" if argument:
                try:
                    selected = self.agent.use_model(argument)
                except ValueError as error:
                    self.transcript.notice(str(error))
                else:
                    self._notify(f"using model {selected.shown_name}", level="success")
                    self.app.request_layout()
            case "/model":
                for entry in self.agent.models:
                    marker = "*" if entry is self.agent.active_model else " "
                    self.transcript.notice(f"{marker} {entry.shown_name} ({entry.model})")
            case "/clear":
                self.transcript.clear()
            case "/theme":
                self._set_theme(argument)
            case "/help":
                self.transcript.notice(help_text())
            case "/quit" | "/exit":
                self.app.exit()
            case _:
                self.transcript.notice(f"Unknown command: {command}. Try /help.")
        self._status = "ready"
        self.app.invalidate()

    def _set_theme(self, name: str) -> None:
        """Switch the palette, reporting usage errors instead of raising.

        Args:
            name: Theme name from the argument of ``/theme``.
        """
        if not name:
            self.transcript.notice("Usage: /theme dark|light")
            return
        try:
            theme = theme_named(name)
        except ValueError:
            self.transcript.notice(f"Unknown theme: {name}. Try dark or light.")
            return
        self.app.theme = theme
        self.app.request_layout()
        self.transcript.notice(f"theme: {theme.name}")

    # -- approvals ----------------------------------------------------------
    def _approval_requested(self, event: AgentEvent) -> None:
        """Show the shell approval dialog for one agent request."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        call_id = str(payload.get("tool_call_id", ""))
        session_id = str(payload.get("session_id") or self.agent.session_id)
        command = str(payload.get("command", ""))
        actions = [DialogAction("Run", lambda: self._respond(session_id, call_id, "execute", False))]
        if payload.get("remember_supported"):
            actions.append(DialogAction("Always", lambda: self._respond(session_id, call_id, "execute", True)))
        actions.append(DialogAction("Abort", lambda: self._respond(session_id, call_id, "abort", False)))
        dialog = Dialog(
            Text(command),
            title="Run this command?",
            actions=tuple(actions),
            on_cancel=lambda: self._respond(session_id, call_id, "abort", False),
        )
        self.app.push_screen(Screen(centered(dialog), name="approval", modal=True))

    def _respond(self, session_id: str, call_id: str, decision: str, remember: bool) -> None:
        """Dismiss the dialog and answer the suspended agent run.

        Args:
            session_id: Session the approval belongs to, echoed back to the agent.
            call_id: Tool call the decision applies to.
            decision: ``"execute"`` or ``"abort"``.
            remember: Ask the agent to remember this decision for the session.
        """
        self.app.pop_screen()
        try:
            self.agent.respond_approval(session_id, call_id, decision, remember)
        except Exception as error:
            self.transcript.notice(f"approval failed: {error}")
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
        """Show the activity glyph, the status word, and the session id."""
        icon = activity_glyph(self.transcript.frame) if self._busy else "\u25cf"
        return f"  {icon} {self._status}  session {self.agent.session_id[:8]}"

    def _status_right(self) -> str:
        """List the keys worth remembering while the composer has focus."""
        return "  ^C stop  ^T thinking  ^D exit  "


class ZettCodeRoot(Widget):
    """Thin root that advances the activity frame while a request runs."""

    def __init__(self, controller: ZettCodeApp, body: VBox) -> None:
        """Keep the controller reachable from the tick hook."""
        super().__init__()
        self.controller = controller
        self.body = body

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the single body widget the root lays out."""
        return (self.body,)

    def layout(self, rect) -> None:
        """Give the body the full application rectangle."""
        super().layout(rect)
        self.body.layout(rect)

    def render(self, canvas) -> None:
        """Paint the body into the shared canvas."""
        self.body.render(canvas)

    def cursor(self):
        """Forward the cursor request to the body."""
        return self.body.cursor()

    def on_tick(self) -> None:
        """Advance the activity frame while a request is running."""
        if self.controller.busy and (self.app is None or not self.app.reduced_motion):
            self.controller.transcript.advance_frame()


def compact_path(path: Path, *, limit: int = 38) -> str:
    """Shorten a workspace path for the header.

    Args:
        path: Absolute path to display.
        limit: Most characters to keep; the home directory collapses to ``~``,
            and anything longer keeps a leading ellipsis plus its tail.
    """
    value = str(path)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        value = "~" + value[len(home) :]
    return value if len(value) <= limit else "\u2026" + value[-(limit - 1) :]
