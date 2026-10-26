"""The slash commands that act on the application, written as ordinary plugins.

``/resume``, ``/model``, ``/context`` and the rest used to be methods of the shell. They are plugins now, for
the reason the shell's rows and the agent's extensions are: the shell asks the loaded plugins for what to show and
does not know which of it is its own, and a plugin that wants a command of this kind finds the way already laid.

A command that acts on the application is handed the shell through the context it runs with
(:meth:`~zettcode.app.commands.CommandContext.require_host`), typed as the narrow
:class:`~zettcode.app.commands.CommandHost` and not as the shell itself, so a plugin of anybody's can do what these
do without importing it. The words a command's completion menu offers are asked for before any command runs, so they
read the shell through :class:`~zettcode.app.plugins.host.HostLink` instead, which the shell attaches itself to.

What stays in the shell is what cannot be written against that interface yet: the commands that preview as they are
walked (``/theme``, ``/pet``) and the panels that edit a form of their own (``/config``, ``/statusline``,
``/self-compact``).
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path

from zettcode.app.commands import (
    COMMAND_ERRORS,
    CommandContext,
    CommandHost,
    CommandResult,
    Subcommand,
    subcommand_words,
)
from zettcode.paths import DEFAULT_COMMAND_HISTORY
from zettcode.tui import Widget

from .container import TerminalContainer
from .host import HOST_LINK, HostLink
from .plugin import TerminalPlugin

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
    from zettcode.app.ui.widgets import bottom_panel

    return bottom_panel(page, rows=PICKER_ROWS)


# -- the session ----------------------------------------------------------------------------------


class SessionCommands(TerminalPlugin):
    """``/resume``, ``/continue``, ``/fork``, ``/title`` and ``/context``: the session you are in and the ones before it."""

    name = "session-commands"
    description = "resume, continue, fork, title and context"

    def activate(self, container: TerminalContainer) -> None:
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
        from zettcode.app.ui.widgets import SessionsPage

        sessions = await host.client.sessions.list(limit=RESUME_LIMIT)
        if not sessions:
            return CommandResult(message="No persisted sessions.")
        try:
            found = await host.client.session_stats([session.id for session in sessions])
            stats = {item.id: item for item in found}
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
            current = host.client.session.title
            if current is None:
                return CommandResult(message="This session has no title yet. Use `/title <name>`.")
            return CommandResult(message=f"Title: **{current}**")
        try:
            renamed = await host.rename_session(context.argument)
        except COMMAND_ERRORS as error:
            return CommandResult(message=str(error))
        return CommandResult(notification=f"renamed to {renamed}", relayout=True)

    async def context(self, context: CommandContext) -> CommandResult:
        """Show what the next request carries, by source and token share.

        The breakdown comes from the request the runtime assembled for the last model call, so it needs one turn
        before it exists: before that there is nothing measured to show, and the panel would be a page of zeroes.
        """
        host = context.require_host()
        report = await host.client.session.context()
        if report is None:
            return CommandResult(
                message="No request yet \u2014 send one (or resume a session), then `/context` shows the breakdown."
            )

        # Imported here and not at the top: the panels import the agent, and the agent imports the plugins.
        from zettcode.app.ui.config_form import whole_if_whole
        from zettcode.app.ui.widgets import ContextPage

        def apply(percent: float) -> None:
            host.close_page()
            try:
                model, unwritten = host.client.use_compact_percent(percent)
            except COMMAND_ERRORS as error:
                host.transcript.error(str(error))
                return
            said = f"{model.name}: compacts at {whole_if_whole(model.compact_percent)}% of the window"
            said += f" ({round(model.context_window * model.compact_percent / 100):,} tokens)"
            if unwritten is None:
                host.transcript.notice(said)
            else:
                host.transcript.notice(f"{said} for this run; not remembered: {unwritten}")
            host.request_layout()

        model = host.client.model
        return CommandResult(
            widget=ContextPage(
                report,
                path=host.client.session.path,
                model=model.name,
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
    models = host.client.models
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
    return subcommand_words(("on", "off"), HARNESS_NOTES, "on" if host.client.harness else "off")


def permission_words(host: CommandHost | None) -> tuple[Subcommand, ...]:
    """Offer the four levels strictest first, each with what it does to a command and a mark on the one in force."""
    if host is None:
        return ()
    return subcommand_words(host.client.permissions, PERMISSION_NOTES, host.client.permission)


class ModelCommands(TerminalPlugin):
    """``/model``, ``/effort``, ``/permission`` and ``/harness``: what the next request runs on and how far it may go."""

    name = "model-commands"
    description = "model, effort, permission and harness"

    def activate(self, container: TerminalContainer) -> None:
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
        from zettcode.app.ui.widgets import ModelPage

        page = ModelPage(host.client, on_select=host.select_model, on_cancel=host.close_page)
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

        from zettcode.app.ui.widgets import EFFORT_ROWS, EffortPage, bottom_panel

        def select(level: str) -> None:
            # The page goes first: the header's gauge is for a reader looking at the header, and it is skipped
            # while a command holds the shell busy.
            host.close_page()
            try:
                host.change_effort(level)
            except ValueError as error:
                host.transcript.error(str(error))

        page = EffortPage(
            host.client.efforts,
            host.client.effort,
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
            host.client.use_harness(word == "on")
        state = "on" if host.client.harness else "off"
        notes = {
            "on": "The model can write Python tools and run them; they live in ~/.zettcode/harness. "
            "Starts with the next request.",
            "off": "The model has no harness.",
        }
        return CommandResult(message=f"Harness is {state}. {notes[state]}", relayout=bool(word))


# -- asking, and leaving ----------------------------------------------------------------------------


class SideQuestion(TerminalPlugin):
    """``/btw``: a question that does not join the conversation."""

    name = "side-question-command"
    description = "btw"

    def activate(self, container: TerminalContainer) -> None:
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


class HelpCommand(TerminalPlugin):
    """``/help``: the commands and the keys, whoever provides them."""

    name = "help-command"
    description = "help"

    def activate(self, container: TerminalContainer) -> None:
        """Register ``/help``; it only shows something, so it is safe beside a running request."""
        container.register_command("help", "show the commands and the keys", self.help, when_busy="now")

    async def help(self, context: CommandContext) -> CommandResult:
        """Describe every command the shell knows, whoever provides it."""
        from zettcode.app.ui.widgets import help_text

        return CommandResult(message=help_text(context.require_host().commands))


class BashCommand(TerminalPlugin):
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

    def activate(self, container: TerminalContainer) -> None:
        """Register ``/bash``; it neither reads nor writes the session, so it may open beside a request."""
        container.register_command(
            "bash", "run commands in a full-screen shell: /bash [command]", self.bash, when_busy="now"
        )

    async def bash(self, context: CommandContext) -> CommandResult:
        """Open the panel in the workspace, with the history of the reader's shells for Up and Tab."""
        from zettcode.app.commandline import CommandHistory, CommandRunner
        from zettcode.app.ui.widgets import BashPage

        host = context.require_host()
        history = CommandHistory(self.history_file or DEFAULT_COMMAND_HISTORY)
        # A shell history can be megabytes; reading it is not the event loop's to wait for.
        entries = await asyncio.to_thread(history.load)
        runner = CommandRunner(host.agent.runtime.config.workspace)
        page = BashPage(runner, history, entries, on_close=host.close_page, initial=context.argument)
        return CommandResult(widget=page)


