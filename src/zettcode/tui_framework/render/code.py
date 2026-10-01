"""Line-oriented syntax highlighting whose colours come from a theme.

The tokenizer is deliberately small: it covers the shapes a terminal reader
actually scans for (comments, strings, numbers, keywords, called names) and
merges everything else into plain code text. Nothing here picks a colour — a
:class:`CodeTheme` supplies every one, so a palette is data, not code.
"""

from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import dataclass

from .style import Span, Style

PYTHON = "python"
GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class CodeTheme:
    """Token colours for highlighted code.

    Attributes:
        name: Palette name, shown in theme listings.
        inline: Colour of inline code spans inside Markdown prose.
        text: Colour of code that belongs to no other token class.
        keyword: Colour of language keywords.
        string: Colour of quoted literals.
        comment: Colour of comments; also drawn italic.
        number: Colour of numeric literals.
        function: Colour of a name that is immediately called.
        builtin: Colour of builtin names and the ``True``/``False``/``None`` trio.
        operator: Colour of arithmetic and comparison operators.
        punctuator: Colour of brackets, commas, and other separators.
    """

    name: str = "default"
    inline: str = "#d8c07a"
    text: str = "#e6e9e7"
    keyword: str = "#e58fa8"
    string: str = "#9bddad"
    comment: str = "#6d7a70"
    number: str = "#d8b46a"
    function: str = "#7fb7d8"
    builtin: str = "#b8a6e0"
    operator: str = "#a3ada6"
    punctuator: str = "#a3ada6"

    def style_for(self, kind: str) -> Style:
        """Return the style for one token class."""
        return Style(foreground=getattr(self, kind, self.text), italic=kind == "comment")


DEFAULT_CODE_THEME = CodeTheme()

_PYTHON_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>[rbfuRBFU]{0,2}(?:'''[^\n]*|'''|\"\"\"[^\n]*|\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"))"
    r"|(?P<number>\b(?:0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<operator>[-+*/%=<>!&|^~]+)"
    r"|(?P<other>.)"
)

_GENERIC_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>//[^\n]*|#[^\n]*|--[^\n]*)"
    r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<other>.)"
)

_BUILTINS = frozenset(dir(builtins))
_LANGUAGES = {"py": PYTHON, "python": PYTHON, "python3": PYTHON}


def language_for(label: str) -> str:
    """Map a fence label to a tokenizer.

    Args:
        label: Text after the opening fence; case and surrounding space are
            ignored, and an unknown label falls back to ``GENERIC``.
    """
    return _LANGUAGES.get(label.strip().lower(), GENERIC)


def highlight(line: str, language: str = GENERIC, theme: CodeTheme = DEFAULT_CODE_THEME) -> list[Span]:
    """Return styled spans for one line of code.

    Args:
        line: Single source line, without its trailing newline.
        language: ``PYTHON`` or ``GENERIC``; any other value uses the generic
            tokenizer.
        theme: Palette the token colours are read from.
    """
    pattern = _PYTHON_TOKENS if language == PYTHON else _GENERIC_TOKENS
    matches = list(pattern.finditer(line))
    spans: list[Span] = []
    for index, match in enumerate(matches):
        kind = match.lastgroup or "other"
        text = match.group()
        if kind == "name":
            kind = _classify_name(text, matches, index, language)
        elif kind == "other":
            kind = "punctuator" if text.strip() else "text"
        spans.append(Span(text, theme.style_for(kind)))
    return _merge(spans)


def _classify_name(text: str, matches: list[re.Match[str]], index: int, language: str) -> str:
    """Decide whether an identifier is a keyword, a builtin, or a call target."""
    if language == PYTHON and keyword.iskeyword(text):
        return "keyword"
    if text in _BUILTINS or text in {"True", "False", "None"}:
        return "builtin"
    following = matches[index + 1].group() if index + 1 < len(matches) else ""
    return "function" if following.lstrip().startswith("(") else "text"


def _merge(spans: list[Span]) -> list[Span]:
    """Join adjacent runs that ended up with the same style."""
    merged: list[Span] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].style == span.style:
            merged[-1] = Span(merged[-1].text + span.text, span.style)
        else:
            merged.append(span)
    return merged
