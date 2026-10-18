"""The slime: a mint jelly with a shine on its head, asleep when nothing is running.

Fourteen pixels by twelve, flat colour with no outline. A soft dome with a bright highlight, two big eyes, pink cheeks
and a small mouth, sitting on a darker base. At work it hops and a shadow appears under it; when patted it opens its
mouth wide.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a mint jelly; it hops while a request runs"

PALETTE = {
    "G": "#8fdca4",
    "D": "#5fb67c",
    "Z": "#d8f7e0",
    "E": "#23412e",
    "W": "#ffffff",
    "P": "#f08fa6",
    "M": "#c4475c",
    "S": "#6f9f80",
}

_AIR = "." * 14

_BLOCK = (
    "......GG......",
    "....GGGGGG....",
    "..GZZGGGGGGG..",
    ".GGGGGGGGGGGG.",
    "GGGWEGGGGWEGGG",
    "GGGEEGGGGEEGGG",
    "GGPGGGGGGGGPGG",
    "GGGGGGMMGGGGGG",
    "GGGGGGGGGGGGGG",
    ".DDDDDDDDDDDD.",
)

_SHADOW = "..SSSSSSSSSS.."

_REST = (_AIR, _AIR, *_BLOCK)
_HOP = (_AIR, *_BLOCK, _SHADOW)
_ASLEEP = edited(_REST, {6: "GGGGGGGGGGGGGG"})
_GLAD = edited(_REST, {6: "GGGGGGGGGGGGGG", 9: "GGGGGMMMMGGGGG"})
_SMILE = edited(_HOP, {5: "GGGGGGGGGGGGGG"})

PET = Pet(
    "slime",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_REST, _HOP),
        GLAD: (_GLAD, _SMILE),
    },
)