class CodeReview(TerminalPlugin):
    """``/code-review``: ask for a review of the uncommitted changes, in this conversation."""

    name = "code-review-command"
    description = "code review"

    #: What the model is asked, in pieces: a preset for the turn, not a report about it. The reader gets the review
    #: as an answer they could have asked for by typing all of this themselves.
    INTRO = "Review the uncommitted changes in this workspace."
    COLLECT = (
        "Collect them first: `git status --short` for what changed, `git diff HEAD` for the patch, and the contents "
        "of any untracked file that belongs to the change."
    )
    #: The reviewer is a session of its own, at the shell level of the reader who asked — never above it, since
    #: nobody here approved anything. `{spawn}` is the whole line to run, so the model copies it rather than
    #: reassembling an alias.
    DAEMON = (
        "Have it read by a reviewer of its own, so this conversation keeps its context. `{command} list` shows the "
        "daemons running on this machine. If one is already there for this workspace — `code-review` is the name "
        "this command gives one — reuse it rather than starting another: it has read the earlier rounds and "
        "already knows this change, which makes it the better reviewer. Send it what you need with "
        '`send_message(to="<session id>", message=...)` — the request as you would put it, and that the change '
        "is the uncommitted diff this workspace holds, which it can collect itself. Only when there is none, run\n"
        "\n"
        "    {spawn}\n"
        "\n"
        "and take the session id it prints; it is recorded under the name `code-review`, so the next review in "
        "this workspace finds it.\n"
        "\n"
        "Say in that message, every round, that it must answer: send its findings back to you with `send_message`, "
        "and if it has nothing to change, say that in a word. A reviewer that goes quiet leaves the change "
        "waiting, and a review that found nothing cannot be told apart from one that never happened.\n"
        "\n"
        "Keep the reviewer running while you work on what it found: make the changes here, then send it the new "
        "state of the change for another look, and go round again until it has nothing left to say. A reviewer "
        "stopped after the first round cannot tell you whether the fix worked. If a round brings no answer at all, "
        "send the request once more; if that also goes unanswered, read what it did say: its conversation is "
        "`~/.zettcode/sessions/*/<session id>/data.jsonl`, and the last assistant message in it is its review — "
        "report that here, then stop it with `{command} kill <session id>` so that it is not left running. If a "
        "daemon cannot be started here, say why and do the review yourself."
    )
    #: A reviewer is told plainly what it is: the instruction is the safeguard, and the reader is told the same in
    #: the guide, since a session at `full` could change things if it chose to.
    NOT_YOURS = (
        "Tell the reviewer plainly that it reads and does not change: no edits, no writes, no commits, no command "
        "that modifies the workspace. The changes are yours to make, and you keep making them, round after round, "
        "until nothing it found is left."
    )
    #: Under `deny` there is no shell for a daemon to collect a diff with, and the session that asked has none
    #: either: the review is a reading one.
    ALONE = (
        "This session runs no shell commands, so neither the diff nor a daemon to read it can be gathered: review "
        "the files themselves with the reading tools, and say which ones you read."
    )
    SHAPE = (
        "In the review, name concrete problems with `file:line` — correctness, error handling, tests, naming — say "
        "what you would change and why, and do not restate the diff.\n"
        "\n"
        "What to pay attention to: {focus}"
    )

    #: The shell levels a reviewer may be started at. `ask` has no meaning in a process nobody sits at, so it is
    #: started `safe`: sandboxed, which is still more than a reader at `ask` has granted.
    LEVELS = {"full": "full", "safe": "safe", "ask": "safe"}

    def activate(self, container: TerminalContainer) -> None:
        """Register the command; it queues, since a review is a request like any other."""
        container.register_command(
            "code-review",
            "review the uncommitted changes: /code-review [what to look for]",
            self.review,
            when_busy="queue",
        )

    async def review(self, context: CommandContext) -> CommandResult:
        """Run the review as one turn, with what the reader typed as its focus.

        The command adds no work of its own: it writes the brief, hands it to `host.prompt`, and the ordinary turn
        does the rest — the echo in the transcript, the session, the streaming, the line it ends on. Nothing is
        gathered here, so the model decides what the review needs and how to get it.

        The transcript shows the command the reader typed, not the brief it stands for: the brief is what the model
        reads, and `shown` is what the conversation keeps.
        """
        host = context.require_host()
        argument = context.argument.strip()
        focus = argument or "anything that would make this change wrong or hard to keep"
        shown = f"/code-review {argument}" if argument else "/code-review"
        await host.prompt(self.brief(level=host.client.permission, focus=focus), shown=shown)
        return CommandResult()

    def brief(self, *, level: str, focus: str) -> str:
        """Return what the model reads, for a reader whose shell level is ``level``.

        The reviewer is started at the reader's own level (`ask` becoming `safe`, which is what a level that asks
        means in a process nobody can answer in), and not at all under `deny`.
        """
        command = self.command()
        parts = [self.INTRO, self.COLLECT]
        if level in self.LEVELS:
            spawn = f"{command} spawn --name code-review --permission {self.LEVELS[level]}"
            parts.append(self.DAEMON.format(command=command, spawn=spawn))
            parts.append(self.NOT_YOURS)
        else:
            parts.append(self.ALONE)
        parts.append(self.SHAPE.format(focus=focus))
        return "\n\n".join(parts)

    @staticmethod
    def command() -> str:
        """Return the command that runs this installation's daemon, quoted for the shell that will run it.

        `python -m zettcode.daemon` and the interpreter that is running this terminal: a checkout whose console
        script is not on the PATH, or a virtualenv nothing else can see, still works. The quoting follows the
        platform's shell, because a Windows path with a space cannot be passed the way POSIX quotes it.
        """
        argv = [sys.executable, "-m", "zettcode.daemon"]
        return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


class ShellControl(TerminalPlugin):
    """``/clear``, ``/quit`` and ``/exit``."""

    name = "shell-control"
    description = "clear and quit"

    def activate(self, container: TerminalContainer) -> None:
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
