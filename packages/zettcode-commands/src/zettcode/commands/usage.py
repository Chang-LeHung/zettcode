"""``/usage``: what this workspace's sessions have spent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.app.plugins.groups import require_tui
from zettcode.plugin_api import USAGE_LEDGER
from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.presenters import labels
from zettcode.sdk.translation import ledger_from

from .usage_page import UsagePage

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class UsageCommand(TuiPlugin):
    """``/usage``: what this workspace's sessions have spent, by model, session and day.

    The numbers are read back from the stored conversations, so the page covers every
    session of the workspace, not only the one open, and an hour from now it will still
    agree with the files. It only reads, so it may run beside a request.
    """

    name = "usage"
    description = "Token use by model, by session and by day"

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/usage``; the store keeps one reader, so a second look re-reads only what changed."""
        config = ctx.config
        tui = require_tui(ctx)

        async def show(context: CommandContext) -> CommandResult:
            """Open the usage page, or say that nothing has been spent yet."""
            service = ctx.agent.usage_ledger_service()
            if service is None:
                raise LookupError(f"No plugin provides the {USAGE_LEDGER!r} service")
            usage = ledger_from(await service.ledger())
            if usage.total.requests == 0:
                return CommandResult(message="No model replies are recorded in this workspace yet.")
            return CommandResult(widget=UsagePage(usage, workspace=labels.compact_path(config.workspace, limit=None)))

        tui.register_command("usage", "Token use by model, by session and by day", show, when_busy="now")
