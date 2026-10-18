"""The seagull: a pale grey-blue gull with slate wings, asleep when nothing is running and flapping at work.

Fourteen pixels by twelve, flat colour with no outline. A round head with a dark eye on each side and a yellow beak, a
light belly between two slate wings, and two orange feet. At work the wings lift and fall; when patted it closes its
eyes and opens its beak.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a seagull; it flaps its wings while a request runs"

PALETTE = {
    "B": "#d5e0ea",
    "G": "#7f95aa",
    "S": "#f4f8fb",
    "Y": "#f2c14e",
    "O": "#ee8a3c",
    "E": "#1f2230",
    "M": "#c4475c",
}

_DOWN = (
    "....BBBBBB....",
    "...BBBBBBBB...",
    "..BBBBBBBBBB..",
    "..BBEBBBBEBB..",
    "..BBBBYYBBBB..",
    "...BBBYYBBB...",
    "..GGBBBBBBGG..",
    ".GGGBBSSBBGGG.",
    ".GGGBSSSSBGGG.",
    "..GGBSSSSBGG..",
    "....BBBBBB....",
    "....OO..OO....",
)

_UP = edited(
    _DOWN,
    {
        5: ".GGBBBYYBBBGG.",
        6: ".GGGBBBBBBGGG.",
        7: "..GGBBSSBBGG..",
        8: "...GBSSSSBG...",
        9: "....BSSSSB....",
    },
)

_ASLEEP = edited(_DOWN, {3: "..BBBBBBBBBB.."})
_ASLEEP_UP = edited(_UP, {3: "..BBBBBBBBBB.."})
_GLAD = edited(_ASLEEP, {5: "...BBBMMBBB..."})
_SMILE = edited(_ASLEEP_UP, {5: ".GGBBBMMBBBGG."})

PET = Pet(
    "seagull",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_DOWN, _UP),
        GLAD: (_GLAD, _SMILE),
    },
)
