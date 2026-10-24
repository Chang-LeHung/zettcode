"""The slash commands that act on the application, written as ordinary plugins.

``/resume``, ``/model``, ``/context`` and the rest used to be methods of the shell. They are plugins now, for
the reason the shell's rows and the agent's extensions are: the shell asks the loaded plugins for what to show and
does not know which of it is its own, and a plugin that wants a command of this kind finds the way already laid.

A command that acts on the application is handed the shell through the context it runs with
(:meth:`~zettcode.app.commands.CommandContext.require_host`), typed as the narrow
:class:`~zettcode.app.commands.CommandHost` and not as the shell itself, so a plugin of anybody's can do what these
do without importing it. The words a command's completion menu offers are asked for before any command runs, so they
read the shell through :class:`~zettcode.plugins.services.HostLink` instead, which the shell attaches itself to.

What stays in the shell is what cannot be written against that interface yet: the commands that preview as they are
walked (``/theme``, ``/pet``) and the panels that edit a form of their own (``/config``, ``/statusline``,
``/self-compact``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..app.commands import CommandContext, CommandHost, CommandResult, Subcommand, subcommand_words
from ..paths import DEFAULT_COMMAND_HISTORY
from ..tui import Widget
from .container import PluginContainer
from .plugin import Plugin
from .services import HOST_LINK, HostLink

#: Rows the picker panels take from the bottom of the screen: the title, the list, and the footer hint. The
#: handler owns the number; nothing in the framework reads it.
PICKER_ROWS = 14

#: Sessions the ``/resume`` panel lists.
RESUME_LIMIT = 20

#: One-line note per shell-permission level, shown next to its name in the menu. They say what happens to a command,
#: because the names alone do not: `safe` in particular is a promise about what a command can do, not about what it
#: can read.
PERMISSION_NOTES = {
    "deny": "no shell commands run; the model is told and carries on without",
    "ask": "each command waits for your answer (the default)",
    "safe": "every command runs in a sandbox: writes only the workspace and /tmp, no network",
    "full": "every command runs with your own access, without asking",
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


def _panel(page: Widget) -> Widget:
    """Wrap one picker in the bottom panel these commands share."""
    from ..app.ui.widgets import bottom_panel

    return bottom_panel(page, rows=PICKER_ROWS)


# -- the session ----------------------------------------------------------------------------------


class SessionCommands(Plugin):
    """``/resume``, ``/continue``, ``/fork``, ``/title`` and ``/context``: the session you are in and the ones before it."""

    name = "session-commands"
    description = "resume, continue, fork, title and context"

    def activate(self, container: PluginContainer) -> None:
        """Register the five commands."""
        container.register_command("resume", "resume a session: /resume [id]", self.resume)
        container.register_command("continue", "carry on a request that was cut short", self.continue_)
        container.register_command("fork", "carry this conversation into a new session", self.fork)
        container.register_command("context", "what is filling the context window", self.context, when_busy="now")
        container.register_command("title", "name this session: /title <name>", self.title, when_busy="now")

    async def resume(self, context: CommandContext) -> CommandResult:
        """Open the stored sessions with what each holds, or resume the one named in the argument.

        The picker is a widget, so the command needs the shell; the agent owns the stored sessions and the
        totals beside them. The same call opens the session `--resume` names on the command line. A store whose
        totals cannot be read still lists its sessions, only without the figures.
        """
        host = context.require_host()
        if context.argument:
            await host.resume_session(context.argument)
            return CommandResult(notification=f"resumed session {context.argument[:8]}", relayout=True)
        from ..app.ui.widgets import SessionsPage

        sessions = await host.agent.list_sessions(limit=RESUME_LIMIT)
        if not sessions:
            return CommandResult(message="No persisted sessions.")
        try:
            stats = await host.agent.session_stats(sessions)
        except Exception as error:  # noqa: BLE001 - the figures are a courtesy; a list without them is still a list
            context.ui.notice(f"Session totals unavailable: {error}")
            stats = None
        page = SessionsPage(sessions, stats=stats, on_select=host.select_session, on_cancel=host.close_page)
        return CommandResult(widget=_panel(page))

    async def continue_(self, context: CommandContext) -> CommandResult:
        """Carry on the request that was interrupted \u2014 stopped, cut off, failed \u2014 from where it stopped.

        ``/resume`` opens an earlier *session*; this picks up the *request* that did not finish in this one. Having
        nothing to continue is not an error: the reader is told why (the last request finished; the model declined
        and would again; the context window is full), which is the useful part of asking.
        """
        host = context.require_host()
        host.agent.require_session()
        await host.run_continue()
        return CommandResult()

    async def fork(self, context: CommandContext) -> CommandResult:
        """Copy what this conversation carries into a new session and continue there.

        The copy lands in a session of its own so the reader can take a different direction without losing the
        conversation that got them here, which stays where it is: nothing about the session being left is written.
        """
        # The line the fork leaves in the conversation is the report: it names the session, and both commands that
        # reopen it. A toast above the composer would be the same news twice, in less detail.
        await context.require_host().fork_session()
        return CommandResult(relayout=True)

    async def title(self, context: CommandContext) -> CommandResult:
        """Rename the active session, or report the name it already has.

        The name lives in the session metadata beside the title the agent summarizes, so `/resume` shows it and a
        later automatic naming step leaves it alone.
        """
        host = context.require_host()
        if not context.argument:
            current = host.agent.session_title
            if current is None:
                return CommandResult(message="This session has no title yet. Use `/title <name>`.")
            return CommandResult(message=f"Title: **{current}**")
        try:
            renamed = await host.rename_session(context.argument)
        except ValueError as error:
            return CommandResult(message=str(error))
        return CommandResult(notification=f"renamed to {renamed}", relayout=True)

    async def context(self, context: CommandContext) -> CommandResult:
        """Show what the next request carries, by source and token share.

        The breakdown comes from the request the runtime assembled for the last model call, so it needs one turn
        before it exists: before that there is nothing measured to show, and the panel would be a page of zeroes.
        """
        host = context.require_host()
        report = await host.agent.context_report()
        if report is None:
            return CommandResult(
                message="No request yet \u2014 send one (or resume a session), then `/context` shows the breakdown."
            )

        # Imported here and not at the top: the panels import the agent, and the agent imports the plugins.
        from ..app.ui.config_form import whole_if_whole
        from ..app.ui.widgets import ContextPage

        def apply(percent: float) -> None:
            host.close_page()
            try:
                model, unwritten = host.agent.change_compact_percent(percent)
            except ValueError as error:
                host.transcript.error(str(error))
                return
            said = f"{model.shown_name}: compacts at {whole_if_whole(model.compact_percent)}% of the window"
            said += f" ({model.compaction_max_tokens:,} tokens)"
            if unwritten is None:
                host.transcript.notice(said)
            else:
                host.transcript.notice(f"{said} for this run; not remembered: {unwritten}")
            host.request_layout()

        model = host.agent.active_model
        return CommandResult(
            widget=ContextPage(
                report,
                path=host.agent.session_path(),
                model=model.shown_name,
                trigger=model.compaction_max_tokens,
                compact_percent=model.compact_percent,
                on_apply=apply,
                on_cancel=host.close_page,
            )
        )


# -- the model ------------------------------------------------------------------------------------


def model_words(host: CommandHost | None) -> tuple[Subcommand, ...]:
    """Offer the configured models by the name ``/model`` accepts.

    A name two entries share is left out (``/model`` refuses it as ambiguous), and so is one with a space in it,
    which would not stay one word. Before there is a shell there is nothing to offer.
    """
    if host is None:
        return ()
    models = host.agent.models
    shown = [model.display_model or model.model for model in models]
    return tuple(
        Subcommand(name, model.model)
        for name, model in zip(shown, models, strict=True)
        if shown.count(name) == 1 and not any(character.isspace() for character in name)
    )


#: The two words ``/harness`` takes, with what each does.
HARNESS_NOTES = {
    "on": "the model may write small Python tools of its own and run them",
    "off": "the model has no harness (the default)",
}


def harness_words(host: CommandHost | None) -> tuple[Subcommand, ...]:
    """Offer ``on`` and ``off``, with a mark on the one in force."""
    if host is None:
        return ()
    return subcommand_words(("on", "off"), HARNESS_NOTES, "on" if host.agent.harness else "off")


def permission_words(host: CommandHost | None) -> tuple[Subcommand, ...]:
    """Offer the four levels strictest first, each with what it does to a command and a mark on the one in force."""
    if host is None:
        return ()
    return subcommand_words(host.agent.permissions, PERMISSION_NOTES, host.agent.permission.value)


class ModelCommands(Plugin):
    """``/model``, ``/effort``, ``/permission`` and ``/harness``: what the next request runs on and how far it may go."""

    name = "model-commands"
    description = "model, effort, permission and harness"

    def activate(self, container: PluginContainer) -> None:
        """Register the commands; the ones that are a choice among words read the shell for those words."""
        # A container built by hand has no link to follow; the menus then offer no words, and the commands still run.
        link = container.find(HOST_LINK, HostLink) or HostLink()
        container.register_command("model", "choose a model", self.model, subcommands=lambda: model_words(link.host))
        container.register_command("effort", "how much the model reasons: /effort high", self.effort, when_busy="now")
        container.register_command(
            "permission",
            "how much of the shell may run unasked: /permission safe",
            self.permission,
            when_busy="now",
            subcommands=lambda: permission_words(link.host),
        )
        container.register_command(
            "harness",
            "let the model write and run its own tools: /harness on|off",
            self.harness,
            when_busy="refuse",
            subcommands=lambda: harness_words(link.host),
        )

    async def model(self, context: CommandContext) -> CommandResult:
        """Open the model picker, or switch directly to a named model.

        The picker is a widget, so the command needs the shell: the agent owns the models, the shell owns the
        widget that chooses between them.
        """
        host = context.require_host()
        if context.argument:
            host.change_model(context.argument)
            return CommandResult(relayout=True)
        from ..app.ui.widgets import ModelPage

        page = ModelPage(host.agent, on_select=host.select_model, on_cancel=host.close_page)
        return CommandResult(widget=_panel(page))

    async def effort(self, context: CommandContext) -> CommandResult:
        """Switch straight to a named level, or open the panel with a knob on a rail.

        The levels are the runtime's own, so the panel lists what the provider adapters can actually send rather
        than a hand-written list. The arrow keys only slide the knob; Enter applies the level under it, which is
        when the header plays its gauge and the transcript says so. Escape applies nothing.
        """
        host = context.require_host()
        if context.argument:
            try:
                host.change_effort(context.argument)
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(relayout=True)

        from ..app.ui.widgets import EFFORT_ROWS, EffortPage, bottom_panel

        def select(level: str) -> None:
            # The page goes first: the header's gauge is for a reader looking at the header, and it is skipped
            # while a command holds the shell busy.
            host.close_page()
            try:
                host.change_effort(level)
            except ValueError as error:
                host.transcript.error(str(error))

        page = EffortPage(
            host.agent.efforts,
            host.agent.effort,
            notes=EFFORT_NOTES,
            on_select=select,
            on_cancel=host.close_page,
        )
        return CommandResult(widget=bottom_panel(page, rows=EFFORT_ROWS))

    async def permission(self, context: CommandContext) -> CommandResult:
        """Set a named level straight away, or open the menu of the levels.

        The menu lists the four levels strictest first, and each says what happens to a command rather than what
        the level is called. The level governs the shell tool only; the file and MCP tools are not behind a prompt
        in this application, so nobody should read ``deny`` as a read-only mode for the workspace.
        """
        host = context.require_host()
        if context.argument:
            try:
                host.change_permission(context.argument)
            except ValueError as error:
                return CommandResult(message=str(error))
            return CommandResult(relayout=True)
        host.offer("/permission")
        return CommandResult()

    async def harness(self, context: CommandContext) -> CommandResult:
        """Turn the just-in-time harness on or off, or say which it is.

        Refused while a request runs: the harness's tools are mounted when a request starts, so a change made
        halfway would be announced and not be true until the next one.
        """
        host = context.require_host()
        word = context.argument.strip().lower()
        if word not in ("", "on", "off"):
            return CommandResult(message="Usage: /harness on|off")
        if word:
            host.agent.use_harness(word == "on")
        state = "on" if host.agent.harness else "off"
        notes = {
            "on": "The model can write Python tools and run them; they live in ~/.zettcode/harness. "
            "Starts with the next request.",
            "off": "The model has no harness.",
        }
        return CommandResult(message=f"Harness is {state}. {notes[state]}", relayout=bool(word))


# -- asking, and leaving ----------------------------------------------------------------------------


class SideQuestion(Plugin):
    """``/btw``: a question that does not join the conversation."""

    name = "side-question-command"
    description = "btw"

    def activate(self, container: PluginContainer) -> None:
        """Register ``/btw``; it is the one command worth taking mid-reply, so it queues."""
        container.register_command(
            "btw",
            "ask something that will not join the conversation: /btw <question>",
            self.btw,
            # How a reader asks about what is on screen while it is still arriving.
            when_busy="queue",
        )

    async def btw(self, context: CommandContext) -> CommandResult:
        """Ask a side question: answered here, and kept out of the conversation.

        The answer is shown in the transcript like any other, but the store records the exchange as one the model
        is never given back, and the tools are the reading ones \u2014 see :mod:`zettcode.engine.dialogue.side`.
        Declaring itself queue-worthy is what lets the command be typed during a reply: the answer then waits its
        turn like any other request.

        A session another process has open takes none: the store records the exchange, which is a write, and the
        question is refused before it is echoed rather than shown and then failed.
        """
        host = context.require_host()
        host.agent.require_session()
        await host.run_side_question(context.argument)
        return CommandResult()


class HelpCommand(Plugin):
    """``/help``: the commands and the keys, whoever provides them."""

    name = "help-command"
    description = "help"

    def activate(self, container: PluginContainer) -> None:
        """Register ``/help``; it only shows something, so it is safe beside a running request."""
        container.register_command("help", "show the commands and the keys", self.help, when_busy="now")

    async def help(self, context: CommandContext) -> CommandResult:
        """Describe every command the shell knows, whoever provides it."""
        from ..app.ui.widgets import help_text

        return CommandResult(message=help_text(context.require_host().commands))


class BashCommand(Plugin):
    """``/bash``: a full-screen command line over the workspace.

    ``/bash`` opens it empty and ``/bash <command>`` opens it already running that command. It is the reader's
    own shell run by the reader's own hand, so it asks no permission and shows nothing to the model; what it prints
    stays on its screen and is gone when the page closes.

    Args:
        history_file: Where the commands typed in the panel are kept; ``~/.zettcode/command_history`` by default.
    """

    name = "bash-command"
    description = "a shell panel"

    def __init__(self, history_file: Path | None = None) -> None:
        self.history_file = history_file

    def activate(self, container: PluginContainer) -> None:
        """Register ``/bash``; it neither reads nor writes the session, so it may open beside a request."""
        container.register_command(
            "bash", "run commands in a full-screen shell: /bash [command]", self.bash, when_busy="now"
        )

    async def bash(self, context: CommandContext) -> CommandResult:
        """Open the panel in the workspace, with the history of the reader's shells for Up and Tab."""
        from ..app.commandline import CommandHistory, CommandRunner
        from ..app.ui.widgets import BashPage

        host = context.require_host()
        history = CommandHistory(self.history_file or DEFAULT_COMMAND_HISTORY)
        # A shell history can be megabytes; reading it is not the event loop's to wait for.
        entries = await asyncio.to_thread(history.load)
        runner = CommandRunner(host.agent.runtime.config.workspace)
        page = BashPage(runner, history, entries, on_close=host.close_page, initial=context.argument)
        return CommandResult(widget=page)


class ShellControl(Plugin):
    """``/clear``, ``/quit`` and ``/exit``."""

    name = "shell-control"
    description = "clear and quit"

    def activate(self, container: PluginContainer) -> None:
        """Register the three commands; leaving does not wait for the answer."""
        container.register_command("clear", "clear the transcript", self.clear)
        container.register_command("quit", "exit", self.quit, when_busy="now")
        container.register_command("exit", "exit, same as /quit", self.quit, when_busy="now")

    async def clear(self, context: CommandContext) -> CommandResult:
        """Clear visible conversation entries."""
        context.require_host().transcript.clear()
        return CommandResult()

    async def quit(self, context: CommandContext) -> CommandResult:
        """Exit the terminal application."""
        context.require_host().quit()
        return CommandResult()
