"""Styled text primitives shared by every render target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Style:
    """Terminal style independent from ANSI encoding.

    Attributes:
        foreground: Hex colour, or ``None`` to leave the terminal default.
        background: Hex colour, or ``None`` for no background.
        bold: Emit the bold attribute.
        italic: Emit the italic attribute.
        dim: Emit the faint attribute, used for de-emphasised structure.
        reverse: Swap foreground and background; a text selection is painted
            this way so it works over any colour underneath.
    """

    foreground: str | None = None
    background: str | None = None
    bold: bool = False
    italic: bool = False
    dim: bool = False
    reverse: bool = False


DEFAULT_STYLE = Style()


@dataclass(frozen=True, slots=True)
class Span:
    """One styled text fragment.

    Attributes:
        text: Characters that share one style; no newlines.
        style: Style applied to every character in ``text``.
    """

    text: str
    style: Style = DEFAULT_STYLE

    @property
    def width(self) -> int:
        """Return the columns this fragment paints, including wide glyphs."""
        from .text import display_width

        return display_width(self.text)


@dataclass(frozen=True, slots=True)
class TextLine:
    """One logical line with optional component-owned metadata.

    Attributes:
        spans: Styled fragments in paint order.
        metadata: Free-form slot for the component that produced the line; the
            canvas ignores it, hit-testing and callers may read it.
    """

    spans: tuple[Span, ...] = ()
    metadata: object | None = None

    @property
    def text(self) -> str:
        """Return the concatenated text of every span."""
        return "".join(span.text for span in self.spans)

    @property
    def width(self) -> int:
        """Return the displayed column width of this line."""
        return sum(span.width for span in self.spans)

    def layout(self, width: int, *, wrap: bool = True, align: str = "left") -> tuple[TextLine, ...]:
        """Lay out this line using the same rules as a RichText widget."""
        from .rich_text import layout_rich_lines

        return layout_rich_lines((self,), width, wrap=wrap, align=align)


@dataclass(frozen=True, slots=True)
class Cell:
    """One terminal column; wide glyph tails use continuation=True.

    Attributes:
        character: Glyph drawn in this column, or ``""`` on a continuation cell.
        style: Style of the cell; a continuation cell repeats its leader's style.
        continuation: This cell is the second half of a wide glyph, so the
            renderer must skip it and the leader must be repainted together.
    """

    character: str = " "
    style: Style = DEFAULT_STYLE
    continuation: bool = False
