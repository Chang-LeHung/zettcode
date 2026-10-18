"""The sprout: a seedling in a warm pot, asleep when nothing is running.

Fourteen pixels by fourteen, flat colour with no outline. Two leaves on a stem above a round pot, and in the pot a face
with two big eyes, pink cheeks and a small mouth. The leaves lift while a request runs and droop when nothing does;
when patted it closes its eyes.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a seedling in a pot; its leaves lift while a request runs"

PALETTE = {
    "L": "#7fc46a",
    "Z": "#b8e8a4",
    "S": "#4f9a4a",
    "P": "#e8a96b",
    "Q": "#c98a50",
    "E": "#3a2a1c",
    "W": "#ffffff",
    "B": "#f08fa6",
    "M": "#b04a52",
}

_AWAKE = (
    "..............",
    "..ZZL....LLL..",
    ".ZLLLL..LLLLL.",
    "..LLLL..LLLL..",
    "....LLSSLL....",
    ".......S......",
    ".......S......",
    "..QQQQQQQQQQ..",
    ".PPPPPPPPPPPP.",
    ".PPWEPPPPWEPP.",
    ".PPEEPPPPEEPP.",
    ".PBPPPMMPPPBP.",
    "..PPPPPPPPPP..",
    "...QQQQQQQQ...",
)

_DROOP = edited(
    _AWAKE,
    {
        1: "..............",
        2: "..............",
        3: ".ZLL......LLL.",
        4: "ZLLLL.S..LLLLL",
    },
)
_ASLEEP = edited(_DROOP, {9: ".PPPPPPPPPPPP."})
_HAPPY = edited(_AWAKE, {9: ".PPPPPPPPPPPP.", 11: ".PBPPMMMMPPBP."})
_SMILE = edited(_AWAKE, {9: ".PPPPPPPPPPPP."})

PET = Pet(
    "sprout",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_DROOP, _AWAKE),
        GLAD: (_HAPPY, _SMILE),
    },
)
