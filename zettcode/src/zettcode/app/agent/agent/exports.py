"""Writing a session out as a page a reader can open."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..export import build_trace, render_html, write_export
from ..storage import Session
from .context import ContextMixin
from .sessions import SessionsMixin
from .settings import SettingsMixin


class ExportsMixin(SessionsMixin, SettingsMixin, ContextMixin):
    """Export the active session together with the request the next turn would send."""

    async def export_session(self, path: str | Path | None = None) -> Path:
        """Write the active session, and the context it now carries, to HTML.

        The conversation is rendered with the same presenters the shell paints,
        and the request the next turn would send is included beside it, so a
        reader sees both the history and what the model is down to.

        Args:
            path: File to write; ``None`` puts ``zettcode-<id8>.html`` in the
                workspace. A relative path is taken from the working directory.

        Returns:
            The absolute path that was written.

        Raises:
            ValueError: When the session has no stored header, so there is
                nothing to export yet.
        """
        session = self.runtime.persistence.read(self.session_id)
        if session.header is None:
            raise ValueError("Nothing to export: this session has not been stored yet")
        report = await self.context_report()
        messages, tools = self._context_request(session)
        trace = build_trace(
            session,
            title=self.session_name,
            subtitle=f"Session {self.session_id} · {self.workspace}",
            meta=self._export_meta(session),
            tags=(self.runtime.active_model.shown_name, self.effort),
            context_messages=messages,
            tools=tuple(tool.name for tool in tools),
            report=report,
        )
        trace = replace(trace, exported_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))
        target = path if path is not None else self.workspace / f"zettcode-{self.session_id[:8]}.html"
        return write_export(target, render_html(trace))

    def _export_meta(self, session: Session) -> tuple[tuple[str, str], ...]:
        """Return the label/value pairs the exported page's sidebar carries."""
        model = self.runtime.active_model
        return (
            ("Workspace", str(self.workspace)),
            ("Model", f"{model.shown_name} ({model.model})"),
            ("Effort", self.effort),
            ("Created", session.created_at.astimezone().strftime("%Y-%m-%d %H:%M")),
            ("Updated", session.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")),
            ("Messages", f"{session.message_count}"),
        )
