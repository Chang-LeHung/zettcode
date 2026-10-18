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

from zettcode.config_edit import ConfigEditError
from zettcode.tui import Widget

from ..commands import Command, CommandContext, CommandProvider, CommandResult, Subcommand
from .config_form import whole_if_whole
from .widgets import (
    EFFORT_ROWS,
    SELF_COMPACT_ROWS,
    ContextPage,
    EffortPage,
    ModelPage,
    PetPage,
    SelfCompactPage,
    SessionsPage,
    StatuslinePage,
    bottom_panel,
    help_text,
    pet_rows,
    statusline_rows,
)

#: Rows the picker panels take from the bottom of the screen: the title, the
#: list, and the footer hint. The handler owns the number; nothing in the
#: framework reads it.
PICKER_ROWS = 14

#: One-line description per built-in palette, shown next to its name.
THEME_NOTES = {
    "dark": "green-leaning palette for dark terminals",
    "light": "green-leaning palette for light terminals",
}

#: One-line note per shell-permission level, shown next to its name in the menu.
#: They say what happens to a command, because the names alone do not: `safe` in
#: particular is a promise about what a command can do, not about what it can read.
PERMISSION_NOTES = {
    "deny": "no shell commands run; the model is told and carries on without",
    "ask": "each command waits for your answer (the default)",
    "safe": "commands that only read run; anything else asks",
    "auto": "every command runs without asking",
}

