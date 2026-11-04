"""The pixel robot shared by the terminal banner and documentation assets.

Each character is one square pixel: frame, ear, dark face, eye, or heart;
``.`` is transparent. One fifteen-by-ten map drives every rendering; the
terminal holds two vertically stacked pixels per cell for a five-row mark,
and the documentation scales those same pixels without resampling them.
The brand colours stay fixed in both themes; only the surrounding text follows
the reader's palette.
"""

from __future__ import annotations

from zettcode.plugin_api.pets import pixel_lines
from zettcode.tui.render.style import TextLine

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


LOGO_LINES: tuple[TextLine, ...] = logo_lines()
