"""The rows ZettCode ships with, written as an ordinary plugin.

Keeping the default header and status here — rather than inside
:class:`~zettcode.app.ui.app.ZettCodeApp` — is what leaves the shell with one
generic renderer: it asks the merged plugin bundle for each row side and paints
whatever comes back. The builtin registers its segments first, so a plugin that
overrides one of the same builders replaces it in place instead of adding a
second segment beside it.
"""

from __future__ import annotations

import asyncio

from ..app.agent.conversation.rows import activity_glyph
from ..app.agent.dialogue.mentions import FileMentions, SkillMentions
from ..app.agent.extensions.usage import context_text, usage_text
from ..app.agent.storage.ledger import LedgerReader
from ..app.commands import CommandContext, CommandResult
from ..app.ui import labels
from ..app.ui.widgets import UsagePage
from ..tui import SEPARATOR, STATUS
from .container import PluginContainer
from .plugin import Plugin
from .state import ShellContext


class ShellRows(Plugin):
    """The header and status rows a reader expects out of the box."""

    name = "shell"

    def render_header_left(self, context: ShellContext) -> str:
        """Label the app, the session (its title and the name others reach it by), and the workspace."""
        return labels.header_left(context.session.workspace, context.session.name, context.session.handle)

    def render_header_right(self, context: ShellContext) -> str:
        """Show the model and the reasoning effort the next request will use."""
        return labels.header_right(context.model.name, context.model.effort)

    def render_status_left(self, context: ShellContext) -> str:
        """Show the activity glyph, status word, mode, and token use; the session is in the header."""
        activity = context.activity
        icon = activity_glyph(activity.frame) if activity.busy else STATUS
        mode = f" {SEPARATOR} {activity.permission}" if activity.permission != "ask" else ""
        used = context_text(activity.usage, context.model.config.context_window)
        label = f"{activity.label}{mode}"
        return f"  {icon} {label}{usage_text(activity.usage)}{used}"

    def render_status_right(self, context: ShellContext) -> str:
        """List the keys worth remembering."""
        return labels.status_right()


class SkillResources(Plugin):
    """The builtin ``@`` resource provider: the skills on this machine.

    Registering it here rather than inside the shell keeps the shell generic: it
    merges whatever providers the bundle holds, and the skills are simply the
    one the repository ships.
    """

    name = "skills"

    def activate(self, container: PluginContainer) -> None:
        """Offer the discovered skills as ``@`` resources, when skills are on."""
        if container.config.skills_enabled:
            container.register_mention(SkillMentions(container.config))


class FileResources(Plugin):
    """The ``@`` resource provider for the workspace's own files.

    Registered after the skills, so a name both could offer is the skill: a
    repository holds a file called ``test`` and a skill is the more specific
    thing to mean. Nothing turns this off, because a workspace always has files.
    """

    name = "files"

    def activate(self, container: PluginContainer) -> None:
        """Offer the workspace's files as ``@`` resources."""
        container.register_mention(FileMentions(container.config.workspace))


class UsageCommand(Plugin):
    """``/usage``: what this workspace's sessions have spent, by model, session and day.

    The numbers are read back from the stored conversations, so the page covers every
    session of the workspace, not only the one open, and an hour from now it will still
    agree with the files. It only reads, so it may run beside a request.
    """

    name = "usage"

    def activate(self, container: PluginContainer) -> None:
        """Register ``/usage`` and keep one reader, so a second look re-reads only what changed."""
        config = container.config
        readers: list[LedgerReader] = []

        async def show(context: CommandContext) -> CommandResult:
            """Open the usage page, or say that nothing has been spent yet."""
            if not readers:
                readers.append(LedgerReader(config.store, config.workspace))
            ledger = await asyncio.to_thread(readers[0].read)
            if ledger.empty:
                return CommandResult(message="No model replies are recorded in this workspace yet.")
            return CommandResult(widget=UsagePage(ledger, workspace=labels.compact_path(config.workspace, limit=None)))

        container.register_command("usage", "Token use by model, by session and by day", show, when_busy="now")


#: Plugins loaded from the repository itself, never from a distribution.
BUILTIN_PLUGINS: tuple[Plugin, ...] = (ShellRows(), SkillResources(), FileResources(), UsageCommand())
