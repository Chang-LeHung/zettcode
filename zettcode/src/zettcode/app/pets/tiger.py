"""The tiger: an orange tiger cub with black stripes, asleep when nothing is running.

Fourteen pixels by twelve, flat colour with no outline. Small round ears, three black stripes down the forehead and two
on each cheek, a white muzzle with a dark nose, and a striped tail behind. At work it blinks; when patted it narrows
its eyes and shows its mouth.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "an orange tiger; it keeps watch while a request runs"

PALETTE = {
    "B": "#f2993a",
    "K": "#2b1d17",
    "S": "#fff3dc",
    "N": "#3a2418",
    "E": "#2e2230",
    "W": "#ffffff",
    "T": "#f2748c",
}

_AWAKE = (
    ".BBB......BBB.",
    "BBBBB....BBBBB",
    ".BBBBBBBBBBBB.",
    "BBBKBBKKBBKBBB",
    "KKBBBBKKBBBBKK",
    "BBBWEBBBBWEBBB",
    "KKBEEBBBBEEBKK",
    "BBBBSSSSSSBBBB",
    "KKBSSSNNSSSBKK",
    ".BBBSSSSSSBBB.",
    "..BBBBBBBBBBBK",
    "..BSSBBBBSSBBB",
)

_ASLEEP = edited(_AWAKE, {5: "BBBBBBBBBBBBBB"})
_BLINK = _ASLEEP
_GLAD = edited(_AWAKE, {9: ".BBBSTTTTSBBB."})
_SMILE = edited(_ASLEEP, {9: ".BBBSTTTTSBBB."})

PET = Pet(
    "tiger",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _BLINK),
        GLAD: (_GLAD, _SMILE),
    },
)
