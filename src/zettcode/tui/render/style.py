"""Styled text primitives shared by every render target."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only, avoids an import cycle
    from .rich_text import Alignment


@dataclass(frozen=True, slots=True)
class Style:
    """Terminal style independent from ANSI encoding.

    Attributes:
        foreground: Hex colour, or ``None`` to leave the terminal default.
        background: Hex colour, or ``None`` for no background.
        bold: Emit the bold attribute.
        italic: Emit the italic attribute.
        dim: Emit the faint attribute, used for de-emphasised structure.
        strike: Emit the crossed-out attribute, used for text a writer removed.
        reverse: Swap foreground and background; a text selection is painted
            this way so it works over any colour underneath.
    """

    foreground: str | None = None
    background: str | None = None
    bold: bool = False
    italic: bool = False
    dim: bool = False
    strike: bool = False
    reverse: bool = False


DEFAULT_STYLE = Style()


_measure: Callable[[str], int] | None = None


def _display_width() -> Callable[[str], int]:
    """Return ``text.display_width``, imported the first time it is needed and kept.

    ``text`` builds on the types in this module, so this module cannot import it when
    it loads; asking for the function inside every call was a statement the
    interpreter had to resolve each time, and a transcript measures a span tens of
    thousands of times.
    """
    global _measure
    if _measure is None:
        from .text import display_width

        _measure = display_width
    return _measure


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
        return _display_width()(self.text)


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
        measure = _display_width()
        return sum(measure(span.text) for span in self.spans)

    def layout(self, width: int, *, wrap: bool = True, align: Alignment = "left") -> tuple[TextLine, ...]:
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
