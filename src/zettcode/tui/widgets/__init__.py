"""Reusable widgets built on the core runtime and the layout containers."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Collapsible": ".collapsible",
    "Column": ".table",
    "Completer": ".completion",
    "CompletionItem": ".completion",
    "CompletionPopup": ".completion",
    "Dialog": ".dialog",
    "DialogAction": ".dialog",
    "DiffLine": ".diff",
    "DiffSegment": ".diff",
    "DiffView": ".diff",
    "ListItem": ".list",
    "ListPage": ".list_page",
    "ListView": ".list",
    "Markdown": ".markdown",
    "MarkdownSource": ".markdown",
    "MarkdownView": ".markdown",
    "ProgressBar": ".progress",
    "RichText": ".rich_text",
    "Rule": ".text",
    "Spinner": ".progress",
    "StatusBar": ".status",
    "Table": ".table",
    "TaskPanel": ".tasks",
    "Text": ".text",
    "TextArea": ".textarea",
    "Toast": ".toast",
    "build_unified": ".diff",
    "layout_input": ".textarea",
    "next_word": ".textarea",
    "parse_unified": ".diff",
    "previous_word": ".textarea",
    "render_markdown": ".markdown",
    "word_diff": ".diff",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .collapsible import Collapsible
    from .completion import Completer, CompletionItem, CompletionPopup
    from .dialog import Dialog, DialogAction
    from .diff import DiffLine, DiffSegment, DiffView, build_unified, parse_unified, word_diff
    from .list import ListItem, ListView
    from .list_page import ListPage
    from .markdown import Markdown, MarkdownSource, MarkdownView, render_markdown
    from .progress import ProgressBar, Spinner
    from .rich_text import RichText
    from .status import StatusBar
    from .table import Column, Table
    from .tasks import TaskPanel
    from .text import Rule, Text
    from .textarea import TextArea, layout_input, next_word, previous_word
    from .toast import Toast


def __getattr__(name: str) -> object:
    """Import the module a public name lives in, the first time it is asked for.

    This package is a facade over several subpackages, and a caller that wants
    one name should not pay for the rest of them — the TUI alone holds the
    widget library, the Markdown parser, the diff viewer, and the syntax
    scanners. ``__all__`` is still the public surface.
    """
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    """Return the names this package publishes."""
    return sorted(__all__)


__all__ = [
    "Collapsible",
    "Column",
    "Completer",
    "CompletionItem",
    "CompletionPopup",
    "Dialog",
    "DialogAction",
    "DiffLine",
    "DiffSegment",
    "DiffView",
    "ListItem",
    "ListView",
    "ListPage",
    "Markdown",
    "MarkdownSource",
    "MarkdownView",
    "ProgressBar",
    "RichText",
    "Rule",
    "Spinner",
    "StatusBar",
    "Table",
    "TaskPanel",
    "Text",
    "TextArea",
    "Toast",
    "build_unified",
    "layout_input",
    "next_word",
    "parse_unified",
    "previous_word",
    "render_markdown",
    "word_diff",
]
