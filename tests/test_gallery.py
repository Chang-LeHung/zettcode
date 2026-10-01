"""The gallery is the one-shot preview path, so every entry has to paint cleanly."""

from io import StringIO

import pytest

from zettcode.tui_framework.gallery import GALLERY, main, print_gallery, render_entry, select_entries


def test_gallery_names_are_unique_and_cover_the_widgets():
    names = [entry.name for entry in GALLERY]

    assert len(names) == len(set(names))
    assert {"list", "table", "dialog", "markdown"} <= set(names)


def test_every_gallery_entry_renders_without_a_terminal():
    for entry in GALLERY:
        canvas = render_entry(entry)
        painted = "".join(cell.character for row in canvas.cells for cell in row if not cell.continuation)

        assert (canvas.width, canvas.height) == (entry.size.width, entry.size.height), entry.name
        assert painted.strip(), f"{entry.name} painted nothing"


def test_gallery_previews_fit_an_eighty_column_terminal():
    for entry in GALLERY:
        assert entry.size.width <= 58, entry.name
        assert entry.size.height <= 12, entry.name


def test_print_gallery_writes_one_caption_and_frame_per_entry():
    stream = StringIO()

    print_gallery(select_entries(["list"]), color=False, stream=stream)
    text = stream.getvalue()

    assert text.startswith("### list - ")
    assert "alpha" in text
    assert "\x1b[" not in text


def test_print_gallery_can_paint_the_frame_with_colour():
    stream = StringIO()

    print_gallery(select_entries(["list"]), color=True, stream=stream)

    assert "\x1b[" in stream.getvalue()


def test_select_entries_defaults_to_everything_and_rejects_typos():
    assert select_entries(()) == GALLERY

    with pytest.raises(ValueError, match="Unknown component 'nope'"):
        select_entries(["nope"])


def test_main_lists_the_names(capsys):
    assert main(["--list"]) == 0

    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == len(GALLERY)
    assert lines[0].startswith("text ")


def test_main_reports_an_unknown_component_on_stderr(capsys):
    assert main(["nope"]) == 2

    captured = capsys.readouterr()

    assert "Unknown component 'nope'" in captured.err
    assert captured.out == ""
