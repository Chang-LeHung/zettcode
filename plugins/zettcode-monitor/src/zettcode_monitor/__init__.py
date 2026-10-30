"""``/monitor``: record each model call of a session, and export the record as an HTML report.

``/monitor`` takes no arguments: it opens a panel with the recording and image switches and the export action.
"""

from __future__ import annotations

from pathlib import Path

from zettcode.app.commands import CommandContext, CommandResult
from zettcode.app.plugins import TerminalContainer, TerminalPlugin

from .recorder import MonitorExtension, default_root
from .report import render_report, write_report

#: The one place the version is written; ``pyproject.toml`` reads it from here.
__version__ = "0.1.1"

__all__ = ["MonitorExtension", "MonitorPlugin", "__version__", "render_report"]


def _calls(count: int) -> str:
    return f"{count} call{'' if count == 1 else 's'}"


class MonitorPlugin(TerminalPlugin):
    """Registers the recorder as an agent extension and the ``/monitor`` command."""

    name = "monitor"
    description = "record model calls and export them as HTML"

    def __init__(self, root: Path | None = None) -> None:
        self.extension = MonitorExtension(root if root is not None else default_root())

    def activate(self, container: TerminalContainer) -> None:
        container.register_extension(self.extension)
        container.register_command(
            "monitor",
            "record every model call: opens a panel with recording, images and export",
            self.monitor,
            when_busy="now",
        )

    def export(self, session_id: str, workspace: Path) -> tuple[int, Path]:
        """Write the report of a session into the workspace; return how many calls it holds and where it went.

        Raises:
            ValueError: Nothing has been recorded yet.
        """
        calls = self.extension.calls(session_id)
        if not calls:
            raise ValueError("Nothing recorded yet. Turn recording on, then send a request.")
        target = workspace / f"zettcode-monitor-{session_id[:8]}.html"
        page = render_report(session_id, calls, workspace=str(workspace))
        return len(calls), write_report(target, page)

    async def monitor(self, context: CommandContext) -> CommandResult:
        """Open the panel; whatever follows the command is ignored."""
        host = context.require_host()
        session_id = host.agent.session_id
        return CommandResult(widget=self.panel(host, context.ui, session_id, Path(host.agent.workspace)))

    def panel(self, host, ui, session_id: str, workspace: Path):  # type: ignore[no-untyped-def]
        """Return the bottom panel for one session, its switches where the session's state has them now."""
        from zettcode.app.ui.widgets import bottom_panel

        from .panel import ROWS, MonitorPage

        def export() -> str:
            count, written = self.export(session_id, workspace)
            return f"Exported {_calls(count)} to {written}"

        def apply(recording: bool, images: bool) -> None:
            self.extension.set_enabled(session_id, recording)
            self.extension.set_images(session_id, images)

        def done(said: str, exported: bool) -> None:
            # An export names a path worth keeping in the conversation; a saved setting is a passing remark.
            ui.notice(said) if exported else ui.notify(said)

        page = MonitorPage(
            recording=self.extension.enabled(session_id),
            images=self.extension.images(session_id),
            count=lambda: self.extension.count(session_id),
            on_apply=apply,
            on_export=export,
            on_close=host.close_page,
            on_done=done,
        )
        return bottom_panel(page, rows=ROWS)
