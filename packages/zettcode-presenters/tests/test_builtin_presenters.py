"""The rows the program draws are complete, and they are drawn through the contract and not around it."""

from __future__ import annotations

import pytest

from zettcode.plugin_api.entries import EntryKind, TextEntry
from zettcode.plugin_api.presenters import Presenter, Presenters
from zettcode.presenters.presenters import BUILTIN_PRESENTERS, DEFAULT_PRESENTERS, render_entry
from zettcode.tui import DARK, LIGHT
from zettcode.tui.render import display_width


def test_every_kind_of_row_has_a_builtin_presenter():
    """A transcript with a kind nobody draws raises at the first row of it; that is how a new kind is caught."""
    drawn = {presenter.kind for presenter in DEFAULT_PRESENTERS.presenters}

    assert set(EntryKind) == drawn, set(EntryKind) ^ drawn


def test_the_builtin_presenters_are_ordinary_presenters_at_the_lowest_priority():
    """Which is the whole of why a plugin's claim on a row wins without having to outrank anything."""
    assert BUILTIN_PRESENTERS and all(isinstance(presenter, Presenter) for presenter in BUILTIN_PRESENTERS)
    assert {presenter.priority for presenter in BUILTIN_PRESENTERS} == {0}


def test_the_default_registry_is_the_builtins_and_a_plugin_can_replace_one_of_them():
    class Louder(Presenter[TextEntry]):
        kind = EntryKind.NOTICE
        priority = 1

        def lines(self, entry, width, theme, frame):
            return render_entry(entry, width, theme, frame)[:0]

    registry = Presenters(BUILTIN_PRESENTERS)
    louder = Louder()
    entry = TextEntry(id=1, kind=EntryKind.NOTICE, text="x")

    assert registry.for_entry(entry) is not louder
    assert registry.replacing(louder).for_entry(entry) is louder
    assert DEFAULT_PRESENTERS.for_entry(entry).kind is EntryKind.NOTICE


@pytest.mark.parametrize("kind", [EntryKind.NOTICE, EntryKind.USER, EntryKind.ANNOUNCEMENT])
@pytest.mark.parametrize("width", [1, 2, 7, 40, 120])
@pytest.mark.parametrize("theme", [DARK, LIGHT], ids=["dark", "light"])
def test_a_text_row_never_draws_wider_than_the_room_it_is_given(kind: EntryKind, width: int, theme):
    entry = TextEntry(id=1, kind=kind, text="a long enough line to wrap more than once, with 幅広 characters in it")

    lines = render_entry(entry, width, theme, 0)

    assert lines, "a row with text draws something"
    for line in lines:
        assert sum(display_width(span.text) for span in line.spans) <= width, (width, line)
