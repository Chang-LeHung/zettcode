"""The cat: a ginger cat sitting up, asleep when nothing is running.

Fourteen pixels by twelve, flat colour with no outline. Two pointed ears with pink insides, whiskers that reach past the
face, a cream muzzle with a pink nose, white paws and a tail curling up behind. At work it blinks; when patted it
narrows its eyes into a smile and opens its mouth.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a ginger cat; it blinks along while a request runs"

PALETTE = {
    "B": "#f4a95a",
    "D": "#7a4a2a",
    "S": "#fff1d6",
    "P": "#f48fa0",
    "E": "#2e2230",
    "W": "#ffffff",
    "M": "#c4475c",
}

_AWAKE = (
    ".B..........B.",
    ".BB........BB.",
    ".BPB......BPB.",
    ".BPPBBBBBBPPB.",
    ".BBBBBBBBBBBB.",
    "DBBWEBBBBWEBBD",
    ".BBEEBBBBEEBB.",
    "DBBBBSPPSBBBBD",
    ".BBBBSDDSBBBB.",
    "..BBBBBBBBBB.D",
    "..BSSBBBBSSBBB",
    "..BSSBBBBSSBB.",
)

_ASLEEP = edited(_AWAKE, {5: "DBBBBBBBBBBBBD"})
_BLINK = edited(_AWAKE, {5: "DBBBBBBBBBBBBD"})
_GLAD = edited(_AWAKE, {6: ".BBEEBBBBEEBB.", 8: ".BBBBSMMSBBBB."})
_SMILE = edited(_AWAKE, {5: "DBBBBBBBBBBBBD", 8: ".BBBBSMMSBBBB."})

PET = Pet(
    "cat",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _BLINK),
        GLAD: (_GLAD, _SMILE),
    },
)
