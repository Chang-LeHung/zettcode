"""The shell's two bars: what the header and the status line draw.

The bars are plugin segments, so this part owns only the generic loop and the
snapshot a segment builder reads. The builtin rows themselves ship as a plugin,
which is what leaves the shell with one renderer rather than one per row.
"""

from __future__ import annotations

from dataclasses import replace

from zettcode.plugins import (
    ActivityState,
    DisplayState,
    ModelState,
    SessionState,
    ShellContext,
    UiRegion,
    UiSide,
)
from zettcode.tui import HEADER, SEPARATOR, Span, Style, TextLine
from zettcode.tui.render import blend, display_width

from ..agent.agent.sessions import UNTITLED_SESSION
from ..agent.conversation.shimmer import ShimmerFrame
from ..agent.permission import Permission
from .shell import ShellState
from .widgets.effort_page import heat_colour


class BarsMixin(ShellState):
    """Paint each row side from the segments the plugins registered."""

    def _terminal_title(self) -> str:
        """Keep the brand marker and app name when the active session changes."""
        return f"{HEADER} zettcode {SEPARATOR} {self._session_title or UNTITLED_SESSION}"

    def _header_left(self) -> TextLine:
        """Return the header's left side, whatever the plugins put there.

        While the show for a switch to the top of the scale plays, the light crossing the header goes over
        this side too, so the whole row glints and not only the corner that changed.
        """
        line = self._side("header", "left")
        frame = self._effort_gauge()
        return self._glint(line, frame) if isinstance(frame, ShimmerFrame) else line

    def _glint(self, line: TextLine, frame: ShimmerFrame) -> TextLine:
        """Lay the light of the show over a line drawn from the left edge, character by character."""
        theme = self.app.theme
        halo = blend(blend(theme.warning, theme.text, 0.18), theme.text, 0.4)
        spans: list[Span] = []
        column = 0
        for span in line.spans:
            for character in span.text:
                glow, core = frame.light(frame.reach - 1 - column)
                colour = span.style.foreground or theme.muted
                if glow > 0.0:
                    colour = blend(colour, halo, glow * 0.9 * frame.presence)
                    colour = blend(colour, theme.text, core * frame.presence)
                bold = span.style.bold or core * frame.presence > 0.5
                spans.append(Span(character, replace(span.style, foreground=colour, bold=bold)))
                column += max(1, display_width(character))
        return TextLine(tuple(spans), metadata=line.metadata)

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
        if isinstance(gauge, ShimmerFrame):
            return self._shimmer_row(gauge)
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

    def _shimmer_row(self, frame: ShimmerFrame) -> TextLine:
        """Paint the show a switch to the top of the scale plays: light crossing the row, right to left.

        The frame says where the light is and what it has lit; the colours are chosen here, from the theme
        like every other colour in the header. A lit column is gold, and at ``ultra`` the gauge runs on from
        gold into the error colour toward its dear end. The halo is a pale gold and the core inside it takes
        the text colour, which is the brightest the palette has (on a light theme that is the darkest ink,
        so the glint reads as a glint there too). Everything returns to the resting header by what is
        missing of the frame's presence, as the ordinary gauge does.
        """
        theme = self.app.theme
        muted = theme.muted
        groove = blend(theme.muted, theme.surface, 0.55)
        away = 1.0 - frame.presence
        ultra = frame.word == "ultra"
        gold = blend(theme.warning, theme.text, 0.18)
        halo = blend(gold, theme.text, 0.4)
        last = max(1, frame.cells - 1)

        def lit(steady: str, column: int, rest: str, *, ignited: bool | None = None) -> str:
            colour = steady if (frame.ignited[column] if ignited is None else ignited) else rest
            colour = blend(colour, halo, frame.glow[column] * 0.9)
            colour = blend(colour, theme.text, frame.core[column])
            if frame.ignited[column]:
                colour = blend(colour, theme.text, frame.glitter[column] * 0.8)
            return blend(colour, rest, away)

        spans: list[Span] = []
        column = 0
        for character in f"{self.agent.active_model.shown_name} {SEPARATOR} ":
            if column >= frame.lead:
                break
            steady = blend(muted, gold, 0.3)
            spans.append(Span(character, Style(foreground=lit(steady, column, muted))))
            column += max(1, display_width(character))
        for index in range(frame.cells):
            column = frame.lead + index
            if index < frame.lit_cells and frame.ignited[column]:
                steady = heat_colour(theme, index / last)
                steady = blend(steady, gold, 0.45)
                if ultra:
                    steady = blend(steady, theme.error, 0.5 * index / last)
                spans.append(Span("\u2501", Style(foreground=lit(steady, column, groove))))
            else:
                spans.append(Span("\u2500", Style(foreground=lit(groove, column, groove, ignited=False))))
        word_colour = blend(heat_colour(theme, frame.heat), gold, 0.5)
        if ultra:
            word_colour = blend(word_colour, theme.error, 0.35)
        word_start = frame.word_start
        spans.append(Span(" ", Style(foreground=muted)))
        spark_left = word_start - 2
        spans.append(Span(frame.sparks[0], Style(foreground=lit(word_colour, spark_left, muted), bold=True)))
        spans.append(Span(" ", Style(foreground=muted)))
        for offset, character in enumerate(frame.word):
            at = word_start + offset
            spans.append(Span(character, Style(foreground=lit(word_colour, at, muted), bold=frame.ignited[at])))
        spans.append(Span(" ", Style(foreground=muted)))
        spark_right = frame.width - 1
        spans.append(Span(frame.sparks[1], Style(foreground=lit(word_colour, spark_right, muted), bold=True)))
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
        return heat_colour(theme, heat)

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
