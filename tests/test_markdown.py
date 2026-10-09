"""Tests for Markdown rendering and its incremental parse cache."""

from html.entities import html5

from zettcode.tui import LIGHT, Canvas, Markdown, MarkdownView, Rect
from zettcode.tui.core.theme import DARK
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness
from zettcode.tui.widgets import markdown
from zettcode.tui.widgets.markdown import (
    _ENTITY,
    decode_entities,
    inline_markdown,
    render_markdown,
    stable_cut,
)


def test_markdown_renders_headings_lists_and_inline_markup():
    lines = render_markdown("# Title\n\nbody **bold** and `code`\n\n- one\n- two", 40, DARK)
    text = "\n".join(line.text for line in lines)

    assert "Title" in text
    assert "#" not in text
    assert "body bold and code" in text
    assert "\u00b7 one" in text and "\u00b7 two" in text
    bold = [span for line in lines for span in line.spans if span.text == "bold"]
    assert bold and bold[0].style.bold is True


def test_markdown_rerenders_when_the_theme_changes():
    """The cached blocks are keyed by theme, not only by width and length.

    A theme switch keeps the same text and width, so a cache that ignored the
    palette would keep painting the previous colours.
    """
    document = Markdown("## Title\n\nbody with `code` and a [link](https://x.dev)")
    dark_heading = document.line_at(0, 44)
    dark_code = [span for span in document.line_at(3, 44).spans if span.text == "code"][0]

    document.theme = LIGHT
    light_heading = document.line_at(0, 44)
    light_code = [span for span in document.line_at(3, 44).spans if span.text == "code"][0]

    assert dark_heading.spans[0].style.foreground == DARK.text
    assert dark_code.style.foreground == DARK.code.inline
    assert light_heading.spans[0].style.foreground == LIGHT.text
    assert light_code.style.foreground == LIGHT.code.inline


def test_backtick_runs_open_one_code_span():
    """A span delimited by N backticks may hold backticks of its own.

    Models write this for anything that contains a backtick, and a parser that
    only knew single delimiters would spill the delimiters into the prose.
    """
    spans = inline_markdown("`` `lessons/01`-`05` `` — runnable", theme=DARK)

    assert [(span.text, span.style.foreground) for span in spans] == [
        ("`lessons/01`-`05`", DARK.code.inline),
        (" \u2014 runnable", DARK.text),
    ]


def test_emphasis_can_wrap_a_code_span():
    """A code span is atomic, so the delimiters around it cannot reach inside.

    Matching every inline rule in one pass let ``**...**`` swallow the
    backticks, so the span inside bold text leaked as literal characters.
    """
    spans = inline_markdown("**bold `code` bold**", theme=DARK)

    assert [(span.text, span.style.bold, span.style.foreground) for span in spans] == [
        ("bold ", True, DARK.text),
        ("code", False, DARK.code.inline),
        (" bold", True, DARK.text),
    ]


def test_emphasis_inside_a_code_span_stays_literal():
    spans = inline_markdown("`**not bold**`", theme=DARK)

    assert [(span.text, span.style.bold, span.style.foreground) for span in spans] == [
        ("**not bold**", False, DARK.code.inline)
    ]


def test_strikethrough_wraps_text_and_nests_with_emphasis():
    spans = inline_markdown("~~gone~~ and ~~**bold struck**~~", theme=DARK)

    assert [(span.text, span.style.strike, span.style.bold) for span in spans] == [
        ("gone", True, False),
        (" and ", False, False),
        ("bold struck", True, True),
    ]


def test_a_code_span_inside_strikethrough_stays_code():
    """The strike wraps the prose around it, not the code span itself."""
    spans = inline_markdown("~~a `x` b~~", theme=DARK)

    assert [(span.text, span.style.strike, span.style.foreground) for span in spans] == [
        ("a ", True, DARK.text),
        ("x", False, DARK.code.inline),
        (" b", True, DARK.text),
    ]


def test_markdown_wraps_paragraphs_inside_the_width():
    lines = render_markdown("word " * 30, 20, DARK)

    assert len(lines) > 1
    assert all(display_width(line.text) <= 20 for line in lines)


