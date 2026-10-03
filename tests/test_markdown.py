"""Tests for Markdown rendering and its incremental parse cache."""

from zettcode.tui import Canvas, Markdown, MarkdownView, Rect
from zettcode.tui.core.theme import DARK
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness
from zettcode.tui.widgets import markdown
from zettcode.tui.widgets.markdown import render_markdown, stable_cut


def test_markdown_renders_headings_lists_and_inline_markup():
    lines = render_markdown("# Title\n\nbody **bold** and `code`\n\n- one\n- two", 40, DARK)
    text = "\n".join(line.text for line in lines)

    assert "Title" in text
    assert "#" not in text
    assert "body bold and code" in text
    assert "\u00b7 one" in text and "\u00b7 two" in text
    bold = [span for line in lines for span in line.spans if span.text == "bold"]
    assert bold and bold[0].style.bold is True


def test_markdown_wraps_paragraphs_inside_the_width():
    lines = render_markdown("word " * 30, 20, DARK)

    assert len(lines) > 1
    assert all(display_width(line.text) <= 20 for line in lines)


def test_markdown_renders_fenced_code_with_a_language_label():
    lines = render_markdown("```python\nprint(1)\n```", 30, DARK)
    texts = [line.text for line in lines]

    assert texts[0].strip() == "python"
    assert texts[1] == "  print(1)"


def test_markdown_renders_a_borderless_table():
    lines = render_markdown("| Name | Count |\n| --- | ---: |\n| a | 1 |", 40, DARK)
    text = "\n".join(line.text for line in lines)

    assert "Name" in text and "Count" in text
    assert "\u2500" in text
    assert "\u256d" not in text and "\u253c" not in text and "\u2502" not in text
    assert "---" not in text
    assert all(display_width(line.text) <= 40 for line in lines)
    rule = next(line for line in lines if "\u2500" in line.text)
    # A table rule is structure, so it stays brighter than the section divider.
    assert rule.spans[0].style.foreground == DARK.subtle
    assert rule.spans[0].style.dim is False


def test_markdown_renders_a_thematic_break_as_a_full_width_rule():
    lines = render_markdown("above\n\n---\n\nbelow", 24, DARK)

    (rule,) = [line for line in lines if set(line.text.strip()) == {"\u2500"}]
    assert display_width(rule.text) == 24
    assert rule.spans[0].style.foreground == DARK.muted
    assert "".join(line.text for line in lines).count("---") == 0


def test_a_long_table_cell_wraps_instead_of_being_cut():
    value = "a very long value that does not fit"
    lines = render_markdown(f"| {value} |  |\n| --- | --- |\n| x |  |", 22, DARK)
    text = "\n".join(line.text for line in lines)
    compact = text.replace(" ", "").replace("\n", "")

    assert "\u2026" not in text
    assert value.replace(" ", "") in compact
    assert all(display_width(line.text) <= 22 for line in lines)


def test_stable_cut_stops_at_unterminated_code_fences():
    assert stable_cut("alpha\n\nbeta") == 7
    assert stable_cut("```\ncode\n\nmore") == 0
    assert stable_cut("```\ncode\n```\n\ntail") == 14
    assert stable_cut("no boundaries") == 0


def test_markdown_caches_closed_blocks_and_only_reparses_the_tail(monkeypatch):
    calls: list[str] = []
    real = markdown.render_markdown

    def spy(text: str, width: int, theme=DARK):
        calls.append(text)
        return real(text, width, theme)

    monkeypatch.setattr(markdown, "render_markdown", spy)
    document = Markdown("alpha\n\nbeta\n\n")
    first = document.lines(20)

    assert "alpha" in "\n".join(line.text for line in first)
    calls.clear()
    document.append("gamma\n\ndelta\n\n")
    second = document.lines(20)

    assert all("alpha" not in text and "beta" not in text for text in calls)
    assert any("delta" in text for text in calls)
    assert "alpha" in "\n".join(line.text for line in second)
    assert "delta" in "\n".join(line.text for line in second)

    calls.clear()
    document.lines(20)

    assert calls == []


def test_markdown_rewraps_when_the_width_changes_and_indexes_lines():
    document = Markdown("word " * 40)

    narrow = document.lines(16)
    wide = document.lines(60)

    assert len(narrow) > len(wide)
    assert document.line_count(16) == len(narrow)
    assert document.line_at(0, 16).text == narrow[0].text
    assert document.line_at(len(narrow) - 1, 16).text == narrow[-1].text


def test_markdown_source_serves_a_virtualized_window():
    view = MarkdownView()
    harness = Harness(view, width=24, height=3)
    for index in range(6):
        view.append(f"line {index}\n\n")

    rendered = harness.render().text

    assert view.follow_tail is True
    assert "line 5" in rendered
    assert "line 0" not in rendered


def test_markdown_view_paints_a_directly_mounted_document():
    view = MarkdownView("# Title\n\n**bold** body")
    view.layout(Rect(0, 0, 24, 4))
    canvas = Canvas(24, 4)

    view.render(canvas)

    painted = "\n".join("".join(cell.character for cell in row if not cell.continuation) for row in canvas.cells)
    assert "Title" in painted
    assert "bold body" in painted
