"""The pixel robot shared by the terminal banner and documentation assets.

Each character is one square pixel: frame, ear, dark face, eye, or heart;
``.`` is transparent. One fifteen-by-ten map drives every rendering; the
terminal holds two vertically stacked pixels per cell for a five-row mark,
and the documentation scales those same pixels without resampling them.
The brand colours stay fixed in both themes; only the surrounding text follows
the reader's palette.
"""

from __future__ import annotations

from ..tui.render.style import Span, Style, TextLine

LOGO_PALETTE: dict[str, str] = {
    "F": "#84b795",
    "E": "#558967",
    "D": "#263d34",
    "I": "#b9dfb3",
    "H": "#e4b47c",
}

LOGO_PIXELS: tuple[str, ...] = (
    "..FFFFFFFFFFF..",
    ".FFFFFFFFFFFFF.",
    "EFFDIIDDDIIDFFE",
    "EFFDIIDDDIIDFFE",
    "EFFDDDDDDDDDFFE",
    "EFFDDHHDHHDDFFE",
    "EFFDDHHHHHDDFFE",
    "EFFDDDDHDDDDFFE",
    ".FFFFFFFFFFFFF.",
    "..FFFFFFFFFFF..",
)


def logo_lines() -> tuple[TextLine, ...]:
    """Return the full-size mark: :data:`LOGO_PIXELS` in :data:`LOGO_PALETTE`, five rows of cells."""
    return pixel_lines(LOGO_PIXELS, LOGO_PALETTE)


def pixel_lines(pixels: tuple[str, ...], palette: dict[str, str]) -> tuple[TextLine, ...]:
    """Encode each pixel pair with a full/half block and two independent colours.

    Equal pixels use a full block. Different opaque pixels use an upper half
    block with the lower pixel as its background. When either half is outside
    the silhouette, its background stays unset to preserve the terminal's own
    colour rather than drawing a rectangle around the mark.

    Args:
        pixels: Equal-length rows, an even number of them; ``.`` is transparent and any other
            character names its colour in ``palette``.
        palette: Colour of each pixel character.
    """
    lines: list[TextLine] = []
    for index in range(0, len(pixels), 2):
        spans: list[Span] = []
        for upper, lower in zip(pixels[index], pixels[index + 1], strict=True):
            if upper == lower:
                span = Span(" " if upper == "." else "█", Style(foreground=palette.get(upper)))
            elif upper == ".":
                span = Span("▄", Style(foreground=palette[lower]))
            else:
                span = Span("▀", Style(foreground=palette[upper], background=palette.get(lower)))
            if spans and spans[-1].style == span.style:
                spans[-1] = Span(spans[-1].text + span.text, span.style)
            else:
                spans.append(span)
        lines.append(TextLine(tuple(spans)))
    return tuple(lines)


LOGO_LINES: tuple[TextLine, ...] = logo_lines()
