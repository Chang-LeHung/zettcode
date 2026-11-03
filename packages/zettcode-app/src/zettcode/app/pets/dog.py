"""The dog: a tan dog with long floppy ears, asleep when nothing is running.

Fourteen pixels by twelve, flat colour with no outline. Two dark ears hang from the top of the head to the cheeks, a
pale muzzle carries a big dark nose, and a short tail sticks out behind. At work it blinks; when patted it narrows its
eyes and pokes its tongue out.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a tan dog; it looks along the work and wags when patted"

PALETTE = {
    "B": "#e9b97a",
    "H": "#a8693a",
    "S": "#fff0d4",
    "N": "#33231a",
    "E": "#2e2230",
    "W": "#ffffff",
    "T": "#f2748c",
}

_AWAKE = (
    "...BBBBBBBB...",
    "..BBBBBBBBBB..",
    "HHBBBBBBBBBBHH",
    "HHBBWEBBWEBBHH",
    "HHBBEEBBEEBBHH",
    "HHBBBSSSSBBBHH",
    "HHBBSNNNNSBBHH",
    "HH.BSSSSSSB.HH",
    "...BBBBBBBB...",
    "..BBBBBBBBBBBH",
    "..BSSBBBBSSBBH",
    "..BSSBBBBSSBB.",
)

_ASLEEP = edited(_AWAKE, {3: "HHBBBBBBBBBBHH"})
_BLINK = _ASLEEP
_GLAD = edited(_AWAKE, {7: "HH.BSTTTTSB.HH"})
_SMILE = edited(_ASLEEP, {7: "HH.BSTTTTSB.HH"})

PET = Pet(
    "dog",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _BLINK),
        GLAD: (_GLAD, _SMILE),
    },
)
