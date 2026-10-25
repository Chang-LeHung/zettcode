"""The rows ZettCode ships with, written as an ordinary plugin.

Keeping the default header and status here — rather than inside
:class:`~zettcode.app.ui.app.ZettCodeApp` — is what leaves the shell with one
generic renderer: it asks the merged plugin bundle for each row side and paints
whatever comes back. The builtin registers its segments first, so a plugin that
overrides one of the same builders replaces it in place instead of adding a
second segment beside it.
"""

from __future__ import annotations

from zettcode.app.agent.conversation.presenters import BUILTIN_PRESENTERS
from zettcode.app.agent.conversation.pulse import activity_glyph
from zettcode.app.agent.conversation.text import (
    cache_text,
    calls_text,
    elapsed_text,
    speed_text,
    tokens_text,
    tools_text,
)
from zettcode.app.commands import CommandContext, CommandResult
from zettcode.app.pets import bundled_pets
from zettcode.app.ui import labels
from zettcode.app.ui.widgets import UsagePage
from zettcode.statusline import TURN_PARTS, Row, context_share, usage_parts
from zettcode.tui import STATUS, bundled_themes

from .builtin_commands import BashCommand, HelpCommand, ModelCommands, SessionCommands, ShellControl, SideQuestion
from .container import TerminalContainer
from .plugin import TerminalPlugin
from .state import ShellContext, TurnBuilder


class ShellRows(TerminalPlugin):
    """The header and status rows a reader expects out of the box."""

    name = "shell"

    def render_header_left(self, context: ShellContext) -> Row:
        """Label the app, the session (its title and the name others reach it by), and the workspace."""
        return labels.header_left(context.session.workspace, context.session.name, context.session.handle)

    def render_header_right(self, context: ShellContext) -> Row:
        """Show the model and the reasoning effort the next request will use."""
        return labels.header_right(context.model.name, context.model.effort)

    def render_status_left(self, context: ShellContext) -> Row:
        """Show the activity glyph, status word, mode, and token use; the session is in the header."""
        activity = context.activity
        counters = usage_parts(activity.usage)
        return labels.status_left(
            activity.label,
            icon=activity_glyph(activity.frame) if activity.busy else STATUS,
            permission=activity.permission,
            self_compact=activity.self_compact,
            ctx=context_share(activity.usage, context.model.config.context_window),
            **counters,
        )

    def render_status_right(self, context: ShellContext) -> Row:
        """List the keys worth remembering."""
        return labels.status_right()


class TurnLine(TerminalPlugin):
    """The items of the line a request ends on: how long it took, when, and what it spent.

    Each is a segment of its own, so a plugin can add one beside them or replace one by name, and each is a switch
    in ``/statusline``. Written as an ordinary plugin, like the header and status rows above.
    """

    name = "turn-line"

    def activate(self, container: TerminalContainer) -> None:
        """Register the items in the order they stand."""
        sentences = dict(TURN_PARTS)
        builders: dict[str, TurnBuilder] = {
            "turn-time": lambda turn: f"{turn.label} for {elapsed_text(turn.seconds)}",
            "turn-clock": lambda turn: turn.clock,
            "turn-tokens": lambda turn: tokens_text(turn.usage),
            "turn-cache": lambda turn: cache_text(turn.usage),
            "turn-calls": lambda turn: calls_text(turn.usage),
            "turn-speed": lambda turn: speed_text(turn.usage),
            "turn-tools": lambda turn: tools_text(turn.tools, turn.failed_tools),
        }
        for name, builder in builders.items():
            container.register_turn_segment(name, sentences[name], builder)


class UsageCommand(TerminalPlugin):
    """``/usage``: what this workspace's sessions have spent, by model, session and day.

    The numbers are read back from the stored conversations, so the page covers every
    session of the workspace, not only the one open, and an hour from now it will still
    agree with the files. It only reads, so it may run beside a request.
    """

    name = "usage"

    def activate(self, container: TerminalContainer) -> None:
        """Register ``/usage``; the client keeps one reader, so a second look re-reads only what changed."""
        config = container.config

        async def show(context: CommandContext) -> CommandResult:
            """Open the usage page, or say that nothing has been spent yet."""
            ledger = await context.require_host().client.usage_ledger()
            if ledger.total.requests == 0:
                return CommandResult(message="No model replies are recorded in this workspace yet.")
            return CommandResult(widget=UsagePage(ledger, workspace=labels.compact_path(config.workspace, limit=None)))

        container.register_command("usage", "Token use by model, by session and by day", show, when_busy="now")


class BuiltinThemes(TerminalPlugin):
    """The palettes that ship with the program, offered the way any plugin offers one.

    They are TOML files beside the theme loader, so adding a built-in palette is adding a file and a name to
    ``BUNDLED``; nothing here knows what a palette looks like. They are registered first, so they are listed first
    in the ``/theme`` menu, and a plugin cannot register a name they hold.
    """

    name = "themes"

    def activate(self, container: TerminalContainer) -> None:
        """Offer each palette file by name. Nothing is read until one is asked for."""
        for source in bundled_themes():
            container.register_theme(source.name, source.load, description=source.description)


class BuiltinPets(TerminalPlugin):
    """The pets that ship with the program, offered the way any plugin offers one.

    They are registered first, so they are listed first in the ``/pet`` menu, and a plugin cannot register a name
    they hold. Adding a built-in pet is adding a module beside the others and its name to ``BUNDLED``; nothing
    here knows what a pet looks like.
    """

    name = "pets"

    def activate(self, container: TerminalContainer) -> None:
        """Offer each pet by name. Nothing is built until one is asked for."""
        for source in bundled_pets():
            container.register_pet(source.name, source.load, description=source.description)


class BuiltinPresenters(TerminalPlugin):
    """How the program draws its own rows, offered the way any plugin offers a presenter.

    They register first, at the class's own priority, which is the lowest there is, so a plugin that
    draws the same kind or family wins without having to outrank them; a plugin that registers
    nothing leaves exactly the rows the program has always drawn. Adding a built-in kind of row is
    adding a presenter to ``BUNDLED`` in the conversation and nothing here.
    """

    name = "presenters"

    def activate(self, container: TerminalContainer) -> None:
        """Register every built-in presenter at the priority its class declares."""
        for presenter in BUILTIN_PRESENTERS:
            container.register_presenter(presenter)


#: Plugins loaded from the repository itself, never from a distribution. The agent-side ones, which build on
#: state the runtime hands over, are :data:`~zettcode.engine.plugins.builtin_agent.AGENT_PLUGINS`.
BUILTIN_PLUGINS: tuple[TerminalPlugin, ...] = (
    ShellRows(),
    # The commands that act on the application, in the order ``/help`` lists them.
    HelpCommand(),
    SessionCommands(),
    ModelCommands(),
    SideQuestion(),
    BashCommand(),
    ShellControl(),
    TurnLine(),
    UsageCommand(),
    BuiltinThemes(),
    BuiltinPets(),
    BuiltinPresenters(),
)
