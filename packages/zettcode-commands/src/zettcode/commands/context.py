"""``/context``: what the next request carries, by source and token share."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.app.plugins.groups import require_tui
from zettcode.app.ui.config_form import whole_if_whole
from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.sdk.translation import context_report_from

from .context_page import ContextPage
from .handlers import COMMAND_ERRORS

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class ContextPagePlugin(TuiPlugin):
    """The `/context` page, beside the data it draws."""

    name = "context"
    description = "What is filling the context window"

    def activate(self, ctx: PluginContext) -> None:
        tui = require_tui(ctx)

        async def show(context: CommandContext) -> CommandResult:
            """Open the context page, or say why there is nothing to measure yet."""
            host = context.require_host()
            if host.client.active_model is None:
                return CommandResult(
                    message="No model is configured yet \u2014 `/config` adds one; `/context` has something to "
                    "measure after the first request."
                )
            service = ctx.agent.context_report_service()
            if service is None:
                report = await host.client.session.context()
            else:
                report = context_report_from(await service.report(host.agent.session_id))
            if report is None:
                return CommandResult(
                    message="No request yet \u2014 send one (or resume a session), then `/context` shows the breakdown."
                )

            page_service = ctx.agent.context_page_service()
            if page_service is None:
                model = host.client.model
                snapshot = None
                model_name, path = model.name, host.client.session.path
                trigger, compact = model.compaction_max_tokens, model.compact_percent
                window = model.context_window
            else:
                snapshot = await page_service.snapshot(host.agent.session_id)
                model_name, path = snapshot.model_name, Path(snapshot.session_path)
                trigger, compact, window = (
                    snapshot.compaction_max_tokens,
                    snapshot.compact_percent,
                    snapshot.context_window,
                )

            def apply(percent: float) -> None:
                """Write the chosen compaction point and report what happened."""
                host.close_page()
                try:
                    if page_service is None:
                        model, unwritten = host.client.use_compact_percent(percent)
                        name = model.name
                    else:
                        name, unwritten = page_service.set_compact_percent(percent)
                except COMMAND_ERRORS as error:
                    host.transcript.error(str(error))
                    return
                said = f"{name}: compacts at {whole_if_whole(percent)}% of the window"
                said += f" ({round(window * percent / 100):,} tokens)"
                if unwritten is None:
                    host.transcript.notice(said)
                else:
                    host.transcript.notice(f"{said} for this run; not remembered: {unwritten}")
                host.request_layout()

            return CommandResult(
                widget=ContextPage(
                    report,
                    path=path,
                    model=model_name,
                    trigger=trigger,
                    compact_percent=compact,
                    on_apply=apply,
                    on_cancel=host.close_page,
                )
            )

        tui.register_command("context", "what is filling the context window", show, when_busy="now")
