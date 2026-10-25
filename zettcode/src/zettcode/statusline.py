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

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from zettcode.tui.glyphs import ARROW_DOWN, ARROW_UP, SEPARATOR

if TYPE_CHECKING:  # pragma: no cover - annotations only; the engine stays out of the command line's frame
    from zettcode.sdk.types import Usage

#: What stands between two parts of one run, and between two runs of one side.
JOIN = f" {SEPARATOR} "
GAP = "  "

#: Every part, in the order the rows show them: the names ``[statusline]`` may set, and the panel lists.
#: ``tests/test_statusline.py`` holds this to what the rows actually add, then the pet.
NAMES: tuple[str, ...] = (
    "app",
    "session",
    "handle",
    "workspace",
    "model",
    "effort",
    "state",
    "mode",
    "self-compact",
    "tokens",
    "cache",
    "speed",
    "ctx",
    "keys",
    "turn-time",
    "turn-clock",
    "turn-tokens",
    "turn-cache",
    "turn-calls",
    "turn-speed",
    "turn-tools",
    "pet",
)

#: What a name must start with to be an item of the line a request ends on (``Processed for 12s \u00b7 22:53 \u00b7 ...``).
#: The program's own items are in :data:`NAMES`; an item a plugin adds is named the same way, so that it can be
#: switched in ``[statusline]`` like any other part, and the config accepts any key that starts with this.
TURN_PREFIX = "turn-"

#: The program's own items of that line, in the order they stand, each with the sentence the panel describes it by.
TURN_PARTS: tuple[tuple[str, str], ...] = (
    ("turn-time", 'How long the request took, as "Processed for 12s"'),
    ("turn-clock", "The time of day the request ended"),
    ("turn-tokens", "Tokens sent and received by the request"),
    ("turn-cache", "The share of the request's input the provider served from its cache"),
    ("turn-calls", "How many times the model was asked; shown when more than once"),
    ("turn-speed", "How fast the model generated during the request, in tokens per second"),
    ("turn-tools", "How many tools the model used, and how many of them failed"),
)


@dataclass(frozen=True, slots=True)
class Part:
    """One part of a row.

    Attributes:
        name: What the reader calls it; the key it has in ``[statusline]``.
        summary: One line saying what it shows, written for the panel.
        text: What it shows right now, empty when it has nothing to say.
    """

    name: str
    summary: str
    text: str = ""


#: The one part that is not text on a row: the companion that stands over the conversation. It is switched
#: like the others, with ``[statusline] pet = false``, and the panel lists it under a heading of its own.
PET = Part("pet", "A small companion over the conversation; drag it anywhere, click it to pat it")


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


def is_part(name: str) -> bool:
    """Return whether ``name`` is a part: one the program has, or an item of the request line (which a plugin may add)."""
    return name in NAMES or name.startswith(TURN_PREFIX)


def unknown(names: Collection[str]) -> list[str]:
    """Return the names that are not parts, in the order given; empty when every one is."""
    return [name for name in names if not is_part(name)]


def compact_tokens(count: int) -> str:
    """Shorten a token count for the status line: ``912``, ``12.3k``, ``1.2M``."""
    if count < 1_000:
        return str(count)
    if count < 999_950:
        return f"{count / 1_000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


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
