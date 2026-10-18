"""A highlight that travels across a label, one span per brightness step.

A wait is easier to read when something moves through it than when the whole row
flips between two states: the eye follows the bright point, and the rest of the
label keeps its ordinary colour, so the text never disappears mid-pulse.

The effect is a span, not a widget. :class:`SweepSpan` is an ordinary
:class:`~zettcode.tui.Span` — same text, same resting style — that also carries
the colour of the bright point and the width of the ramp around it;
:func:`sweep_spans` resolves one into the plain spans a renderer draws for a
single frame.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .color import blend
from .style import DEFAULT_STYLE, Span, Style
from .text import character_width, display_width


@dataclass(frozen=True, slots=True)
class SweepSpan(Span):
    """A run of text with a highlight that moves across it.

    Attributes:
        peak: Style of the character the highlight sits on; the colour in it is
            blended towards :attr:`Span.style` on the way out, so a palette only
            has to name the bright end.
        ramp: Columns on either side that fade back to the resting style. The
            highlight also spends this many columns off each end of the text, so
            the sweep pauses instead of jumping back to the start.
    """

    peak: Style = DEFAULT_STYLE
    ramp: int = 4

    @property
    def travel(self) -> int:
        """Return how many columns one full pass takes, ends included."""
        return display_width(self.text) + max(1, self.ramp) * 2


def sweep_spans(span: SweepSpan, step: int) -> tuple[Span, ...]:
    """Resolve one sweep into the spans to draw for a frame.

    Args:
        span: The label, its resting style, and its highlight.
        step: Column the highlight has travelled to; it wraps every
            :attr:`SweepSpan.travel` columns, so a renderer can pass a frame
            counter straight in.

    Adjacent characters that ended up with the same style are merged, so a label
    costs at most ``2 * ramp + 1`` runs per frame.
    """
    ramp = max(1, span.ramp)
    centre = (step % span.travel) - ramp
    runs: list[Span] = []
    column = 0
    for character in span.text:
        amount = 1.0 - abs(column - centre) / (ramp + 1)
        runs.append(Span(character, _style_at(span, amount)))
        column += character_width(character)
    return _merge(runs)


def _style_at(span: SweepSpan, amount: float) -> Style:
    """Return the style for one character, ``amount`` along the ramp."""
    if amount <= 0:
        return span.style
    if amount >= 1:
        return span.peak
    if span.style.foreground is None or span.peak.foreground is None:
        return span.peak if amount > 0.5 else span.style
    return replace(span.style, foreground=blend(span.style.foreground, span.peak.foreground, amount))


def _merge(runs: list[Span]) -> tuple[Span, ...]:
    """Join adjacent runs that share a style, so a frame draws few spans."""
    merged: list[Span] = []
    for run in runs:
        if merged and merged[-1].style == run.style:
            merged[-1] = Span(merged[-1].text + run.text, run.style)
        else:
            merged.append(run)
    return tuple(merged)
