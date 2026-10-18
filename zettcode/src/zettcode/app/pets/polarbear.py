"""The polar bear: a white bear sitting up, asleep when nothing is running.

Fourteen pixels by twelve, flat colour with no outline. Two round ears with icy insides, small dark eyes, a pale muzzle
with a big dark nose, and blue-grey paws. At work it blinks; when patted it closes its eyes, blushes and smiles.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a white polar bear; it blinks along while a request runs"

PALETTE = {
    "B": "#f2f5f7",
    "H": "#a9c3d6",
    "S": "#dbe7ef",
    "N": "#2a2a33",
    "E": "#2e2230",
    "P": "#f4a6b4",
    "M": "#c4475c",
}

_AWAKE = (
    ".BBB......BBB.",
    ".BHBBBBBBBBHB.",
    ".BBBBBBBBBBBB.",
    ".BBEEBBBBEEBB.",
    ".BBEEBBBBEEBB.",
    ".BBBBSSSSBBBB.",
    ".BBBSSNNSSBBB.",
    "..BBSSSSSSBB..",
    "..BBBBBBBBBB..",
    ".BBBBBBBBBBBB.",
    ".BBHHBBBBHHBB.",
    ".BBHHBBBBHHBB.",
)

_ASLEEP = edited(_AWAKE, {3: ".BBBBBBBBBBBB."})
_GLAD = edited(_ASLEEP, {5: ".BBPBSSSSBPBB.", 7: "..BBSSMMSSBB.."})
_SMILE = edited(_ASLEEP, {5: ".BBPBSSSSBPBB."})

PET = Pet(
    "polarbear",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _ASLEEP),
        GLAD: (_GLAD, _SMILE),
    },
)