#: One-line note per reasoning level, shown next to its name in the menu.
EFFORT_NOTES = {
    "off": "no deliberate reasoning",
    "minimal": "a token of thought, fastest",
    "low": "quick answers",
    "medium": "the default balance",
    "high": "more thought on hard problems",
    "xhigh": "a long think on hard problems",
    "max": "the highest budget the provider takes",
    "ultra": "above max; a provider maps it down when it must",
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
    """The commands the shell adds around the agent's own.

    It is one provider among several: the shell merges it with the agent's
    commands and the plugins' through a registry, so every source of commands is
    the same shape and the first to claim a name wins.
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
            # model's compaction is sized to - stays refused: /model, /config, /clear, /new, /resume,
            # /fork, /compact and /export.
            Command("/help", "show the commands and the keys", "app", self.help, when_busy="now"),
            Command("/resume", "resume a session: /resume [id]", "app", self.resume),
            Command("/continue", "carry on a request that was cut short", "app", self.continue_),
            Command("/model", "choose a model", "app", self.model, subcommands=self.model_words),
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
            Command("/fork", "carry this conversation into a new session", "app", self.fork),
            Command("/context", "what is filling the context window", "app", self.context, when_busy="now"),
            Command("/title", "name this session: /title <name>", "app", self.title, when_busy="now"),
            Command(
                "/effort",
                "how much the model reasons: /effort high",
                "app",
                self.effort,
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
            Command(
                "/permission",
                "how much of the shell may run unasked: /permission safe",
                "app",
                self.permission,
                when_busy="now",
                subcommands=lambda: self._words(
                    self.shell.agent.permissions, PERMISSION_NOTES, self.shell.agent.permission.value
                ),
            ),
            Command(
                "/btw",
                "ask something that will not join the conversation: /btw <question>",
                "app",
                self.btw,
                # The one command worth taking mid-reply: it is how a reader
                # asks about what is on screen while it is still arriving.
                when_busy="queue",
            ),
            Command("/clear", "clear the transcript", "app", self.clear),
            Command("/quit", "exit", "app", self.quit, when_busy="now"),
            Command("/exit", "exit, same as /quit", "app", self.quit, when_busy="now"),
        )

    @staticmethod
    def _words(names: Sequence[str], notes: dict[str, str], current: str = "") -> tuple[Subcommand, ...]:
        """Offer each name a command takes, with its note and a mark on the one in force."""
        return tuple(Subcommand(name, notes.get(name, ""), current=name == current) for name in names)

    def _offer(self, command: str) -> CommandResult:
        """Put the command and a space in the draft, which opens the menu of the words it takes.

        A command that is a choice among a few fixed words has no page of its own: the menu is the choice,
        so typing the bare command only moves the reader to it.
        """
        self.shell.composer.set_text(f"{command} ")
        return CommandResult()

    def theme_words(self) -> tuple[Subcommand, ...]:
        """Offer every palette by name: the built-in ones, then the plugins' and the reader's own, with their notes."""
        catalog = self.shell.agent.themes
        notes = {**THEME_NOTES, **catalog.notes()}
        return self._words(catalog.names(), notes, self.shell.app.theme.name)

    def model_words(self) -> tuple[Subcommand, ...]:
        """Offer the configured models by the name ``/model`` accepts.

        A name two entries share is left out (``/model`` refuses it as ambiguous), and so is one with a space
        in it, which would not stay one word.
        """
        models = self.shell.agent.models
        shown = [model.display_model or model.model for model in models]
        return tuple(
            Subcommand(name, model.model)
            for name, model in zip(shown, models, strict=True)
            if shown.count(name) == 1 and not any(character.isspace() for character in name)
        )

    async def help(self, context: CommandContext) -> CommandResult:
        """Describe commands from both the shell and the agent."""
        return CommandResult(message=help_text(self.shell.commands))

    async def model(self, context: CommandContext) -> CommandResult:
        """Open the model picker, or switch directly to a named model.

        The picker is a widget, so the command lives with the shell: the agent
        owns the models, the shell owns the widget that chooses between them.
        """
        if context.argument:
            self.shell.change_model(context.argument)
            return CommandResult(relayout=True)
        page = ModelPage(self.shell.agent, on_select=self.shell.select_model, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    async def config(self, context: CommandContext) -> CommandResult:
        """Open the model list, or act on it from one line.

        With nothing after it the command opens the panel, which asks one question at a time and
        is the way to type a token without it being echoed. The words after it do the same job
        on one line: ``add`` takes a provider and whatever of its settings the line gives, and
        asks for the rest; ``remove`` takes a number or a name; ``list`` and ``providers`` only
        show. A refusal — a bad address, a file that cannot be edited — is the command's error and
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

    async def resume(self, context: CommandContext) -> CommandResult:
        """Open the stored sessions, or resume the one named in the argument.

        The picker is a widget, so the command lives with the shell: the agent
        owns the stored sessions, the shell owns the widget that browses them —
        and the same call opens the session `--resume` names on the command line.
        """
        if context.argument:
            await self.shell.resume_session(context.argument)
            return CommandResult(notification=f"resumed session {context.argument[:8]}", relayout=True)
        sessions = await self.shell.agent.list_sessions(limit=20)
        if not sessions:
            return CommandResult(message="No persisted sessions.")
        page = SessionsPage(sessions, on_select=self.shell.select_session, on_cancel=self.shell.close_page)
        return CommandResult(widget=self._panel(page))

    def _panel(self, page: Widget) -> Widget:
        """Wrap one picker in the bottom panel the shell's own commands use."""
        return bottom_panel(page, rows=PICKER_ROWS)

    async def fork(self, context: CommandContext) -> CommandResult:
        """Copy what this conversation carries into a new session and continue there.

        The copy lands in a session of its own so the reader can take a different
        direction without losing the conversation that got them here, which stays
        where it is: nothing about the session being left is written.
        """
        # The line the fork leaves in the conversation is the report: it names the
        # session, and both commands that reopen it. A toast above the composer would
        # be the same news twice, in less detail.
        await self.shell.fork_session()
        return CommandResult(relayout=True)

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
        return CommandResult(relayout=True, notification=f"theme {name} — remembered for next time")

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
            return f"pet {name} — remembered, but the pet is hidden: /statusline show pet"
        return f"pet {name} — remembered for next time"

    async def context(self, context: CommandContext) -> CommandResult:
        """Show what the next request carries, by source and token share.

        The breakdown comes from the request the runtime assembled for the last
        model call, so it needs one turn before it exists: before that there is
        nothing measured to show, and the panel would be a page of zeroes.
        """
        shell = self.shell
        report = await shell.agent.context_report()
        if report is None:
            return CommandResult(
                message="No request yet \u2014 send one (or resume a session), then `/context` shows the breakdown."
            )

        def apply(percent: float) -> None:
            shell.close_page()
            try:
                model, unwritten = shell.agent.change_compact_percent(percent)
            except ValueError as error:
                shell.transcript.error(str(error))
                return
            said = f"{model.shown_name}: compacts at {whole_if_whole(model.compact_percent)}% of the window"
            said += f" ({model.compaction_max_tokens:,} tokens)"
            if unwritten is None:
                shell.transcript.notice(said)
            else:
                shell.transcript.notice(f"{said} for this run; not remembered: {unwritten}")
            shell.app.request_layout()

        model = shell.agent.active_model
        return CommandResult(
            widget=ContextPage(
                report,
                path=shell.agent.session_path(),
                model=model.shown_name,
                trigger=model.compaction_max_tokens,
                compact_percent=model.compact_percent,
                on_apply=apply,
                on_cancel=shell.close_page,
            )
        )

    async def title(self, context: CommandContext) -> CommandResult:
        """Rename the active session, or report the name it already has.

        The name lives in the session metadata beside the title the agent
        summarizes, so `/sessions` shows it and a later automatic naming step
        leaves it alone.
        """
        if not context.argument:
            current = self.shell.agent.session_title
            if current is None:
                return CommandResult(message="This session has no title yet. Use `/title <name>`.")
            return CommandResult(message=f"Title: **{current}**")
        try:
            renamed = await self.shell.rename_session(context.argument)
        except ValueError as error:
            return CommandResult(message=str(error))
        return CommandResult(notification=f"renamed to {renamed}", relayout=True)

    async def effort(self, context: CommandContext) -> CommandResult:
        """Switch straight to a named level, or open the panel with a knob on a rail.

        The levels are the runtime's own, so the panel lists what the provider adapters can actually
        send rather than a hand-written list. The arrow keys only slide the knob; Enter applies the level
        under it, which is when the header plays its gauge and the transcript says so. Escape applies nothing.
        """
        if context.argument:
            try:
                self.shell.change_effort(context.argument)
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(relayout=True)
        shell = self.shell

        def select(level: str) -> None:
            # The page goes first: the header's gauge is for a reader looking at the header, and it is
            # skipped while a command holds the shell busy.
            shell.close_page()
            try:
                shell.change_effort(level)
            except ValueError as error:
                shell.transcript.error(str(error))

        page = EffortPage(
            shell.agent.efforts,
            shell.agent.effort,
            notes=EFFORT_NOTES,
            on_select=select,
            on_cancel=shell.close_page,
        )
        return CommandResult(widget=bottom_panel(page, rows=EFFORT_ROWS))

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
                (lambda: agent.use_self_compaction(choice), choice != agent.self_compaction_choice),
            ):
                if not needed:
                    continue
                try:
                    change()
                except ValueError as error:
                    shell.transcript.error(str(error))
            shell.transcript.notice(shell.agent.self_compaction_summary())

        page = SelfCompactPage(
            shell.agent.self_compaction_choice,
            shell.agent.self_compaction_default,
            on_apply=apply,
            on_cancel=shell.close_page,
            session_open=not shell.agent.session_locked,
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

    async def permission(self, context: CommandContext) -> CommandResult:
        """Set a named level straight away, or open the menu of the levels.

        The menu lists the four levels strictest first, and each says what happens to a command rather than
        what the level is called. The level governs the shell tool only; the file and MCP tools are not
        behind a prompt in this application, so nobody should read ``deny`` as a read-only mode for the
        workspace.
        """
        if context.argument:
            try:
                self.shell.change_permission(context.argument)
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(relayout=True)
        return self._offer("/permission")

    async def clear(self, context: CommandContext) -> CommandResult:
        """Clear visible conversation entries."""
        self.shell.transcript.clear()
        return CommandResult()

    async def btw(self, context: CommandContext) -> CommandResult:
        """Ask a side question: answered here, and kept out of the conversation.

        The answer is shown in the transcript like any other, but the store
        records the exchange as one the model is never given back, and the tools
        are the reading ones — see :mod:`zettcode.app.agent.dialogue.side`. Declaring
        itself queue-worthy is what lets the command be typed during a reply:
        the answer then waits its turn like any other request.

        A session another process has open takes none: the store records the exchange, which is a write, and
        the question is refused before it is echoed rather than shown and then failed.
        """
        self.shell.agent.require_session()
        await self.shell.run_side_question(context.argument)
        return CommandResult()

    async def continue_(self, context: CommandContext) -> CommandResult:
        """Carry on the request that was interrupted — stopped, cut off, failed — from where it stopped.

        ``/resume`` opens an earlier *session*; this picks up the *request* that did not finish in this one. Having
        nothing to continue is not an error: the reader is told why (the last request finished; the model declined
        and would again; the context window is full), which is the useful part of asking.
        """
        self.shell.agent.require_session()
        await self.shell.run_continue()
        return CommandResult()

    async def quit(self, context: CommandContext) -> CommandResult:
        """Exit the terminal application."""
        self.shell.app.exit()
        return CommandResult()
