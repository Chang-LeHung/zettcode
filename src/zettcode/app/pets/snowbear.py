"""The snow bear: a big white polar bear sitting side on and looking left, asleep when nothing is running.

Eighteen pixels by fourteen, flat colour with a slate outline, which is what keeps a white bear on a light terminal. A
long snout with a dark nose, two round ears with pink insides, a heavy back sloping down to the right, two front legs
and a haunch. At work an ear flicks and it blinks; when patted it squints, blushes and shows its tongue.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a white bear sitting side on; an ear flicks while a request runs"

PALETTE = {
    "O": "#44527a",
    "W": "#f4f8ff",
    "H": "#d4def0",
    "P": "#eab6c0",
    "E": "#1a1d2b",
    "M": "#d05a6e",
}

_AWAKE = (
    "....OOO..OOO......",
    "...OWPWOOWPWO.....",
    "..OWWWWWWWWWWO....",
    ".OWEWWWWWWWWWWO...",
    "OEWHHWWWWWWWWWWO..",
    ".OOHHHWWWWWWWWWWO.",
    "...OWWWWWWWWWWWWWO",
    "..OWWWWWWWWWWWWWWO",
    "..OWWWHWWWWWWWWWWO",
    "..OWWWHWWWWWWHHWWO",
    "..OWWWHWWWWWWHHWO.",
    "..OWWWHWWWWWWWWO..",
    ".OWWWWHWWWWWWWWO..",
    ".OOOOOOOOOOOOOOO..",
)

_EAR = {0: "....OOO...OOO.....", 1: "...OWPWO.OWPWO...."}
_SQUINT = {3: ".OEEWWWWWWWWWWO..."}
_ASLEEP = edited(_AWAKE, _SQUINT)
_FLICK = edited(_AWAKE, {**_EAR, **_SQUINT})
_GLAD = edited(_ASLEEP, {4: "OEWHHPPWWWWWWWWO..", 5: ".OOMMHWWWWWWWWWWO."})
_SMILE = edited(_GLAD, _EAR)

PET = Pet(
    "snowbear",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _FLICK),
        GLAD: (_GLAD, _SMILE),
    },
)
