"""The shell's two rows: what the header and the status line draw.

The rows are plugin segments, so this part owns only the generic loop and the
snapshot a segment builder reads. The builtin rows themselves ship as a plugin,
which is what leaves the shell with one renderer rather than one per row.
"""

from __future__ import annotations

from ...plugins import (
    ActivityState,
    DisplayState,
    ModelState,
    SessionState,
    ShellContext,
    UiRegion,
    UiSide,
)
from ...tui import HEADER, SEPARATOR, Span, Style, TextLine
from ..agent.agent import UNTITLED_SESSION
from .shell import ShellState


class RowsMixin(ShellState):
    """Paint each row side from the segments the plugins registered."""

    def _terminal_title(self) -> str:
        """Keep the brand marker and app name when the active session changes."""
        return f"{HEADER} zettcode {SEPARATOR} {self._session_title or UNTITLED_SESSION}"

    def _header_left(self) -> TextLine:
        """Return the header's left side, whatever the plugins put there."""
        return self._side("header", "left")

    def _header_right(self) -> TextLine:
        """Return the header's right side, whatever the plugins put there."""
        return self._side("header", "right")

    def _status_left(self) -> TextLine:
        """Return the status line's left side, whatever the plugins put there."""
        return self._side("status", "left")

    def _status_right(self) -> TextLine:
        """Return the status line's right side, whatever the plugins put there."""
        return self._side("status", "right")

    def _side(self, region: UiRegion, side: UiSide) -> TextLine:
        """Paint one side of one row from the segments the plugins registered.

        The shell owns only this loop: the builtin rows are a plugin like any
        other, and a plugin that overrode one of its slots already sits in its
        place. A segment that returns nothing is skipped, one that raises is
        dropped for that frame only, and one that returns ``(line, True)`` takes
        the side over — the segments painted before it are dropped.
        """
        row = next((row for row in self._plugin_rows if row.region == region), None)
        segments = () if row is None else (row.left if side == "left" else row.right)
        style = Style(foreground=self.app.theme.muted)
        spans: list[Span] = []
        context: ShellContext | None = None
        for segment in segments:
            if context is None:
                context = self._shell_context()
            try:
                value = segment.builder(context)
            except Exception:
                continue
            overrides = False
            if isinstance(value, tuple):
                value, overrides = value
            line = value if isinstance(value, TextLine) else TextLine((Span(str(value)),)) if value else None
            if overrides:
                spans.clear()
            if line is None or not line.width:
                continue
            if spans:
                spans.append(Span(f" {SEPARATOR} ", style))
            spans.extend(line.spans)
        return TextLine(tuple(spans))

    def _shell_context(self) -> ShellContext:
        """Snapshot what a plugin's segment builder reads, rebuilt for one paint."""
        return ShellContext(
            config=self.agent.runtime.config,
            session=SessionState(
                id=self.agent.session_id,
                title=self._session_title,
                name=self._session_title or UNTITLED_SESSION,
                workspace=self.agent.workspace,
            ),
            model=ModelState(
                config=self.agent.active_model,
                name=self.agent.active_model.shown_name,
                effort=self.agent.effort,
                efforts=self.agent.efforts,
            ),
            activity=ActivityState(
                busy=self._busy,
                status=self._activity,
                note=self._note,
                auto_shell=self._auto_shell,
                usage=self._usage,
                tasks=self.agent.tasks(),
                frame=self.transcript.frame,
            ),
            display=DisplayState(
                theme=self.app.theme,
                width=self.app.width,
                height=self.app.height,
                screen=self.app.screens.top.name,
                scrolled_up=self.view.scrolled_up,
            ),
        )
