"""What the agent offers the shell to run and to show: its own commands, and what plugins added.

The commands report through transcript Markdown; commands that present a widget belong to
the shell, which owns the widgets. The plugin contributions are listed here because the
agent is where the shell asks for everything the runtime loaded.
"""

from __future__ import annotations

from zettcode.app.commands import Command, CommandContext, CommandHost, CommandResult
from zettcode.app.pets import PetCatalog, bundled_pets
from zettcode.app.plugins.host import HOST_LINK, HostLink
from zettcode.app.plugins.plugin import TuiPlugins
from zettcode.app.plugins.state import TurnSegment, UiRow
from zettcode.engine.agent.exports import ExportsMixin
from zettcode.providers import BUILTIN_PROVIDERS, Provider, merge_providers
from zettcode.statusline import NAMES, unknown
from zettcode.tui import ThemeCatalog

from ..conversation.presenters import Presenters
from .settings import AppearanceMixin

#: The words ``/self-compact`` takes after it, or after ``global``.
_SELF_COMPACT_WORDS = frozenset({"on", "off", "default"})


class CommandsMixin(AppearanceMixin, ExportsMixin):
    """The ``/new``, ``/compact``, and ``/export`` commands, and the plugins' commands, mentions, and rows."""

    @property
    def terminal_plugins(self) -> TuiPlugins:
        """Return what the plugins contributed to the terminal; the engine was built with the terminal's loader."""
        plugins = self.runtime.plugins
        if not isinstance(plugins, TuiPlugins):
            raise TypeError("This agent's engine was not built with the terminal's plugin loader")
        return plugins

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

    def attach_host(self, host: CommandHost) -> None:
        """Tell the plugins where the shell is, so the words their commands offer can follow the session."""
        link = self.runtime.plugins.find(HOST_LINK, HostLink)
        if link is not None:
            link.attach(host)

    @property
    def plugin_commands(self) -> tuple[Command, ...]:
        """Return the commands the installed plugins registered, not counting the built-in ones.

        The shell keeps them after everything built in, so a plugin cannot take over a built-in name;
        plugin-versus-plugin duplicates are rejected when the plugins load.
        """
        return self.terminal_plugins.installed_commands

    @property
    def builtin_plugin_commands(self) -> tuple[Command, ...]:
        """Return the commands the program's own plugins registered: ``/resume``, ``/model``, ``/usage`` and the rest."""
        return self.terminal_plugins.builtin_commands

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
        return ThemeCatalog(self.terminal_plugins.themes, self.runtime.config.themes_dir)

    @property
    def pets(self) -> PetCatalog:
        """Return every pet that can be asked for by name: the built-in plugin's, then any other plugin's.

        A plugin bundle that offers none (one built by hand, without the built-in plugin) gets the program's own.
        """
        sources = self.terminal_plugins.pets
        return PetCatalog(sources or bundled_pets())

    @property
    def turn_segments(self) -> tuple[TurnSegment, ...]:
        """Return the items of the line a request ends on, the program's own first, then the plugins'."""
        return self.terminal_plugins.turn_segments

    @property
    def plugin_failures(self) -> tuple[str, ...]:
        """Return one message per plugin that could not be loaded or activated."""
        return self.terminal_plugins.failures

    @property
    def presenters(self) -> Presenters:
        """Return how this run draws entries: the built-in presenters, and any a plugin outranks them with.

        Built from the bundle rather than from a module-level default for the same reason the palettes are: the
        program's own rows are registered through the plugin route, so a plugin that draws a kind or a family of
        rows reaches the transcript without a second path only plugins could not take.
        """
        return Presenters(self.terminal_plugins.presenters)

    @property
    def plugin_rows(self) -> tuple[UiRow, ...]:
        """Return the header and status rows plugins asked the shell to draw."""
        return self.terminal_plugins.rows

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

    def self_compaction_summary(self) -> str:
        """Say in one line whether self-compaction is on here, where that comes from, and what the default is."""
        state = "on" if self.self_compaction else "off"
        default = "on" if self.self_compaction_default else "off"
        if self.self_compaction_choice is None:
            return f"Self-compaction is {state}: this session follows the default ({default})"
        return f"Self-compaction is {state}: this session chose it; the default is {default}"

    def self_compact_report(self) -> str:
        """Say what self-compaction is, whether it is on here, and where that comes from."""
        choice = self.self_compaction_choice
        default = "on" if self.self_compaction_default else "off"
        state = "on" if self.self_compaction else "off"
        source = (
            f"this session chose it; the config default is **{default}**"
            if choice is not None
            else "following the config default (`[compaction] self`)"
        )
        return (
            f"Self-compaction is **{state}** ({source}).\n\n"
            "When on, the model gets a `compact_context` tool and can summarize its own earlier conversation "
            "when it judges the detail is no longer needed. The current turn is always kept. "
            "`/compact` and the automatic threshold work either way.\n\n"
            "`/self-compact on|off` sets this session; `default` hands it back to the config; "
            "`global on|off` changes the default for every session that has not chosen."
        )

    def change_self_compaction(self, argument: str) -> str:
        """Read or change self-compaction from the words ``/self-compact`` takes, and say what now applies.

        ``on``, ``off`` and ``default`` set this session's own choice; ``global on`` and ``global off``
        write the default for every session into the config file. A failed write is never reported as saved.

        Raises:
            ValueError: The words are not ones the command takes, or the change could not be saved.
        """
        words = argument.lower().split()
        scope = "session"
        if words[:1] == ["global"]:
            scope, words = "global", words[1:]
        usage = ValueError("Usage: /self-compact [on|off|default] or /self-compact global on|off")
        if len(words) > 1 or (scope == "global" and not words) or (words and words[0] not in _SELF_COMPACT_WORDS):
            raise usage
        if scope == "global":
            if words[0] == "default":
                raise usage
            self.remember_self_compaction(words[0] == "on")
        elif words:
            self.use_self_compaction({"on": True, "off": False, "default": None}[words[0]])
        return self.self_compact_report()

    def statusline_summary(self) -> str:
        """Say in one line which parts of the header and the status line are hidden."""
        hidden = [
            *(name for name in NAMES if name in self.statusline_hidden),
            *sorted(self.statusline_hidden - set(NAMES)),
        ]
        if not hidden:
            return "Status line: every part is shown"
        total = len(NAMES) + len({item.name for item in self.turn_segments} - set(NAMES))
        return f"Status line: {len(hidden)} of {total} parts hidden ({', '.join(hidden)})"

    def change_statusline(self, argument: str) -> str:
        """Hide or show parts of the header and status line from the words ``/statusline`` takes.

        ``hide <name>...`` and ``show <name>...`` change the named parts, and ``show all`` brings every one
        back. The change is written to ``[statusline]`` in the config file, and nothing is changed when any
        name is not a part.

        Raises:
            ValueError: The words are not ones the command takes, or the change could not be saved.
        """
        words = argument.lower().split()
        usage = ValueError(
            f"Usage: /statusline [hide|show] <part>... or /statusline show all; parts: {', '.join(NAMES)}"
        )
        if len(words) < 2 or words[0] not in {"hide", "show"}:
            raise usage
        visible = words[0] == "show"
        names = list(NAMES) if visible and words[1:] == ["all"] else words[1:]
        if stray := unknown(names):
            raise ValueError(f"No such part: {', '.join(stray)}. Parts: {', '.join(NAMES)}")
        self.remember_statusline({name: visible for name in names})
        return self.statusline_summary()

    async def _command_compact(self, context: CommandContext) -> CommandResult:
        """Summarize the conversation now, whatever its size.

        The row and the outcome notice arrive while this await runs: the pass
        dispatches through the same event dispatcher a turn does, so the
        transcript animates ``Compacting`` and ends with ``Context compaction
        applied`` (or ``skipped`` when the summary would not be smaller).
        """
        await self.compact()
        return CommandResult()
