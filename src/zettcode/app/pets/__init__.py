"""The pets: what one is, the catalog that finds one by name, and the seven that ship.

The sprites live one to a module (``cat``, ``dog``, ``tiger``, ``whale``, ``chibi``, ``slime``, ``sprout``) and are
built only when asked for, so offering all of them costs a start nothing; the built-in plugin registers them through
``register_pet`` exactly as another plugin would register its own.
"""

from __future__ import annotations

import importlib

from .model import GLAD, IDLE, PET_NAME, WORKING, Pet, PetCatalog, PetSource, edited, mirrored

#: The pets that ship, in the order the ``/pet`` menu lists them.
BUNDLED = ("cat", "dog", "tiger", "whale", "chibi", "slime", "sprout")

#: The pet a reader has without choosing one.
DEFAULT_PET_NAME = "cat"


def _module(name: str):
    return importlib.import_module(f"{__name__}.{name}")


def _source(name: str) -> PetSource:
    """Describe one bundled pet; its module is imported when the pet or its note is first asked for."""
    return PetSource(name, lambda: _module(name).PET, lambda: _module(name).DESCRIPTION)


def bundled_pets() -> tuple[PetSource, ...]:
    """Return the pets that ship as sources: each builds its sprite when it is first asked for."""
    return tuple(_source(name) for name in BUNDLED)


__all__ = [
    "BUNDLED",
    "DEFAULT_PET_NAME",
    "GLAD",
    "IDLE",
    "PET_NAME",
    "WORKING",
    "Pet",
    "PetCatalog",
    "PetSource",
    "bundled_pets",
    "edited",
    "mirrored",
]
