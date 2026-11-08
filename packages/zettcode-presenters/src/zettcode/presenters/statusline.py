"""The parts the header and the status line are made of, and the two rows they are appended to.

A row is written where its text is known: :meth:`Row.add` names a part, says in one line what the part shows —
that line is what the ``/statusline`` panel lists — and gives the text the part has right now. The text may be
empty (a handle with messaging off, the mode at ``ask``), and the part stays listed all the same; it just takes
no room on the row. Every part is shown until the reader switches it off, and the switch is the part's name in
the ``[statusline]`` table.

Nothing here reads the config, the theme, or the session, so the frame the command line paints before the
application exists lays its rows out with the same code the shell paints with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.plugin_api.rows import GAP, JOIN, Piece, Row
from zettcode.statusline_parts import NAMES, PET, TURN_PARTS, TURN_PREFIX, Part, is_part, unknown
from zettcode.tui.glyphs import ARROW_DOWN, ARROW_UP, SEPARATOR

from .text import compact_tokens

#: The names and the shape of a part are the config's vocabulary, shipped by the engine
#: (:mod:`zettcode.statusline_parts`); they are re-exported here so the terminal reads one module.
__all__ = [
    "GAP",
    "JOIN",
    "NAMES",
    "PET",
    "TURN_PARTS",
    "TURN_PREFIX",
    "Part",
    "Piece",
    "Row",
    "compact_tokens",
    "context_share",
    "context_text",
    "is_part",
    "unknown",
    "usage_parts",
    "usage_text",
]

if TYPE_CHECKING:  # pragma: no cover - annotations only; the engine stays out of the command line's frame
    from zettcode.sdk.types import Usage


#: What stands between two parts of one run, and between two runs of one side.
def usage_parts(snapshot: Usage) -> dict[str, str]:
    """Return the status line's token figures by the name of the part that shows each; empty before a reply."""
    if not snapshot.requests:
        return {}
    parts = {
        "tokens": f"{ARROW_UP}{compact_tokens(snapshot.input_tokens)} {ARROW_DOWN}{compact_tokens(snapshot.output_tokens)}"
    }
    rate = snapshot.cache_hit_rate
    if rate is not None:
        parts["cache"] = f"{rate * 100:.1f}% cached"
    speed = snapshot.output_rate
    if speed is not None:
        parts["speed"] = f"{speed:.0f} tok/s" if speed >= 10 else f"{speed:.1f} tok/s"
    return parts


def usage_text(snapshot: Usage) -> str:
    """Render the status-line summary, or an empty string before the first call."""
    parts = usage_parts(snapshot)
    return "  " + f" {SEPARATOR} ".join(parts.values()) if parts else ""


def context_share(snapshot: Usage, window: int) -> str:
    """Render how much of the model's window the newest request filled, as ``ctx 34.0%``.

    Empty before any request has been measured or when the model does not declare a window.
    """
    if not snapshot.requests or window < 1 or snapshot.context_tokens < 1:
        return ""
    share = min(100.0, snapshot.context_tokens * 100 / window)
    return f"ctx {share:.1f}%"


def context_text(snapshot: Usage, window: int) -> str:
    """Render how much of the model's window the newest request filled, as a fragment that follows the counters.

    Returns:
        A short ``"· ctx 34.0%"`` fragment, or ``""`` before any request has been measured or when the model does
        not declare a window. The leading separator is part of the fragment, so it joins the usage counters the
        same way they join each other.
    """
    share = context_share(snapshot, window)
    return f" {SEPARATOR} {share}" if share else ""
