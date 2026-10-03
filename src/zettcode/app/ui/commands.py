"""The shell's own slash commands.

They live outside :class:`~zettcode.app.ui.app.ZettCodeApp` so that class stays
the wiring — widget tree, keymap, pages — rather than the command set. Every
handler is a method here, returns a
:class:`~zettcode.app.commands.CommandResult`, and never paints directly: the
shell applies the result (see ``ZettCodeApp._apply_result``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...tui import Widget, theme_named
from ..commands import Command, CommandResult
from .widgets import ModelPage, SessionsPage, bottom_panel, help_text

#: Rows the picker panels take from the bottom of the screen: the title, the
#: list, and the footer hint. The handler owns the number; nothing in the
#: framework reads it.
PICKER_ROWS = 14

if TYPE_CHECKING:  # pragma: no cover - only needed for the annotation
    from .app import ZettCodeApp


class ShellCommands:
    """Build the commands the shell adds around the agent's own."""

    def __init__(self, shell: ZettCodeApp) -> None:
        """Keep the shell the handlers act on; ``shell.app`` is its ``TuiApp``."""
        self.shell = shell

    def build(self, agent_commands: Sequence[Command]) -> tuple[Command, ...]:
        """Return every command, leaving the agent's own in their order."""
        return (
            Command("/help", "show the commands and the keys", "app", self.help),
            *agent_commands,
            Command("/sessions", "browse recent sessions", "app", self.sessions),
            Command("/model", "choose a model", "app", self.model),
            Command("/theme", "switch the palette: /theme dark|light", "app", self.theme),
            Command("/clear", "clear the transcript", "app", self.clear),
            Command("/quit", "exit", "app", self.quit),
            Command("/exit", "exit, same as /quit", "app", self.quit),
        )

    async def help(self, argument: str) -> CommandResult:
        """Describe commands from both the shell and the agent."""
        return CommandResult(message=help_text(self.shell.commands))

    async def model(self, name: str) -> CommandResult:
        """Open the model picker, or switch directly to a named model.

        The picker is a widget, so the command lives with the shell: the agent
        owns the models, the shell owns the widget that chooses between them.
        """
        if name:
            selected = self.shell.agent.use_model(name)
            return CommandResult(notification=f"using model {selected.shown_name}", relayout=True)
        page = ModelPage(self.shell.agent, on_select=self.shell.select_model, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    async def sessions(self, name: str) -> CommandResult:
        """Open the recent-session picker, or switch straight to a named session.

        The picker is a widget, so the command lives with the shell: the agent
        owns the stored sessions, the shell owns the widget that browses them.
        """
        if name:
            self.shell.agent.use_session(name)
            return CommandResult(notification=f"using session {name[:8]}", relayout=True)
        sessions = await self.shell.agent.list_sessions(limit=20)
        if not sessions:
            return CommandResult(message="No persisted sessions.")
        page = SessionsPage(sessions, on_select=self.shell.select_session, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    def _panel(self, page: Widget) -> Widget:
        """Wrap one picker in the bottom panel the shell's own commands use."""
        return bottom_panel(page, rows=PICKER_ROWS, color=self.shell.app.theme.border)

    async def theme(self, name: str) -> CommandResult:
        """Select a theme without changing agent settings."""
        if not name:
            return CommandResult(message="Usage: `/theme dark|light`")
        try:
            theme = theme_named(name)
        except ValueError:
            return CommandResult(message=f"Unknown theme: {name}. Try dark or light.")
        self.shell.app.theme = theme
        return CommandResult(message=f"theme: {theme.name}", relayout=True)

    async def clear(self, argument: str) -> CommandResult:
        """Clear visible conversation entries."""
        self.shell.transcript.clear()
        return CommandResult()

    async def quit(self, argument: str) -> CommandResult:
        """Exit the terminal application."""
        self.shell.app.exit()
        return CommandResult()
