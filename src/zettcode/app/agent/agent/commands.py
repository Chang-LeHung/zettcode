"""What the agent offers the shell to run and to show: its own commands, and what plugins added.

The commands report through transcript Markdown; commands that present a widget belong to
the shell, which owns the widgets. The plugin contributions are listed here because the
agent is where the shell asks for everything the runtime loaded.
"""

from __future__ import annotations

from zettcode.app.commands import Command, CommandContext, CommandResult
from zettcode.plugins import UiRow
from zettcode.providers import BUILTIN_PROVIDERS, Provider, merge_providers
from zettcode.tui import ThemeCatalog

from ..dialogue.mentions import MentionProvider
from .exports import ExportsMixin


class CommandsMixin(ExportsMixin):
    """The ``/new``, ``/compact``, and ``/export`` commands, and the plugins' commands, mentions, and rows."""

    @property
    def commands(self) -> tuple[Command, ...]:
        """Return the conversation commands the agent owns.

        They report through transcript Markdown; commands that present a widget
        (such as the model picker) belong to the shell, which owns the widgets.
        """
        return (
            Command("/new", "start a fresh session", "agent", self._command_new),
            Command("/compact", "summarize the context now", "agent", self._command_compact),
            Command("/export", "write this session to an HTML file: /export [path]", "agent", self._command_export),
        )

    @property
    def plugin_commands(self) -> tuple[Command, ...]:
        """Return the commands the installed plugins registered.

        The shell keeps them after its own commands, so a plugin cannot take
        over a built-in name; plugin-versus-plugin duplicates are rejected when
        the plugins load.
        """
        return self.runtime.plugins.commands

    @property
    def plugin_mentions(self) -> tuple[MentionProvider, ...]:
        """Return the ``@`` resource providers the installed plugins registered."""
        return self.runtime.plugins.mentions

    @property
    def providers(self) -> tuple[Provider, ...]:
        """Return the hosts ``/config`` can offer: the built-in ones, then the plugins' own."""
        return merge_providers(BUILTIN_PROVIDERS, self.runtime.plugins.providers)

    @property
    def themes(self) -> ThemeCatalog:
        """Return every palette that can be asked for by name: the plugins', then the reader's own files.

        Built fresh each time it is asked: it lists names and builds nothing, and the reader's directory may have
        gained a file since the last look.
        """
        return ThemeCatalog(self.runtime.plugins.themes, self.runtime.config.themes_dir)

    @property
    def plugin_failures(self) -> tuple[str, ...]:
        """Return one message per plugin that could not be loaded or activated."""
        return self.runtime.plugins.failures

    @property
    def plugin_rows(self) -> tuple[UiRow, ...]:
        """Return the header and status rows plugins asked the shell to draw."""
        return self.runtime.plugins.rows

    async def _command_new(self, context: CommandContext) -> CommandResult:
        """Start a fresh session."""
        session_id = self.new_session()
        return CommandResult(notification=f"started session {session_id[:8]}")

    async def _command_export(self, context: CommandContext) -> CommandResult:
        """Write the session and its context to one HTML file.

        The path argument is optional; without it the file lands in the
        workspace, named after the session, and the result says where.
        """
        path = await self.export_session(context.argument.strip() or None)
        return CommandResult(message=f"Exported to `{path}`")

    async def _command_compact(self, context: CommandContext) -> CommandResult:
        """Summarize the conversation now, whatever its size.

        The row and the outcome notice arrive while this await runs: the pass
        dispatches through the same event dispatcher a turn does, so the
        transcript animates ``Compacting`` and ends with ``Context compaction
        applied`` (or ``skipped`` when the summary would not be smaller).
        """
        await self.compact()
        return CommandResult()
