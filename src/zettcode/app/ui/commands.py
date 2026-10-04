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

from ...tui import ListItem, ListPage, Widget, theme_names
from ..commands import Command, CommandResult
from .widgets import ContextPage, ModelPage, SessionsPage, bottom_panel, help_text

#: Rows the picker panels take from the bottom of the screen: the title, the
#: list, and the footer hint. The handler owns the number; nothing in the
#: framework reads it.
PICKER_ROWS = 14

#: One-line description per built-in palette, shown next to its name.
THEME_NOTES = {
    "dark": "green-leaning palette for dark terminals",
    "light": "green-leaning palette for light terminals",
}

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
            Command("/theme", "choose the palette (or /theme dark|light)", "app", self.theme),
            Command("/context", "what is filling the context window", "app", self.context),
            Command("/title", "name this session: /title <name>", "app", self.title),
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
            self.shell.change_model(name)
            return CommandResult(relayout=True)
        page = ModelPage(self.shell.agent, on_select=self.shell.select_model, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    async def sessions(self, name: str) -> CommandResult:
        """Open the recent-session picker, or switch straight to a named session.

        The picker is a widget, so the command lives with the shell: the agent
        owns the stored sessions, the shell owns the widget that browses them.
        """
        if name:
            self.shell.restore_session(name)
            return CommandResult(notification=f"using session {name[:8]}", relayout=True)
        sessions = await self.shell.agent.list_sessions(limit=20)
        if not sessions:
            return CommandResult(message="No persisted sessions.")
        page = SessionsPage(sessions, on_select=self.shell.select_session, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    def _panel(self, page: Widget) -> Widget:
        """Wrap one picker in the bottom panel the shell's own commands use."""
        return bottom_panel(page, rows=PICKER_ROWS)

    async def theme(self, name: str) -> CommandResult:
        """Open the theme picker, or switch straight to a named palette.

        The built-in palettes are a tiny fixed list, so the picker is a plain
        :class:`ListPage`; a named argument keeps the direct `/theme light` path
        working the same way `/model <name>` does.
        """
        if name:
            self.shell.apply_theme(name)
            return CommandResult(relayout=True)
        current = self.shell.app.theme.name
        names = theme_names()
        page = ListPage(
            [ListItem(item, item, THEME_NOTES.get(item, "")) for item in names],
            title="Theme",
            on_select=lambda item: self.shell.select_theme(str(item.value)),
            on_cancel=self.shell.close_page,
            selected=names.index(current) if current in names else 0,
        )
        return CommandResult(widget=self._panel(page))

    async def context(self, argument: str) -> CommandResult:
        """Show what the next request carries, by source and token share.

        The breakdown comes from the request the runtime assembled for the last
        model call, so it needs one turn before it exists: before that there is
        nothing measured to show, and the panel would be a page of zeroes.
        """
        report = await self.shell.agent.context_report()
        if report is None:
            return CommandResult(
                message="No request yet \u2014 send one (or resume a session), then `/context` shows the breakdown."
            )
        return CommandResult(widget=self._panel(ContextPage(report, on_cancel=self.shell.close_page)))

    async def title(self, argument: str) -> CommandResult:
        """Rename the active session, or report the name it already has.

        The name lives in the session metadata beside the title the agent
        summarizes, so `/sessions` shows it and a later automatic naming step
        leaves it alone.
        """
        if not argument:
            current = self.shell.agent.session_title
            if current is None:
                return CommandResult(message="This session has no title yet. Use `/title <name>`.")
            return CommandResult(message=f"Title: **{current}**")
        try:
            renamed = await self.shell.rename_session(argument)
        except ValueError as error:
            return CommandResult(message=str(error))
        return CommandResult(notification=f"renamed to {renamed}", relayout=True)

    async def clear(self, argument: str) -> CommandResult:
        """Clear visible conversation entries."""
        self.shell.transcript.clear()
        return CommandResult()

    async def quit(self, argument: str) -> CommandResult:
        """Exit the terminal application."""
        self.shell.app.exit()
        return CommandResult()
