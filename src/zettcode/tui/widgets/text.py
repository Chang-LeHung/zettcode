"""Static display primitives: a label and a horizontal rule."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from ...tui import RULE
from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Span, Style, TextLine
from .rich_text import RichText

Value: TypeAlias = str | Callable[[], str]


class Text(RichText):
    """A label that may compute its value at paint time and wrap to its width.

    Shape::

        bold heading                      <- bold=True
        muted caption that wraps across   <- muted=True, wrapped at rect.width
        rows
                            right aligned <- align="right"

    It uses the same styled-line layout as :class:`RichText`; the label never
    grows past the rectangle it was given, it just writes fewer rows.
    """

    #: The label resolves to text only, never to styled fragments.
    value: Value

    def __init__(
        self,
        value: Value = "",
        *,
        align: str = "left",
        bold: bool = False,
        muted: bool = False,
    ) -> None:
        """Configure the label's content and its paint-time styling.

        Args:
            value: Static text, or a callback re-evaluated on every paint so the
                label can mirror live state without the owner calling invalidate.
            align: ``"right"`` right-aligns within the widget rectangle; every
                other value falls back to left alignment. Wrapping is unaffected.
            bold: Draw every span bold.
            muted: Use the theme's muted colour instead of the body text colour.
        """
        super().__init__(value, align="right" if align == "right" else "left")
        self.value = value
        self.bold = bold
        self.muted = muted

    @property
    def content(self) -> str:
        """Resolve the current text, calling the value when it is a provider."""
        return self.value() if callable(self.value) else self.value

    def style_for(self) -> Style:
        """Return the style this label paints with."""
        theme = self.theme
        return Style(foreground=theme.muted if self.muted else theme.text, bold=self.bold)

    def _lines(self) -> tuple[TextLine, ...]:
        """Return the label as styled lines for the shared layout."""
        style = self.style_for()
        return tuple(TextLine((Span(source, style),)) for source in self.content.split("\n"))


class Rule(Widget):
    """A one-row horizontal separator.

    Shape::

        --------------------------------  <- character repeated rect.width times

    Drawn with U+2500 by default. It asks for a single cell and takes whatever
    width its slot gives it, so it is normally used as ``Slot(Rule(), size=1)``
    between two regions.
    """

    def __init__(self, character: str = RULE) -> None:
        """Set the glyph the rule repeats across its width.

        Args:
            character: Repeated once per column; the default is a box-drawing dash.
        """
        super().__init__()
        self.character = character

    def measure(self, constraints: Constraints) -> Size:
        """Claim a single cell; the parent box supplies the real width."""
        return constraints.constrain(Size(1, 1))

    def render(self, canvas: Canvas) -> None:
        """Fill the assigned row with the rule character."""
        if self.rect.empty:
            return
        canvas.draw_text(
            self.rect.x,
            self.rect.y,
            self.character * self.rect.width,
            Style(foreground=self.theme.border),
            max_width=self.rect.width,
        )
