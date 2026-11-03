"""The chibi: an original anime-style girl, asleep when nothing is running.

Fourteen pixels by fourteen, flat colour with no outline. A rounded bob of violet hair with a pink ribbon each side and
two short tails, a pale face with two big eyes lit from the same side, pink cheeks and a small mouth, and a collar
below. She is not drawn from any existing character. At work her eyes look about; when patted she closes them and
smiles.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "an original anime-style girl; her eyes follow the work"

PALETTE = {
    "H": "#b79ae0",
    "F": "#fbe3cd",
    "E": "#3b2b3f",
    "W": "#ffffff",
    "P": "#f08fa6",
    "M": "#c4475c",
    "R": "#e8737f",
}

_AWAKE = (
    "....HHHHHH....",
    "..HHHHHHHHHH..",
    ".HHHHHHHHHHHH.",
    "HHHHHHHHHHHHHH",
    "HHHFFFFFFFFHHH",
    "PHFFFFFFFFFFHP",
    "HHFWEFFFFWEFHH",
    "HHFEEFFFFEEFHH",
    "HHFPFFFFFFPFHH",
    "HHFFFFMMFFFFHH",
    "HHHFFFFFFFFHHH",
    ".HH..FFFF..HH.",
    ".HH.RRRRRR.HH.",
    "..H.RRRRRR.H..",
)

_ASLEEP = edited(_AWAKE, {6: "HHFFFFFFFFFFHH"})
_LOOKING = edited(_AWAKE, {6: "HHFFWEFFFFWEHH", 7: "HHFFEEFFFFEEHH"})
_GLAD = edited(_AWAKE, {6: "HHFFFFFFFFFFHH", 9: "HHFFFMMMMFFFHH"})
_SMILE = edited(_AWAKE, {6: "HHFFFFFFFFFFHH"})

PET = Pet(
    "chibi",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _LOOKING),
        GLAD: (_GLAD, _SMILE),
    },
)
