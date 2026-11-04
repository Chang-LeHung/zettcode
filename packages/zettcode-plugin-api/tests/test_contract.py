"""The plugin contract is the bottom of the graph it defines, and says only what it can keep.

Three things hold the design up, and each is checked where it can be broken: the facade names exactly what it
resolves, importing a contract module pulls nothing of the program in with it, and the registry the presenters are
registered into obeys the priority rule the guide promises.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

import zettcode.plugin_api as api
from zettcode.plugin_api.entries import EntryKind, TextEntry
from zettcode.plugin_api.presenters import Presenter, Presenters
from zettcode.tui import DARK, Span, Style, TextLine


def test_the_facade_publishes_what_it_maps_and_every_name_resolves():
    assert sorted(api._EXPORTS) == sorted(api.__all__)
    for name in api.__all__:
        assert getattr(api, name) is not None, name


def test_an_unknown_name_is_an_attribute_error_and_not_a_silent_none():
    with pytest.raises(AttributeError, match="no attribute 'Nothing'"):
        api.Nothing  # noqa: B018


@pytest.mark.parametrize(
    "module", ["zettcode.plugin_api.presenters", "zettcode.plugin_api.entries", "zettcode.plugin_api.panels"]
)
def test_importing_a_contract_module_pulls_nothing_of_the_program_in(module: str):
    """The boot frame is drawn before the settings, the runtime or a provider SDK exist, and it imports these."""
    script = (
        f"import sys, {module}\n"
        "heavy = ('zettcode.app', 'zettcode.presenters', 'zettcode.config', 'zett_agent', 'zettcode.sdk')\n"
        "print(sorted(name for name in sys.modules if name == 'zettcode.app' or name.startswith(heavy)))\n"
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]", result.stdout


def test_the_contract_names_no_implementation_of_itself():
    """The built-in rows, the shell and the loader are written against these modules, never the other way round."""
    files = sorted(Path(api.__file__).parent.glob("*.py"))
    assert len(files) > 8, files
    for file in files:
        body = file.read_text(encoding="utf-8")
        for implementation in ("zettcode.app", "zettcode.presenters"):
            assert f"from {implementation}" not in body and f"import {implementation}" not in body, (
                file.name,
                implementation,
            )


class _Notice(Presenter[TextEntry]):
    kind: ClassVar[EntryKind] = EntryKind.NOTICE

    def __init__(self, label: str, priority: int = 0) -> None:
        self.label = label
        self.priority = priority  # type: ignore[misc]

    def lines(self, entry: TextEntry, width: int, theme, frame: int) -> list[TextLine]:
        return [TextLine((Span(self.label, Style()),))]


def _entry() -> TextEntry:
    return TextEntry(id=1, kind=EntryKind.NOTICE, text="hello")


def test_the_stronger_claim_on_a_row_wins_and_an_equal_one_goes_to_the_later():
    first, second, strong = _Notice("first"), _Notice("second"), _Notice("strong", priority=5)

    assert Presenters([first, second]).for_entry(_entry()) is second
    assert Presenters([strong, first, second]).for_entry(_entry()) is strong


def test_replacing_appends_so_a_plugin_that_registers_last_draws_the_row():
    registry = Presenters([_Notice("built in")])
    mine = _Notice("mine")

    assert registry.replacing(mine).for_entry(_entry()) is mine
    assert registry.replacing(mine).lines(_entry(), 20, DARK, 0)[0].spans[0].text == "mine"
