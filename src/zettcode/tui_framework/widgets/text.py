"""Static display primitives: a label and a horizontal rule."""

from __future__ import annotations

from collections.abc import Callable

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Span, Style, wrap_spans
from ..render.text import display_width

Value = str | Callable[[], str]


class Text(Widget):
    """A label that may compute its value at paint time and wrap to its width."""

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
        super().__init__()
        self.value = value
        self.align = align
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

    def measure(self, constraints: Constraints) -> Size:
        """Wrap the text to the offered width and count the resulting rows."""
        text = self.content
        width = constraints.max_width if constraints.max_width is not None else display_width(text)
        height = sum(len(wrap_spans((Span(line),), max(1, width))) for line in text.split("\n"))
        return constraints.constrain(Size(min(display_width(text), max(1, width)), height))

    def render(self, canvas: Canvas) -> None:
        """Paint the wrapped lines, right-aligning them when asked."""
        if self.rect.empty:
            return
        style = self.style_for()
        row = 0
        for source in self.content.split("\n"):
            for wrapped in wrap_spans((Span(source),), self.rect.width):
                if row >= self.rect.height:
                    return
                text = "".join(span.text for span in wrapped)
                x = (
                    self.rect.x + max(0, self.rect.width - display_width(text))
                    if self.align == "right"
                    else self.rect.x
                )
                canvas.draw_text(x, self.rect.y + row, text, style, max_width=self.rect.width)
                row += 1


class Rule(Widget):
    """A one-row horizontal separator."""

    def __init__(self, character: str = "\u2500") -> None:
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
