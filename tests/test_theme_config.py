"""Tests for syntax highlighting and the configurable code palette."""

from dataclasses import replace

import pytest

from zettcode.tui import DARK, EXAMPLE, LIGHT, ThemeFileError, load_theme, theme_from_toml
from zettcode.tui.render import highlight, language_for, languages
from zettcode.tui.widgets.markdown import render_markdown


def color_of(spans, needle: str) -> str | None:
    """Return the colour of the run containing needle.

    Adjacent runs that share a style are merged, so a token is looked up by
    containment rather than by exact span text.
    """
    for span in spans:
        if needle in span.text:
            return span.style.foreground
    raise AssertionError(f"{needle!r} missing from {[span.text for span in spans]}")


def test_every_language_resolves_from_its_own_name_and_common_aliases():
    for name in languages():
        assert language_for(name) == name

    assert language_for("  PY  ") == "python"
    assert language_for("yml") == "yaml"
    assert language_for("c++") == "cpp"
    assert language_for("tex") == "latex"
    assert language_for("no-such-language") == "generic"
    # The names a fence is most likely to carry are all covered.
    common = {
        "python",
        "javascript",
        "typescript",
        "rust",
        "go",
        "java",
        "c",
        "cpp",
        "csharp",
        "ruby",
        "php",
        "sql",
        "json",
        "yaml",
        "toml",
        "html",
        "css",
        "latex",
        "shell",
    }
    assert common <= set(languages())


def test_highlight_classifies_python_tokens():
    spans = highlight("def parse(path: str) -> int:  # note", "python", DARK.code)

    assert color_of(spans, "def") == DARK.code.keyword
    assert color_of(spans, "parse") == DARK.code.function
    assert color_of(spans, "str") == DARK.code.builtin
    assert color_of(spans, "# note") == DARK.code.comment
    comment = next(span for span in spans if span.text == "# note")
    assert comment.style.italic is True


def test_highlight_marks_numbers_strings_and_builtins():
    spans = highlight('count = values[3] + len("ab")', "python", DARK.code)

    assert color_of(spans, "3") == DARK.code.number
    assert color_of(spans, '"ab"') == DARK.code.string
    assert color_of(spans, "len") == DARK.code.builtin
    assert color_of(spans, "values") == DARK.code.text


def test_highlight_falls_back_to_a_generic_tokenizer():
    # A label no scanner knows still colours the shapes every language shares.
    spans = highlight("const total = 3; // note", "cobol", DARK.code)

    assert color_of(spans, "3") == DARK.code.number
    assert color_of(spans, "// note") == DARK.code.comment
    assert color_of(spans, "const") == DARK.code.text


def test_highlight_reads_shell_commands_flags_and_strings():
    spans = highlight('cd /tmp && rm -f -- "a b.txt" 2>/dev/null', "bash", DARK.code)

    assert color_of(spans, "cd") == DARK.code.function
    assert color_of(spans, "rm") == DARK.code.function
    assert color_of(spans, "&&") == DARK.code.operator
    assert color_of(spans, '"a b.txt"') == DARK.code.string
    # ``--`` is a flag in a shell command, not the comment a generic tokenizer
    # would see, so the strings after it must stay strings; a redirection does
    # not turn its target into a command name either.
    assert color_of(spans, "dev/null") == DARK.code.text


def test_highlight_leaves_shell_variables_and_arguments_plain():
    spans = highlight('echo "$HOME" > $OUT', "sh", DARK.code)

    assert color_of(spans, "$HOME") == DARK.code.string
    assert color_of(spans, "$OUT") == DARK.code.builtin
    assert color_of(spans, "echo") == DARK.code.function


def test_highlight_reads_the_brace_languages():
    javascript = highlight("const total = 3; // note", "js", DARK.code)
    assert color_of(javascript, "const") == DARK.code.keyword
    assert color_of(javascript, "3") == DARK.code.number
    assert color_of(javascript, "// note") == DARK.code.comment

    rust = highlight("fn main() { let x = 1; }", "rs", DARK.code)
    assert color_of(rust, "fn") == DARK.code.keyword
    assert color_of(rust, "let") == DARK.code.keyword
    # A name that is called is a function, whatever the language calls it.
    assert color_of(rust, "main") == DARK.code.function

    go = highlight('func main() { fmt.Println("hi") }', "go", DARK.code)
    assert color_of(go, "func") == DARK.code.keyword
    assert color_of(go, '"hi"') == DARK.code.string


