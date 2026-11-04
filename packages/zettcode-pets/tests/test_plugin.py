"""The pets plugin offers every bundled pet by name and builds nothing until one is asked for."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from zettcode.pets import BUNDLED, bundled_pets
from zettcode.pets.plugin import PetsPlugin
from zettcode.plugin_api.pets import DEFAULT_PET_NAME, PetCatalog


def test_the_default_pet_is_one_of_the_pets_that_ship():
    assert DEFAULT_PET_NAME in BUNDLED


def test_every_module_beside_the_others_is_listed_and_every_listed_name_has_a_module():
    folder = Path(importlib.import_module("zettcode.pets").__file__).parent
    assert {path.stem for path in folder.glob("*.py")} - {"__init__", "plugin"} == set(BUNDLED)


@pytest.mark.parametrize("name", BUNDLED)
def test_every_pet_builds_and_is_described(name: str):
    catalog = PetCatalog(bundled_pets())

    assert catalog.load(name).name == name
    assert catalog.notes()[name]


def test_the_plugin_registers_each_pet_in_order_and_does_nothing_without_a_screen():
    registered: list[str] = []
    tui = SimpleNamespace(register_pet=lambda name, load, *, description: registered.append(name))

    PetsPlugin().activate(SimpleNamespace(tui=None))  # type: ignore[arg-type]
    assert registered == []
    PetsPlugin().activate(SimpleNamespace(tui=tui))  # type: ignore[arg-type]
    assert registered == list(BUNDLED)