def test_list_items_are_inset_and_wrap_under_their_own_text():
    lines = render_markdown("- a long item that has to wrap somewhere, twice over", 26, DARK)
    texts = [line.text for line in lines]

    # The marker is one level in from the prose, and the wrapped rows line up
    # under the item's text rather than falling back to the margin.
    assert texts[0].startswith("  \u00b7 a long item")
    assert texts[1].startswith("    ")
    assert all(display_width(text) <= 26 for text in texts)


def test_ordered_and_nested_items_keep_their_levels():
    lines = render_markdown("1. first\n   - nested\n2. second", 40, DARK)

    assert [line.text for line in lines] == ["  1. first", "     \u00b7 nested", "  2. second"]


def test_markdown_highlights_fenced_code_without_drawing_the_label():
    lines = render_markdown("```python\ndef parse(x):\n    return x\n```", 30, DARK)
    texts = [line.text for line in lines]

    # The label selects the scanner and is never part of the block.
    assert "python" not in "\n".join(texts)
    assert texts[0] == "  def parse(x):"
    keyword = next(span for line in lines for span in line.spans if span.text == "def")
    assert keyword.style.foreground == DARK.code.keyword


def test_markdown_draws_a_rule_under_the_header_and_every_row():
    lines = render_markdown("| Name | Count |\n| --- | ---: |\n| a | 1 |\n| b | 2 |", 40, DARK)
    text = "\n".join(line.text for line in lines)

    assert "Name" in text and "Count" in text
    assert "\u256d" not in text and "\u253c" not in text and "\u2502" not in text
    assert "---" not in text
    assert all(display_width(line.text) <= 40 for line in lines)
    rules = [line for line in lines if line.text.strip() and set(line.text.strip()) <= {"\u2500", " "}]
    # One under the header, one closing each of the two data rows.
    assert len(rules) == 3
    for rule in rules:
        # A table rule is structure, so it stays brighter than the section divider.
        assert rule.spans[0].style.foreground == DARK.subtle
        assert rule.spans[0].style.dim is False


def test_inline_underscores_inside_a_word_are_not_emphasis():
    lines = render_markdown("`code` and replace_in_file and _italic_", 48, DARK)
    text = "".join(line.text for line in lines)

    assert "replace_in_file" in text
    assert "italic" in text and "_italic_" not in text


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


def test_entity_references_render_as_the_character_they_name():
    """A model writes ``&nbsp;`` for the character it means, not for its six letters."""
    lines = render_markdown("one&nbsp;two &amp; &copy;", 40, DARK)

    assert lines[0].text == "one\u00a0two & \u00a9"


def test_every_inline_path_decodes_its_entities():
    """A heading, a list item, and a quote run the same inline rules as prose."""
    document = "# A&nbsp;B\n\n- x&amp;y\n\n> q&nbsp;r"
    texts = [line.text for line in render_markdown(document, 30, DARK) if line.text]

    assert texts == ["A\u00a0B", "  \u00b7 x&y", "\u2502 q\u00a0r"]


def test_an_indent_spelled_with_entities_keeps_its_cells():
    """``&nbsp;&nbsp;`` is how a model indents a line, and the indent must measure.

    The escape decodes to one cell, not to the six it is written with, so the
    line starts two columns in and no column of it is lost.
    """
    lines = render_markdown("&nbsp;&nbsp;2.1 ①–⑬ 分阶段 µs 探针表", 40, DARK)

    assert lines[0].text == "\u00a0\u00a02.1 ①–⑬ 分阶段 µs 探针表"
    assert display_width(lines[0].text) == display_width("  2.1 ①–⑬ 分阶段 µs 探针表")


def test_a_table_column_is_measured_after_its_entities_decode():
    """Widths come from the visible cell, so a column of ``&nbsp;`` stays at the floor."""
    lines = render_markdown("| A | B |\n| --- | --- |\n| &nbsp; | &amp; |", 30, DARK)

    assert lines[1].text == "\u2500\u2500\u2500\u2500   \u2500\u2500\u2500\u2500"
    assert lines[2].text.startswith("\u00a0")


