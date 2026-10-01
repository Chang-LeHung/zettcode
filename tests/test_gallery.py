"""The gallery is the preview path, so every entry has to paint cleanly."""

from io import StringIO

import pytest

from zettcode.tui_framework.gallery import (
    GALLERY,
    GalleryBrowser,
    main,
    print_gallery,
    render_entry,
    select_entries,
)
from zettcode.tui_framework.testing import Harness


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


def test_main_prints_instead_of_browsing_without_a_terminal(capsys):
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("### text - ")

    assert main(["--print"]) == 0
    assert capsys.readouterr().out.startswith("### text - ")


def test_the_browser_keeps_an_index_beside_a_live_preview():
    browser = GalleryBrowser()
    harness = Harness(app=browser.app)
    harness.app.resize(90, 20)

    text = harness.render().text

    assert "components" in text
    assert "status_bar" in text
    assert "bold heading" in text

    harness.press("down")

    assert "openai/gpt-5" in harness.render().text


def test_the_browser_hands_the_keyboard_to_a_focusable_preview():
    browser = GalleryBrowser()
    harness = Harness(app=browser.app)
    browser.list.select([entry.name for entry in browser.entries].index("textarea"))

    assert "explain the diff widget" in harness.render().text

    harness.press("enter")
    assert browser.app.focused_widget() is not browser.list

    harness.press("escape")
    assert browser.app.focused_widget() is browser.list


def test_q_quits_only_while_the_index_holds_the_keyboard():
    browser = GalleryBrowser()
    harness = Harness(app=browser.app)
    browser.list.select([entry.name for entry in browser.entries].index("textarea"))
    harness.press("enter")

    harness.write("x")

    assert harness.exited is False

    harness.press("escape")
    # The real terminal delivers a printable key as text, not as a named key.
    harness.write("q")

    assert harness.exited is True


def test_main_reports_an_unknown_component_on_stderr(capsys):
    assert main(["nope"]) == 2

    captured = capsys.readouterr()

    assert "Unknown component 'nope'" in captured.err
    assert captured.out == ""
