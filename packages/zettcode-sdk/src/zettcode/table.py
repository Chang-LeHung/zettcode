"""Plain-text layout for the command line: columns measured in terminal cells, not in characters.

A command that prints a table has two ways to get it wrong. ``len`` counts a Chinese character as one cell when a
terminal gives it two, so a column of mixed names is crooked; and one row of many columns is wider than the terminal
it is printed to. :func:`table` measures with :func:`display_width`, and :func:`block` lays one field per line, which
is what a record with ten fields needs. Both are stdlib only, so any command may import them.

A cell's text is shown, not interpreted: a newline, a tab, an escape or a bidi override in a title becomes a space,
so a value can never break the layout or turn the rest of the line around; :func:`pad` does the same. Width is counted
per code point, with combining marks, joiners, variation selectors and skin-tone modifiers taking none; a joined emoji
is measured as its parts, which is wider than the one glyph a terminal may draw, and that is the limit of what this
can know without a terminal.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

__all__ = ["block", "display_width", "pad", "table"]

#: Categories a character keeps to itself: an accent on the letter before it, a joining mark, a direction mark.
_ZERO_WIDTH = ("Mn", "Me", "Cf")

#: Format characters that reorder or hide what follows: a right-to-left override turns the rest of the line around.
_BIDI = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def display_width(text: str) -> int:
    """Return how many terminal cells ``text`` takes.

    An East Asian wide or fullwidth character takes two cells; a combining mark, a joiner, a variation selector, a
    skin-tone modifier or another format character (``Cf``) takes none; everything else takes one.
    """
    cells = 0
    for character in text:
        if unicodedata.category(character) in _ZERO_WIDTH or _modifier(character):
            continue
        cells += 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
    return cells


def _modifier(character: str) -> bool:
    """Return whether ``character`` only changes the glyph before it: a variation selector or a skin tone."""
    return "\ufe0e" <= character <= "\ufe0f" or "\U0001f3fb" <= character <= "\U0001f3ff"


def _shown(text: str) -> str:
    """Return ``text`` with the characters a terminal would act on rather than show replaced by spaces."""
    return "".join(
        " " if unicodedata.category(character) in ("Cc", "Cs", "Zl", "Zp") or character in _BIDI else character
        for character in text
    )


def pad(text: str, width: int) -> str:
    """Return ``text`` followed by the spaces that make it ``width`` cells wide; a wider one is left alone.

    Control characters are shown as spaces here too, so a caller that pads with this cannot break its own line.
    """
    shown = _shown(text)
    return shown + " " * max(0, width - display_width(shown))


def table(rows: Sequence[Sequence[str]], *, indent: str = "", separator: str = "  ") -> list[str]:
    """Return ``rows`` as aligned lines, the first row being the headings.

    Each column is as wide as its widest cell in terminal cells, so a name in Chinese lines up with one in Latin.

    Raises:
        ValueError: A row holds a different number of cells from the first, so there is no column to put it in.
    """
    if not rows:
        return []
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError(f"every row of a table needs {width} cells")
    shown = [[_shown(cell) for cell in row] for row in rows]
    widths = [max(display_width(row[index]) for row in shown) for index in range(width)]
    return [
        (indent + separator.join(pad(cell, widths[index]) for index, cell in enumerate(row))).rstrip() for row in shown
    ]


def block(fields: Iterable[tuple[str, str]], *, indent: str = "  ", separator: str = "  ") -> list[str]:
    """Return one line per ``(label, value)``, the labels padded to the widest of them.

    This is the layout for a record: a table with one row per field and no heading, so a value may hold a path, a
    sentence or a title without widening every other row.
    """
    pairs = [(_shown(label), _shown(value)) for label, value in fields]
    if not pairs:
        return []
    width = max(display_width(label) for label, _ in pairs)
    return [f"{indent}{pad(label, width)}{separator}{value}".rstrip() for label, value in pairs]