def test_highlight_matches_sql_keywords_case_insensitively():
    spans = highlight("SELECT id FROM users WHERE id = 1 -- note", "sql", DARK.code)

    assert color_of(spans, "SELECT") == DARK.code.keyword
    assert color_of(spans, "FROM") == DARK.code.keyword
    assert color_of(spans, "-- note") == DARK.code.comment
    assert color_of(spans, "users") == DARK.code.text


def test_highlight_reads_config_formats_and_markup():
    json_spans = highlight('{"name": "zett", "ok": true}', "json", DARK.code)
    assert color_of(json_spans, '"zett"') == DARK.code.string
    assert color_of(json_spans, "true") == DARK.code.keyword

    yaml_spans = highlight("key: value # note", "yml", DARK.code)
    assert color_of(yaml_spans, "# note") == DARK.code.comment

    html_spans = highlight('<div class="row">hi</div>', "html", DARK.code)
    assert color_of(html_spans, "div") == DARK.code.keyword
    assert color_of(html_spans, '"row"') == DARK.code.string


def test_highlight_reads_latex_commands_math_and_comments():
    spans = highlight(r"\frac{1}{2} = $x^2$ % note", "tex", DARK.code)

    assert color_of(spans, r"\frac") == DARK.code.function
    assert color_of(spans, "$x^2$") == DARK.code.string
    assert color_of(spans, "% note") == DARK.code.comment


def test_code_and_inline_code_never_paint_a_background():
    block = render_markdown("```python\nvalue = 1\n```\n\nrun `values[0]` now", 40, DARK)
    spans = [span for line in block for span in line.spans]

    assert spans
    assert all(span.style.background is None for span in spans)
    assert color_of(spans, "values[0]") == DARK.code.inline


def test_a_custom_palette_changes_the_rendered_colours():
    custom = replace(DARK, code=replace(DARK.code, keyword="#ff0000"))
    source = "```python\ndef f():\n    return 1\n```"

    default = [span for line in render_markdown(source, 40, DARK) for span in line.spans]
    themed = [span for line in render_markdown(source, 40, custom) for span in line.spans]

    assert color_of(default, "def") == DARK.code.keyword
    assert color_of(themed, "def") == "#ff0000"
    assert color_of(themed, "return") == "#ff0000"


def test_theme_file_overrides_ui_and_code_colours():
    text = 'base = "light"\n\n[ui]\naccent = "#123456"\n\n[code]\nkeyword = "#abcdef"\n'

    theme = theme_from_toml(text)

    assert theme.name == "light"
    assert theme.accent == "#123456"
    assert theme.code.keyword == "#abcdef"
    assert theme.code.string == LIGHT.code.string


def test_theme_file_rejects_unknown_keys_and_bad_values():
    with pytest.raises(ThemeFileError, match="Unknown theme key"):
        theme_from_toml('[ui]\nnope = "#000000"\n')
    with pytest.raises(ThemeFileError, match="#rrggbb"):
        theme_from_toml('[code]\nkeyword = "red"\n')
    with pytest.raises(ThemeFileError, match="Invalid theme file"):
        theme_from_toml("this is not toml")
    with pytest.raises(ThemeFileError, match="Unknown theme"):
        theme_from_toml('base = "neon"\n')
    with pytest.raises(ThemeFileError, match="must be tables"):
        theme_from_toml('ui = "dark"\n')


def test_load_theme_reads_the_documented_example(tmp_path):
    path = tmp_path / "theme.toml"
    path.write_text(EXAMPLE, encoding="utf-8")

    theme = load_theme(path)

    assert theme.code.keyword == "#e58fa8"
    assert theme.accent == "#a7c080"


def test_load_theme_reports_a_missing_file(tmp_path):
    with pytest.raises(ThemeFileError, match="Cannot read"):
        load_theme(tmp_path / "missing.toml")
