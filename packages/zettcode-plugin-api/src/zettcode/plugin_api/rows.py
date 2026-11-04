"""The line the header and the status line are drawn from, as a plugin's segment may hand it over.

A segment hook returns a styled line, a string, or one of these; the shell joins the parts and drops the ones that
are hidden. It sits in the contract because the type a hook may return is part of the hook.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import NamedTuple

from zettcode.statusline_parts import Part
from zettcode.tui.glyphs import SEPARATOR

__all__ = ["GAP", "JOIN", "Piece", "Row"]

JOIN = f" {SEPARATOR} "
GAP = "  "


class Piece(NamedTuple):
    """A part that is shown, with the characters in front of it: the side's lead, a join, or a gap."""

    glue: str
    part: Part


class Row:
    """One side of the header or the status line, appended to part by part.

    Shape::

        row = Row(lead="  ").add("app", "The mark and name", "\\u25c8 zettcode").gap()
        row.add("session", "The session's title", "Fix").add("workspace", "The directory", "~/api")
        row.text()            # "  \\u25c8 zettcode  Fix \\u00b7 ~/api"

    Parts of one run are joined by :data:`JOIN` and runs by :data:`GAP`. A part that is hidden or has no
    text takes no room and no separator either, and a side with nothing left is empty rather than a pair of
    padding spaces — a row too narrow for its right end loses that end, not a stray separator.
    """

    def __init__(self, *, lead: str = "", trail: str = "") -> None:
        """Start an empty side.

        Args:
            lead: Characters before the first part, when there is one.
            trail: Characters after the last part, when there is one.
        """
        self.lead = lead
        self.trail = trail
        #: The parts in the order they were added, with ``None`` standing for a break between two runs.
        self._items: list[Part | None] = []

    def add(self, name: str, summary: str, text: str = "") -> Row:
        """Append one part, and return this row so the calls chain.

        Args:
            name: The part's name, which is the switch ``/statusline`` and ``[statusline]`` use.
            summary: What the part shows, in one line, for the panel.
            text: What it shows now; empty when it has nothing to say in this session.
        """
        self._items.append(Part(name, summary, text))
        return self

    def gap(self) -> Row:
        """Begin a new run: the next part shown stands two spaces after the one before it."""
        self._items.append(None)
        return self

    def parts(self) -> tuple[Part, ...]:
        """Return every part that was added, in order, whether or not it has anything to say."""
        return tuple(item for item in self._items if item is not None)

    def shown(self, hidden: Collection[str] = ()) -> tuple[Piece, ...]:
        """Return the parts that are neither hidden nor empty, each with what stands in front of it."""
        pieces: list[Piece] = []
        glue = self.lead
        for item in self._items:
            if item is None:
                glue = GAP
            elif item.text and item.name not in hidden:
                pieces.append(Piece(glue, item))
                glue = JOIN
        return tuple(pieces)

    def text(self, hidden: Collection[str] = ()) -> str:
        """Return the side as the characters it shows, or ``""`` when nothing is left of it."""
        pieces = self.shown(hidden)
        if not pieces:
            return ""
        return "".join(piece.glue + piece.part.text for piece in pieces) + self.trail
