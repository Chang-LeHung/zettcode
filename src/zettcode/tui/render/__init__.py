"""Rendering primitives: styled text, capabilities-aware color, and canvases."""

from .canvas import Canvas
from .code import DEFAULT_CODE_THEME, GENERIC, LATEX, PYTHON, SHELL, CodeTheme, highlight, language_for, languages
from .color import ColorDepth, encode_style, parse_hex, rgb_to_ansi16, rgb_to_ansi256
from .renderer import DifferentialRenderer
from .style import DEFAULT_STYLE, Cell, Span, Style, TextLine
from .text import (
    ELLIPSIS,
    cell_glyph,
    character_width,
    display_width,
    expand_span_tabs,
    expand_tabs,
    slice_columns,
    truncate,
    wrap_columns,
    wrap_spans,
)

__all__ = [
    "DEFAULT_CODE_THEME",
    "DEFAULT_STYLE",
    "ELLIPSIS",
    "GENERIC",
    "LATEX",
    "PYTHON",
    "SHELL",
    "Canvas",
    "Cell",
    "ColorDepth",
    "CodeTheme",
    "DifferentialRenderer",
    "Span",
    "Style",
    "TextLine",
    "cell_glyph",
    "character_width",
    "display_width",
    "encode_style",
    "expand_span_tabs",
    "expand_tabs",
    "highlight",
    "language_for",
    "languages",
    "parse_hex",
    "rgb_to_ansi16",
    "rgb_to_ansi256",
    "slice_columns",
    "truncate",
    "wrap_columns",
    "wrap_spans",
]
