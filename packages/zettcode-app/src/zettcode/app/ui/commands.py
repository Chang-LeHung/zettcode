"""The shell's own slash commands: the ones that preview as they are walked or edit a form of their own.

They live outside :class:`~zettcode.app.ui.app.ZettCodeApp` so that class stays
the wiring \u2014 widget tree, keymap, pages \u2014 rather than the command set. Every
handler is a method here, returns a
:class:`~zettcode.app.commands.CommandResult`, and never paints directly: the
shell applies the result (see ``ZettCodeApp._apply_result``).

The commands that only need the shell's narrow public surface (``/resume``, ``/model``, ``/context`` and the rest)
are built-in plugins instead, in :mod:`zettcode.app.plugins.builtin_commands`. What stays here is what cannot be written
against that surface yet: ``/theme`` and ``/pet`` call the shell's previews as the menu is walked, and ``/config``
and ``/statusline`` open panels that edit state the shell owns; self-compaction is a `/plugins` switch now.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from zettcode.config_edit import ConfigEditError
from zettcode.statusline import NAMES, Part

from ..commands import (
    Command,
    CommandContext,
    CommandProvider,
    CommandResult,
    Subcommand,
    subcommand_words,
)
from .widgets import (
    PetPage,
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


def _missing_file(error: BaseException) -> bool:
    """Return whether a failed write failed because there is no file yet, however deeply the error was wrapped.

    The file editor raises ``ConfigEditError("… does not exist") from`` the ``FileNotFoundError``, and the SDK
    wraps that again in ``ConfigurationError``, so the cause is the only reliable part of the answer. Note what
    this cannot tell apart: a *read* of a missing file inside a directory that cannot be written also raises
    ``FileNotFoundError``, so the machine is promised a file that ``/config`` will then fail to write — with its
    own error, which is the one place that knows why.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, FileNotFoundError):
            return True
        current = current.__cause__ or current.__context__
    return False


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
            self._unkept(f"theme {name}", error, applied=True)
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
                except ConfigEditError as error:
                    # Before ValueError: the file editor's refusal is a ValueError too, and it is the one a
                    # machine with no file yet should hear about without the word "failure".
                    self._unkept(f"pet {name}", error, applied=True)
                    return
                except ValueError as error:
                    shell.transcript.error(str(error))
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
            self._unkept(f"pet {name}", error, applied=True)
            return CommandResult(relayout=True)
        return CommandResult(relayout=True, notification=self._pet_chosen(name))

    def _pet_chosen(self, name: str) -> str:
        """Say which pet was chosen, and why nothing shows if the reader has switched the pet off."""
        if "pet" in self.shell.agent.statusline_hidden:
            return f"pet {name} \u2014 remembered, but the pet is hidden: /statusline show pet"
        return f"pet {name} \u2014 remembered for next time"

    def _unwritten_config(self, what: str, error: Exception, *, applied: bool) -> str | None:
        """Return the sentence for a setting the missing file could not keep, or ``None`` when it is another failure.

        A machine that has never been set up has no config file at all, and none of the commands that write one
        line creates it: a file holding a palette and no models is worse than none, and ``/config`` is what writes
        it. So on that machine the line names what brings the file rather than reporting a missing file as a
        failure, and the branch is chosen on *why* the write failed — a file that is not there, however deeply the
        error was wrapped — rather than on what the path looks like now.

        Args:
            what: The setting, as a noun phrase the sentence can start with ("theme nord", "the status line").
            error: What the write raised; anything not caused by a missing file is the caller's failure to report.
            applied: Whether the change is in force for this run. ``/theme`` and ``/pet`` apply before they write,
                so they are on now; the compaction default and the status line write first and are not, and their
                sentence must not claim a change the run does not have. ``/config`` writes the models, not this
                setting, so what it brings is the file the setting can be saved into.
        """
        if self.shell.model is not None or not _missing_file(error):
            return None
        path = self.shell.client.config_file
        if applied:
            return f"{what} is on for this run; it is kept for next time once `/config` writes {path}"
        return f"{what} is not saved; `/config` writes {path}, and it can be set again then"

    def _unkept(self, what: str, error: Exception, *, applied: bool) -> None:
        """Say what became of a setting the file could not keep: a notice on a fresh machine, else the failure.

        The failure follows ``applied`` for the same reason the fresh branch does: "will not be remembered" says
        the change is in force and only its memory failed, which is untrue of the pair that writes first.
        """
        unwritten = self._unwritten_config(what, error, applied=applied)
        if unwritten is not None:
            self.shell.transcript.notice(unwritten)
        elif applied:
            self.shell.transcript.error(f"{what} will not be remembered: {error}")
        else:
            self.shell.transcript.error(f"{what} is not saved: {error}")

    def _or_reason(self, what: str, error: Exception, *, applied: bool) -> str:
        """The sentence a command reports a failed setting with: the fresh machine's, or what became of it."""
        unwritten = self._unwritten_config(what, error, applied=applied)
        if unwritten is not None:
            return unwritten
        return f"{what} will not be remembered: {error}" if applied else f"{what} is not saved: {error}"

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
            except ConfigEditError as error:
                return CommandResult(message=self._or_reason("The status line", error, applied=False))
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(message=message, relayout=True)

        def apply(shown: dict[str, bool]) -> None:
            shell.close_page()
            try:
                shell.agent.remember_statusline(shown)
            except ConfigEditError as error:
                # Written before it applies, like the compaction default: the sentence says it is not saved.
                self._unkept("The status line", error, applied=False)
                return
            except ValueError as error:
                shell.transcript.error(str(error))
                return
            shell.transcript.notice(shell.agent.statusline_summary())

        # The program's own items are in the panel already; a plugin's are added beside them.
        extra = tuple(Part(item.name, item.summary) for item in shell.agent.turn_segments if item.name not in NAMES)
        page = StatuslinePage(shell.agent.statusline_hidden, extra, on_apply=apply, on_cancel=shell.close_page)
        return CommandResult(widget=bottom_panel(page, rows=statusline_rows(shell.app.height)))