def test_numeric_references_decode_in_decimal_and_hexadecimal():
    spans = inline_markdown("&#8212; &#x2014; &#X2014;", theme=DARK)

    assert spans[0].text == "\u2014 \u2014 \u2014"


def test_a_reference_longer_than_the_spec_allows_is_not_one():
    """CommonMark reads at most seven decimal and six hexadecimal digits.

    Leading zeros are digits like any other, so a seven-digit reference is
    still a reference; an eighth digit makes it plain text instead.
    """
    spans = inline_markdown("&#12345678; &#x1234567; &#0008212;", theme=DARK)

    assert spans[0].text == "&#12345678; &#x1234567; \u2014"


def test_a_reference_can_name_a_character_beyond_the_basic_plane():
    """An astral code point decodes, and is measured as the two cells it paints."""
    line = render_markdown("&#x1F600;", 10, DARK)[0]

    assert line.text == "\U0001f600"
    assert display_width(line.text) == 2


def test_every_name_the_html5_table_holds_matches_the_pattern():
    """The name branch has to cover the whole table, or an entity is unreachable.

    The shape bounds the name at 31 characters, which is the longest name the
    HTML5 list holds; a name outside the pattern would be left as written by
    the lookup that never got to run. The two odd shapes are pinned beside it:
    a name ending in a digit, and one that is 31 characters long.
    """
    names = [name for name in html5 if name.endswith(";")]

    assert names and all(_ENTITY.fullmatch(f"&{name}") for name in names)
    assert max(len(name) for name in names) == 32  # 31 characters plus the semicolon
    assert decode_entities("&frac12;") == "\u00bd"
    assert decode_entities("&CounterClockwiseContourIntegral;") == "\u2233"


def test_a_name_can_expand_to_more_than_one_character():
    """Some HTML5 names are a base character with a combining mark."""
    span = inline_markdown("&NotEqualTilde;", theme=DARK)[0]

    assert span.text == "\u2242\u0338"
    assert span.width == 1


def test_a_pipe_spelled_as_an_entity_does_not_split_a_table_cell():
    """Cells are split on the pipes the row is written with, then decoded."""
    texts = [
        line.text for line in render_markdown("| A | B |\n| --- | --- |\n| a &#124; b | c |", 30, DARK) if line.text
    ]

    assert texts[2] == "a | b   c"


def test_a_reference_the_spec_does_not_recognise_is_left_as_written():
    """A missing semicolon, an unknown name, and a bare ampersand all stay text."""
    spans = inline_markdown("&nbsp &nope; & &; &#;", theme=DARK)

    assert spans[0].text == "&nbsp &nope; & &; &#;"


def test_an_escaped_escape_is_decoded_once():
    """``&amp;nbsp;`` names an ampersand: one pass, never a second one over the result."""
    spans = inline_markdown("&amp;nbsp; and &amp;amp;", theme=DARK)

    assert spans[0].text == "&nbsp; and &amp;"


def test_a_reference_to_no_character_becomes_the_replacement_glyph():
    spans = inline_markdown("&#0; &#xD800; &#x110000;", theme=DARK)

    assert spans[0].text == "\ufffd \ufffd \ufffd"


def test_code_keeps_its_entity_references_literal():
    """Code is shown as written: an escape inside it is part of the program."""
    lines = render_markdown("`&nbsp;` and\n\n```\n&nbsp;\n```", 40, DARK)
    text = "\n".join(line.text for line in lines)

    assert text.count("&nbsp;") == 2


def test_a_link_destination_decodes_its_entities():
    spans = inline_markdown("[docs](https://x.dev/?a=1&amp;b=2)", theme=DARK)

    assert spans[-1].text == " <https://x.dev/?a=1&b=2>"


def test_an_entity_the_canvas_cannot_paint_is_neutralised_there():
    """A control character spelled as an entity is decoded, then stopped like any other."""
    frame = Harness(MarkdownView("&#27;[31mred\n"), width=20, height=2).render()

    assert "\x1b" not in frame.text
    assert "\ufffd" in frame.text


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
