"""The shell's own slash commands: the ones that preview as they are walked or edit a form of their own.

They live outside :class:`~zettcode.app.ui.app.ZettCodeApp` so that class stays
the wiring \u2014 widget tree, keymap, pages \u2014 rather than the command set. Every
handler is a method here, returns a
:class:`~zettcode.app.commands.CommandResult`, and never paints directly: the
shell applies the result (see ``ZettCodeApp._apply_result``).

The commands that only need the shell's narrow public surface (``/resume``, ``/model``, ``/context`` and the rest)
are built-in plugins instead, in :mod:`zettcode.app.plugins.builtin_commands`. What stays here is what cannot be written
against that surface yet: ``/theme`` and ``/pet`` call the shell's previews as the menu is walked, and ``/config``,
``/statusline`` and ``/self-compact`` open panels that edit state the shell owns.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from zettcode.config_edit import ConfigEditError

from ..commands import Command, CommandContext, CommandProvider, CommandResult, Subcommand, subcommand_words
from .widgets import (
    SELF_COMPACT_ROWS,
    PetPage,
    SelfCompactPage,
    StatuslinePage,
    bottom_panel,
    pet_rows,
    statusline_rows,
)

#: One-line description per built-in palette, shown next to its name.
THEME_NOTES = {
    "dark": "green-leaning palette for dark terminals",
    "light": "green-leaning palette for light terminals",
}

#: What ``/config`` takes first, as its description lists them.
CONFIG_WORDS = (
    Subcommand("add", "add a model: a provider, then what it needs", needs_more=True),
    Subcommand("remove", "remove a model by number or name", needs_more=True),
    Subcommand("list", "show the models in the file"),
    Subcommand("providers", "show the providers and where to get a key"),
)

if TYPE_CHECKING:  # pragma: no cover - only needed for the annotation
    from .app import ZettCodeApp


class ShellCommands(CommandProvider):
    """The commands the shell keeps for itself.

    It is one provider among several: the shell merges it with the built-in plugins' commands, the agent's and the
    installed plugins' through a registry, so every source of commands is the same shape and the first to claim a
    name wins.
    """

    def __init__(self, shell: ZettCodeApp) -> None:
        """Keep the shell the handlers act on; ``shell.app`` is its ``TuiApp``."""
        self.shell = shell

    @property
    def items(self) -> Sequence[Command]:
        """Return the shell's own commands, in the order ``/help`` lists them."""
        return (
            # ``when_busy="now"`` below is for what only looks at the session or sets something the
            # running request reads when it needs it. What it touches while a request runs - the
            # transcript it writes into, the session, the model it started with and the window that
            # model's compaction is sized to - stays refused: /config, and the plugins' /model, /clear,
            # /resume, /fork, plus the agent's /new, /compact and /export.
            Command(
                "/config",
                "add, change or remove models: /config [add|remove|list|providers]",
                "app",
                self.config,
                subcommands=CONFIG_WORDS,
            ),
            Command(
                "/theme",
                "choose the palette: /theme <name> (the menu previews each)",
                "app",
                self.theme,
                when_busy="now",
                subcommands=self.theme_words,
                preview=self.shell.preview_theme,
            ),
            Command(
                "/pet",
                "choose the pet: /pet opens a panel, /pet <name> picks one",
                "app",
                self.pet,
                when_busy="now",
            ),
            Command(
                "/self-compact",
                "let the model compact its own context: /self-compact opens a panel; on|off|default|global",
                "app",
                self.self_compact,
                when_busy="now",
            ),
            Command(
                "/statusline",
                "choose which parts of the header and status line show: /statusline opens a panel",
                "app",
                self.statusline,
                when_busy="now",
            ),
        )

    def _offer(self, command: str) -> CommandResult:
        """Put the command and a space in the draft, which opens the menu of the words it takes.

        A command that is a choice among a few fixed words has no page of its own: the menu is the choice,
        so typing the bare command only moves the reader to it.
        """
        self.shell.offer(command)
        return CommandResult()

    def theme_words(self) -> tuple[Subcommand, ...]:
        """Offer every palette by name: the built-in ones, then the plugins' and the reader's own, with their notes."""
        catalog = self.shell.agent.themes
        notes = {**THEME_NOTES, **catalog.notes()}
        return subcommand_words(catalog.names(), notes, self.shell.app.theme.name)

    async def config(self, context: CommandContext) -> CommandResult:
        """Open the model list, or act on it from one line.

        With nothing after it the command opens the panel, which asks one question at a time and
        is the way to type a token without it being echoed. The words after it do the same job
        on one line: ``add`` takes a provider and whatever of its settings the line gives, and
        asks for the rest; ``remove`` takes a number or a name; ``list`` and ``providers`` only
        show. A refusal \u2014 a bad address, a file that cannot be edited \u2014 is the command's error and
        nothing is written.
        """
        word, _, rest = context.argument.partition(" ")
        shell = self.shell
        if not word:
            return CommandResult(widget=shell.config_page())
        if word == "list":
            return CommandResult(message=shell.config_listing())
        if word == "providers":
            return CommandResult(message=shell.config_providers_listing())
        if word == "add":
            done = shell.config_add_from_line(rest)
            return CommandResult(notification=done, relayout=True) if done else CommandResult()
        if word == "remove":
            return CommandResult(notification=shell.config_remove_from_line(rest), relayout=True)
        raise ValueError("Usage: /config [add <provider> ... | remove <number|name> | list | providers]")

    async def theme(self, context: CommandContext) -> CommandResult:
        """Switch straight to a named palette and remember it, or open the menu of them.

        The choice is written to ``[ui] theme`` in the config file so the next start opens in it. A file that
        cannot take the line does not undo the switch: the palette is on, and the reader is told it will not be
        there next time and why.
        """
        if not context.argument:
            return self._offer("/theme")
        name = context.argument.strip()
        self.shell.apply_theme(name)
        try:
            self.shell.agent.remember_theme(name)
        except ConfigEditError as error:
            context.ui.error(f"{name} is on for this run but will not be remembered: {error}")
            return CommandResult(relayout=True)
        return CommandResult(relayout=True, notification=f"theme {name} \u2014 remembered for next time")

    async def pet(self, context: CommandContext) -> CommandResult:
        """Open the panel of pets, or switch straight to a named one; either way the choice is remembered.

        The panel lists the pets with the marked one shown beside the list and over the conversation; Enter
        chooses and Escape puts the old one back. The choice is written to ``[ui] pet`` in the config file so the
        next start opens with it. A file that cannot take the line does not undo the switch: the pet is there,
        and the reader is told it will not be next time and why. A pet that is switched off in ``/statusline`` is
        still chosen, and the reader is told why nothing appeared.
        """
        shell = self.shell
        if not context.argument:

            def choose(name: str) -> None:
                shell.close_page()
                try:
                    shell.apply_pet(name)
                    shell.agent.remember_pet(name)
                except ValueError as error:
                    shell.transcript.error(str(error))
                    return
                except ConfigEditError as error:
                    shell.transcript.error(f"{name} is here for this run but will not be remembered: {error}")
                    return
                shell.transcript.notice(self._pet_chosen(name))

            def cancel() -> None:
                shell.preview_pet(None)
                shell.close_page()

            catalog = shell.agent.pets
            page = PetPage(catalog, shell.pet.pet.name, on_move=shell.preview_pet, on_select=choose, on_cancel=cancel)
            return CommandResult(widget=bottom_panel(page, rows=pet_rows(len(catalog.names()), shell.app.height)))
        name = context.argument.strip()
        shell.apply_pet(name)
        try:
            shell.agent.remember_pet(name)
        except ConfigEditError as error:
            context.ui.error(f"{name} is here for this run but will not be remembered: {error}")
            return CommandResult(relayout=True)
        return CommandResult(relayout=True, notification=self._pet_chosen(name))

    def _pet_chosen(self, name: str) -> str:
        """Say which pet was chosen, and why nothing shows if the reader has switched the pet off."""
        if "pet" in self.shell.agent.statusline_hidden:
            return f"pet {name} \u2014 remembered, but the pet is hidden: /statusline show pet"
        return f"pet {name} \u2014 remembered for next time"

    async def self_compact(self, context: CommandContext) -> CommandResult:
        """Change self-compaction from the words it takes, or open the panel with a rail for each setting.

        The panel has two rails: this session's own choice, and the default every session that never chose
        follows. The knobs only move; Enter applies both, which is when the session's metadata and the config
        file are written. A part that cannot be saved is reported and the other part still applies, so a
        missing config file does not cost the session its choice. Escape applies nothing.
        """
        shell = self.shell
        if context.argument:
            try:
                return CommandResult(message=shell.agent.change_self_compaction(context.argument))
            except ValueError as error:
                return CommandResult(message=str(error))

        def apply(choice: bool | None, default: bool) -> None:
            shell.close_page()
            agent = shell.agent
            # The default first: whether a choice differs from it is what decides if a session that has not
            # been used yet has anything to save.
            for change, needed in (
                (lambda: agent.remember_self_compaction(default), default != agent.self_compaction_default),
                (lambda: shell.client.use_self_compaction(choice), choice != shell.client.self_compaction_choice),
            ):
                if not needed:
                    continue
                try:
                    change()
                except ValueError as error:
                    shell.transcript.error(str(error))
            shell.transcript.notice(shell.agent.self_compaction_summary())

        page = SelfCompactPage(
            shell.client.self_compaction_choice,
            shell.agent.self_compaction_default,
            on_apply=apply,
            on_cancel=shell.close_page,
            session_open=not shell.client.session.locked,
        )
        return CommandResult(widget=bottom_panel(page, rows=SELF_COMPACT_ROWS))

    async def statusline(self, context: CommandContext) -> CommandResult:
        """Hide or show parts from the words it takes, or open the panel with a switch for each part.

        The switches only move; Enter writes ``[statusline]`` into the config file, and the rows follow at
        the next paint. Escape applies nothing. A config file that cannot be written is reported and the rows
        stay as they were.
        """
        shell = self.shell
        if context.argument:
            try:
                message = shell.agent.change_statusline(context.argument)
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(message=message, relayout=True)

        def apply(shown: dict[str, bool]) -> None:
            shell.close_page()
            try:
                shell.agent.remember_statusline(shown)
            except ValueError as error:
                shell.transcript.error(str(error))
                return
            shell.transcript.notice(shell.agent.statusline_summary())

        page = StatuslinePage(shell.agent.statusline_hidden, on_apply=apply, on_cancel=shell.close_page)
        return CommandResult(widget=bottom_panel(page, rows=statusline_rows(shell.app.height)))
