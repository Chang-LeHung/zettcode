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
    from zettcode.plugin_api.entries import (
        ChangesEntry,
        MarkdownEntry,
        RelayEntry,
        TextEntry,
        ThinkingEntry,
        ToolEntry,
        WaitEntry,
    )

    entries = (
        TextEntry(id=1, kind=EntryKind.WELCOME, text="hello"),
        TextEntry(id=2, kind=EntryKind.USER, text="hello"),
        TextEntry(id=3, kind=EntryKind.NOTICE, text="saved"),
        TextEntry(id=4, kind=EntryKind.ANNOUNCEMENT, text="changed"),
        MarkdownEntry(id=5, kind=EntryKind.ANSWER),
        MarkdownEntry(id=6, kind=EntryKind.MESSAGE),
        WaitEntry(id=7, started_at=0.0),
        ThinkingEntry(id=8, text="reasoning"),
        ToolEntry(id=9, call_id="c", tool="a-tool", title="Ran a-tool"),
        ChangesEntry(id=10),
        RelayEntry(id=11, peer="peer", text="hello"),
    )

    assert {entry.kind for entry in entries} == set(EntryKind)
    assert all(DEFAULT_PRESENTERS.for_entry(entry) is not None for entry in entries)


def test_the_builtin_presenters_are_ordinary_presenters_at_the_lowest_priority():
    """Which is the whole of why a plugin's claim on a row wins without having to outrank anything."""
    assert BUILTIN_PRESENTERS and all(isinstance(presenter, Presenter) for presenter in BUILTIN_PRESENTERS)
    assert {presenter.priority for presenter in BUILTIN_PRESENTERS} == {0}


def test_the_default_registry_is_the_builtins_and_a_plugin_can_replace_one_of_them():
    class Louder(Presenter[TextEntry]):
        priority = 1

        def handle(self, entry, next):
            return self if entry.kind is EntryKind.NOTICE else next(entry)

        def lines(self, entry, width, theme, frame):
            return render_entry(entry, width, theme, frame)[:0]

    registry = Presenters(BUILTIN_PRESENTERS)
    louder = Louder()
    entry = TextEntry(id=1, kind=EntryKind.NOTICE, text="x")

    assert registry.for_entry(entry) is not louder
    assert registry.replacing(louder).for_entry(entry) is louder
    assert DEFAULT_PRESENTERS.for_entry(entry).__class__.__name__ == "NoticePresenter"


@pytest.mark.parametrize("kind", [EntryKind.NOTICE, EntryKind.USER, EntryKind.ANNOUNCEMENT])
@pytest.mark.parametrize("width", [1, 2, 7, 40, 120])
@pytest.mark.parametrize("theme", [DARK, LIGHT], ids=["dark", "light"])
def test_a_text_row_never_draws_wider_than_the_room_it_is_given(kind: EntryKind, width: int, theme):
    entry = TextEntry(id=1, kind=kind, text="a long enough line to wrap more than once, with 幅広 characters in it")

    lines = render_entry(entry, width, theme, 0)

    assert lines, "a row with text draws something"
    for line in lines:
        assert sum(display_width(span.text) for span in line.spans) <= width, (width, line)
