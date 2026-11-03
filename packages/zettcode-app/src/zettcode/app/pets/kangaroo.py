"""The kangaroo: a russet kangaroo standing up, asleep when nothing is running and hopping at work.

Fourteen pixels by fourteen, flat colour with no outline. Two tall ears with pink insides, a pale muzzle with a dark
nose, a cream chest and pouch, two big hind feet and a tail behind. The picture has one blank row at the top; the hop
is the same drawing lifted by that row. When patted it closes its eyes and opens its mouth.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a russet kangaroo; it hops while a request runs"

PALETTE = {
    "B": "#b9714a",
    "D": "#7d4a2e",
    "S": "#ecc9a0",
    "P": "#f0a6a0",
    "N": "#2e2230",
    "M": "#c4475c",
}

_BLANK = "." * 14

_DRAWN = (
    "..BB......BB..",
    "..BPB....BPB..",
    "..BPBBBBBBPB..",
    "...BBBBBBBB...",
    "...BBNBBNBB...",
    "...BBSSSSBB...",
    "....BSNNSB....",
    "...BBSSSSBB...",
    "..BBSSSSSSBBD.",
    "..BBSSSSSSBBDD",
    "...BSSSSSSB.D.",
    "...BBB..BBB.DD",
    "..DDDD..DDDD..",
)

_STAND = (_BLANK, *_DRAWN)
_HOP = (*_DRAWN, _BLANK)

# With the blank row on top the eyes are row 5 and the mouth row 7; lifted by the hop they are rows 4 and 6.
_ASLEEP = edited(_STAND, {5: "...BBBBBBBB..."})
_HOP_SHUT = edited(_HOP, {4: "...BBBBBBBB..."})
_GLAD = edited(_ASLEEP, {7: "....BSMMSB...."})
_SMILE = edited(_HOP_SHUT, {6: "....BSMMSB...."})

PET = Pet(
    "kangaroo",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_STAND, _HOP),
        GLAD: (_GLAD, _SMILE),
    },
)
