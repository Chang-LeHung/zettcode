"""The whale: a round blue whale, asleep when nothing is running and spouting at work.

Fourteen pixels by twelve, flat colour with no outline. A round body with two big eyes, pink cheeks and a pale belly,
a darker tail lifted at the back, and a spout above the head. The spout is the thing that moves: a low plume, then a
high one. When patted it closes its eyes and opens its mouth.
"""

from __future__ import annotations

from .model import GLAD, IDLE, WORKING, Pet, edited

DESCRIPTION = "a blue whale; it spouts while a request runs"

PALETTE = {
    "B": "#6ba8c4",
    "D": "#4a7a94",
    "S": "#e3eef3",
    "E": "#2b3a42",
    "W": "#ffffff",
    "P": "#f08fa6",
    "M": "#c4475c",
    "I": "#bfe3f2",
}

_BODY = (
    "..............",
    "..............",
    "...........D.D",
    "............DD",
    "....BBBBBBBDD.",
    "..BBBBBBBBBBB.",
    ".BBBBBBBBBBBB.",
    ".BBWEBBWEBBBB.",
    ".BBEEBBEEBBBB.",
    ".BPBBMMBBPBBB.",
    ".SSSSSSSSSSSS.",
    "..SSSSSSSSSS..",
)

_SPOUT = edited(_BODY, {3: "......I.....DD"})
_HIGH = edited(_BODY, {1: "......I.......", 2: ".....I.I...D.D", 3: "......I.....DD"})
_OFF = edited(_BODY, {7: ".BBBBBBBBBBBB."})
_GLAD = edited(_BODY, {7: ".BBBBBBBBBBBB.", 9: ".BPBMMMMBPBBB."})
_SMILE = edited(_BODY, {7: ".BBBBBBBBBBBB."})

PET = Pet(
    "whale",
    PALETTE,
    {
        IDLE: (_OFF,),
        WORKING: (_SPOUT, _HIGH),
        GLAD: (_GLAD, _SMILE),
    },
)
