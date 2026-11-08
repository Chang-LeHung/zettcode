"""``/context`` reads the runtime's report service and converts it for the page."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zettcode.app.plugins.loader import terminal_context
from zettcode.commands.context import ContextPagePlugin
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.extensions.context import ContextReport as EngineContextReport
from zettcode.engine.extensions.context import ContextShare as EngineShare
from zettcode.plugin_api import CONTEXT_REPORT, CommandContext, CommandUi, ContextReportService
from zettcode.sdk.types import ContextReport


class _Service(ContextReportService):
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def report(self, session_id: str):
        self.asked.append(session_id)
        return EngineContextReport(window=4_242, measured_by="t", shares=(EngineShare("User messages", 100, 1),))


class _Silent(CommandUi):
    def markdown(self, text: str) -> None:
        pass

    def notice(self, text: str) -> None:
        pass

    def error(self, text: str) -> None:
        pass

    def notify(self, text: str, *, level: str = "info") -> None:
        pass


async def test_the_page_is_drawn_from_the_context_report_service(tmp_path: Path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    config = ZettCodeConfig(workspace=workspace, models=(ModelConfig(model="m", token="t"),))
    service = _Service()
    ctx = terminal_context(config, {CONTEXT_REPORT: service})
    ContextPagePlugin().activate(ctx)
    (command,) = ctx.tui.registered_commands
    host = SimpleNamespace(
        client=SimpleNamespace(
            active_model=object(),
            model=SimpleNamespace(name="m", context_window=1_000, compact_percent=80.0, compaction_max_tokens=800),
            session=SimpleNamespace(path=workspace / "s.jsonl"),
        ),
        agent=SimpleNamespace(session_id="sess-9"),
        close_page=lambda: None,
        request_layout=lambda: None,
        transcript=SimpleNamespace(notice=lambda text: None, error=lambda text: None),
    )

    result = await command.handler(CommandContext(argument="", ui=_Silent(), host=host))

    assert service.asked == ["sess-9"], "the runtime service, asked for the session the shell is in"
    assert result.widget is not None and result.widget.report.window == 4_242
    assert isinstance(result.widget.report, ContextReport)
    assert result.widget.report.used == 100, "converted by context_report_from, not the client's own report"
    assert result.widget.title == "Context  100 / 4,242 tokens"
