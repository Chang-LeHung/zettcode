"""The page a plugin's document opens: rendered as Markdown, scrolled with the keys, closed on Escape."""

from __future__ import annotations

from zettcode.app.ui.widgets import DocumentPage
from zettcode.tui.testing import Harness


def many_sections(count: int = 40) -> str:
    """Return a document too long for a small page."""
    return "\n\n".join(f"## Section {number}\n\ntext of section {number}" for number in range(1, count + 1))


def test_a_document_is_rendered_as_markdown_under_the_command_that_gave_it():
    page = DocumentPage("# Notes\n\nAll quiet.", title="/notes")

    frame = Harness(page, width=60, height=12).text()

    assert "/notes" in frame
    assert "Notes" in frame and "All quiet." in frame
    assert "esc back" in frame


def test_a_document_longer_than_the_page_scrolls_and_comes_back_home():
    page = DocumentPage(many_sections(), title="/notes")
    harness = Harness(page, width=60, height=12)

    assert "Section 1" in harness.text()
    assert "scroll" in harness.text(), "the footer says the document continues"
    harness.press("page_down")
    assert "Section 1" not in harness.text()
    harness.press("home")
    assert "Section 1" in harness.text()
    harness.press("down")
    assert page.offset == 1


def test_a_document_that_fits_says_only_that_escape_goes_back():
    page = DocumentPage("one line")

    frame = Harness(page, width=60, height=12).text()

    assert "one line" in frame and "scroll" not in frame


def test_escape_and_q_leave_the_page_and_other_keys_do_not():
    cancelled: list[bool] = []
    page = DocumentPage("# Notes", on_cancel=lambda: cancelled.append(True))
    harness = Harness(page, width=60, height=12)

    harness.write("x")
    assert cancelled == []

    harness.press("escape")
    assert cancelled == [True]

    harness.press("q")
    assert cancelled == [True, True]
