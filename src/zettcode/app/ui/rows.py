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
from ...tui.render import blend
from ..agent.agent.sessions import UNTITLED_SESSION
from ..agent.permission import Permission
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
        """Return the header's right side: the plugins' segments, or the gauge.

        A switch between effort levels owns this row for the second it animates:
        the model and the gauge take the place of the segments a plugin
        registered, which is a trade worth making for one second and the one
        moment a reader changed something here.
        """
        gauge = self._effort_gauge()
        if gauge is None:
            return self._side("header", "right")
        theme = self.app.theme
        muted = Style(foreground=theme.muted)
        # The rail is the border colour brought toward the background, so an
        # unreached cell reads as a groove rather than as a dim line of text.
        groove = blend(theme.muted, theme.surface, 0.55)
        spans: list[Span] = [
            Span(self.agent.active_model.shown_name, muted),
            Span(f" {SEPARATOR} ", muted),
        ]
        away = 1.0 - gauge.presence
        # The groove fades with the gauge, so the last thing to leave is not a rail
        # standing alone in an otherwise plain header.
        rail_colour = blend(groove, theme.surface, away)
        rail = Style(foreground=rail_colour)
        for cell in gauge.cells:
            if cell.lit:
                colour = blend(self._heat(cell.heat), theme.text, cell.glow * 0.8)
                # What is missing of the gauge is made up by the groove it sits in,
                # so it fades into the rail rather than into nothing.
                spans.append(Span(cell.char, Style(foreground=blend(colour, rail_colour, away))))
            else:
                spans.append(Span(cell.char, rail))
        word = self._heat(gauge.word_heat)
        spans.append(Span(" ", muted))
        for character, glow in zip(gauge.word, gauge.word_glow, strict=True):
            colour = blend(word, theme.text, glow * 0.9)
            # The word returns to the header's own grey, which is what it is
            # when the gauge is gone: the last frame and the next are the same colour.
            spans.append(Span(character, Style(foreground=blend(colour, theme.muted, away))))
        return TextLine(tuple(spans))

    def _heat(self, heat: float) -> str:
        """Return the colour of a point on the effort scale, from cheap to dear.

        The ramp runs through the theme's own accents — green, a brighter green,
        amber, and the error colour — rather than through fixed hues, so the
        gauge follows `/theme` and a light palette gets the darker ends of the
        same story. Position on the scale is the only input: the same level is
        the same colour whether it is being switched to or away from.
        """
        theme = self.app.theme
        stops = (theme.accent, theme.accent_bright, theme.warning, theme.error)
        scaled = min(max(heat, 0.0), 1.0) * (len(stops) - 1)
        index = min(int(scaled), len(stops) - 2)
        return blend(stops[index], stops[index + 1], scaled - index)

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
                handle=self.messenger.handle if self.messenger is not None else "",
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
                auto_shell=self.agent.permission is Permission.AUTO,
                permission=self.agent.permission.value,
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
