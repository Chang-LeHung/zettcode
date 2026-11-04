"""``/usage``: what this workspace's sessions have spent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.app.plugins.groups import require_tui
from zettcode.app.ui import labels
from zettcode.app.ui.widgets import UsagePage
from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class UsageCommand(TuiPlugin):
    """``/usage``: what this workspace's sessions have spent, by model, session and day.

    The numbers are read back from the stored conversations, so the page covers every
    session of the workspace, not only the one open, and an hour from now it will still
    agree with the files. It only reads, so it may run beside a request.
    """

    name = "usage"

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/usage``; the client keeps one reader, so a second look re-reads only what changed."""
        config = ctx.config
        tui = require_tui(ctx)

        async def show(context: CommandContext) -> CommandResult:
            """Open the usage page, or say that nothing has been spent yet."""
            ledger = await context.require_host().client.usage_ledger()
            if ledger.total.requests == 0:
                return CommandResult(message="No model replies are recorded in this workspace yet.")
            return CommandResult(widget=UsagePage(ledger, workspace=labels.compact_path(config.workspace, limit=None)))

        tui.register_command("usage", "Token use by model, by session and by day", show, when_busy="now")
