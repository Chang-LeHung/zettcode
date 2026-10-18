"""Scarfy: a penguin in a red scarf, seen from the side and looking right, asleep when nothing is running.

Sixteen pixels by fourteen, flat colour with a dark outline, which is what keeps the pale belly on a light terminal.
A round head with two eyes looking ahead and an orange beak, a red scarf whose tail hangs down the chest, a white belly
and two orange feet. At work the scarf swings and the eyes close in a blink; when patted it squints, blushes and opens
its beak.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a penguin in a red scarf; the scarf swings while a request runs"

PALETTE = {
    "O": "#141a2e",
    "B": "#2d3a5c",
    "S": "#f6f9ff",
    "G": "#d0dbef",
    "R": "#e8776a",
    "r": "#b84a42",
    "Y": "#f0a63a",
    "F": "#e8a03a",
    "W": "#ffffff",
    "E": "#0d1020",
    "M": "#c4475c",
    "P": "#e88aa0",
}

_AWAKE = (
    "....OOOOOOO.....",
    "...OBBBBBBBO....",
    "..OBBBBBBBBBO...",
    "..OBWEBBWEBBBO..",
    "..OBBBBBBBBYYYO.",
    "..ORRRRRRRRRRRO.",
    ".OBRRBSSSSSSBBBO",
    ".OBRrBSSSSSSSBBO",
    ".OBBBSSSSSSGSBBO",
    ".OBBBSSSSSSGGBBO",
    "..OBBSSSSSSGBBO.",
    "...OBBSSSSSBBO..",
    "....OOBBBBBOO...",
    "..FFFFF..FFFFF..",
)

_SHUT = {3: "..OBEEBBEEBBBO.."}
_ASLEEP = edited(_AWAKE, _SHUT)
_SWAY = edited(_AWAKE, {3: "..OBEEBBEEBBBO..", 6: ".OBBRRSSSSSSBBBO", 7: ".OBBBRSSSSSSSBBO"})
_GLAD = edited(_ASLEEP, {4: "..OBBBBPPBBYMYO."})
_SMILE = edited(_SWAY, {4: "..OBBBBPPBBYMYO."})

PET = Pet(
    "scarfy",
    PALETTE,
    {
        IDLE: (_ASLEEP,),
        WORKING: (_AWAKE, _SWAY),
        GLAD: (_GLAD, _SMILE),
    },
)
