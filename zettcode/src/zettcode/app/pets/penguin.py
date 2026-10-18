"""The penguin: a navy penguin with a white belly, asleep when nothing is running and flapping at work.

Fourteen pixels by twelve, flat colour with no outline. A dark round head with two white eyes and an orange beak, a
pale belly, flippers at the sides and two orange feet. At work the flippers go up and down; when patted it closes its
eyes and opens its beak.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a navy penguin; it flaps its flippers while a request runs"

PALETTE = {
    "B": "#3d4f6b",
    "S": "#f6f3ea",
    "O": "#f2a03d",
    "E": "#1e1a24",
    "W": "#ffffff",
    "M": "#c4475c",
}

_AWAKE = (
    "....BBBBBB....",
    "...BBBBBBBB...",
    "..BBBBBBBBBB..",
    "..BBWWBBWWBB..",
    "..BBWEBBWEBB..",
    "..BBBOOOOBBB..",
    ".BBBSSSSSSBBB.",
    "BBBSSSSSSSSBBB",
    "BB.SSSSSSSS.BB",
    "B..SSSSSSSS..B",
    "...BSSSSSSB...",
    "..OOO....OOO..",
)

_FLAP = edited(
    _AWAKE,
    {
        6: "BBBBSSSSSSBBBB",
        7: "B.BSSSSSSSSB.B",
        8: "...SSSSSSSS...",
        9: "...SSSSSSSS...",
    },
)

_ASLEEP = edited(_AWAKE, {3: "..BBBBBBBBBB..", 4: "..BBWWBBWWBB.."})
_GLAD = edited(_ASLEEP, {6: ".BBBSSMMSSBBB."})
_SMILE = edited(_ASLEEP, {6: "BBBBSSSSSSBBBB", 7: "B.BSSSSSSSSB.B", 8: "...SSSSSSSS...", 9: "...SSSSSSSS..."})

PET = Pet(
    "penguin",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _FLAP),
        GLAD: (_GLAD, _SMILE),
    },
)
