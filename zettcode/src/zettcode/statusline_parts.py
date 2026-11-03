"""The names the header and the status line are made of: what ``[statusline]`` may set, and what a part is.

The configuration validates the table against these names, so they live here, in the engine's shipped leaves, and not
in :mod:`zettcode.statusline`, which paints the parts and therefore imports the widget framework and the usage types.
That module re-exports everything here, so a reader of the terminal still imports one place.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

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


def is_part(name: str) -> bool:
    """Return whether ``name`` is a part: one the program has, or an item of the request line (which a plugin may add)."""
    return name in NAMES or name.startswith(TURN_PREFIX)


def unknown(names: Collection[str]) -> list[str]:
    """Return the names that are not parts, in the order given; empty when every one is."""
    return [name for name in names if not is_part(name)]
