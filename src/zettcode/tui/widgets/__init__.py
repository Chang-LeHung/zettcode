"""Reusable widgets built on the core runtime and the layout containers."""

from .collapsible import Collapsible
from .completion import Completer, CompletionItem, CompletionPopup
from .dialog import Dialog, DialogAction
from .diff import DiffLine, DiffSegment, DiffView, build_unified, parse_unified, word_diff
from .list import ListItem, ListView
from .list_page import ListPage
from .markdown import Markdown, MarkdownSource, MarkdownView, render_markdown
from .page import Page
from .progress import ProgressBar, Spinner
from .status import StatusBar
from .table import Column, Table
from .tasks import TaskPanel
from .text import Rule, Text
from .textarea import TextArea, layout_input, next_word, previous_word
from .toast import Toast

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
    "Page",
    "ProgressBar",
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
