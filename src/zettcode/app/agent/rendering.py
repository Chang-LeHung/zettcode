"""Agent output, on its way into the transcript: a chain of render handlers.

Every kind of output the agent produces — a tool call, the reasoning channel,
the answer — is shaped by the first handler that claims it, so presentation
rules live in one place and a new one is a new link rather than an ``if`` inside
the transcript.

For tools the chain also decides the words: output should read like a log, not
like a payload, so a call shows as ``Read src/app.py`` rather than
``read_file {"path": "src/app.py"}``. Each handler claims a family of tools —
reading, editing, deleting, running a command, searching, the plan — and the
last one claims whatever is left, which keeps an unknown tool at
``name key=value`` instead of a JSON blob. A handler may shape the result too:
:class:`ReadTool` drops the vendor's continuation hint and names the scanner for
the file, so the row's body is highlighted as the language it is.

Text handlers work on the streamed deltas, not on whole messages: a reasoning
channel arrives in fragments, and so does an answer. That is why
:meth:`RenderHandler.text` is told whether the fragment opens a message — the
only place a chat preamble such as ``Assistant:`` can appear.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...tui.render import GENERIC, language_for

#: Output kinds the chain shapes; a link claims one or more of them.
TOOL = "tool"
THINKING = "thinking"
ANSWER = "answer"

#: The hint a bounded read leaves behind; it is advice for the model, not the
#: reader, and the row already shows the text it applies to.
CONTINUATION = re.compile(r"\n?\.\.\. \[(?:line truncated|more lines)[^\]]*\]\s*\Z")

#: Wrapper tags a model may leave around its reasoning channel.
REASONING_TAGS = re.compile(r"</?(?:think(?:ing)?|reasoning)>|<\|(?:thinking|reasoning)\|>", re.IGNORECASE)

#: A chat preamble a locally hosted model sometimes repeats in front of an answer.
CHAT_PREAMBLE = re.compile(r"^\s*(?:assistant|ai)\s*[:\uff1a]\s*", re.IGNORECASE)

#: Escape sequences a model may echo from output it has read.
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


@dataclass(frozen=True, slots=True)
class ToolRow:
    """How one tool call appears as a transcript row.

    Attributes:
        title: The row's words, e.g. ``Read src/app.py``.
        language: Scanner for the row's output when it is source code, so a
            ``read_file`` body is highlighted; ``None`` draws it plain.
    """

    title: str
    language: str | None = None


class RenderHandler(ABC):
    """One link of the chain: how one kind of output is shaped before it shows.

    Attributes:
        kinds: Output kinds this link claims: ``"tool"``, ``"thinking"``, or
            ``"answer"``.
        names: Tool names, for a tool link that claims only one family; an empty
            set means the link claims every tool.
    """

    kinds: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()

    @abstractmethod
    def handles(self, kind: str, name: str = "") -> bool:
        """Return whether this link claims one piece of output."""

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Return the words of a tool row; only a tool link changes this."""
        return ToolRow(name)

    def body(self, name: str, output: str) -> str:
        """Return the text under a tool row; only a tool link changes this."""
        return output

    def text(self, text: str, *, opening: bool) -> str:
        """Return one streamed fragment, unchanged unless a link shapes it.

        A handler sees deltas, never a whole message, so its rule has to hold
        for a fragment. ``opening`` marks the fragment that starts a message,
        which is the only place something like a chat preamble can appear.
        """
        return text


class ToolHandler(RenderHandler):
    """Base for the tool links: each claims one family of tool names."""

    kinds = frozenset({TOOL})

    def handles(self, kind: str, name: str = "") -> bool:
        """Claim one tool, or every tool when the link names none."""
        return kind == TOOL and (not self.names or name in self.names)


class Renderers:
    """The chain: the first link that claims a piece of output shapes it.

    Args:
        handlers: Links in order, most specific first. The last link is expected
            to claim every tool; text no link claims is shown exactly as it
            arrived.
    """

    def __init__(self, handlers: Sequence[RenderHandler]) -> None:
        self.handlers = tuple(handlers)

    def _claim(self, kind: str, name: str = "") -> RenderHandler | None:
        """Return the first link that claims one piece of output."""
        return next((handler for handler in self.handlers if handler.handles(kind, name)), None)

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Return the row for one call, asking each link until one claims it."""
        handler = self._claim(TOOL, name)
        return ToolRow(name) if handler is None else handler.describe(name, arguments)

    def body(self, name: str, output: str) -> str:
        """Return the body for one call's result, through the claiming link."""
        handler = self._claim(TOOL, name)
        return output if handler is None else handler.body(name, output)

    def text(self, kind: str, text: str, *, opening: bool = False) -> str:
        """Return one streamed fragment of ``kind``, shaped by the claiming link."""
        handler = self._claim(kind)
        return text if handler is None else handler.text(text, opening=opening)


def argument(arguments: Mapping[str, object], key: str, default: str = "") -> str:
    """Return one argument as text, or ``default`` when it is missing or empty."""
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def summarise(arguments: Mapping[str, object], *, limit: int = 48) -> str:
    """Return ``key=value`` pairs for a tool no handler claims.

    The row is for a reader: no braces, no quotes around plain text, and a long
    value is cut rather than wrapped. A structured value becomes its size, which
    is the only part of it a row can say in words.
    """
    parts: list[str] = []
    for key, value in arguments.items():
        collapsed = " ".join(_value_text(value).split())
        parts.append(f"{key}={collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + '\u2026'}")
    return " ".join(parts)


def _value_text(value: object) -> str:
    """Return one argument as words, never as JSON syntax."""
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, Mapping):
        return f"{len(value)} fields"
    if isinstance(value, Sequence):
        return f"{len(value)} items"
    return str(value)


def language_for_path(path: str) -> str | None:
    """Return the scanner for a file's contents, or ``None`` when it is not code."""
    language = language_for(Path(path).suffix.lstrip("."))
    return None if language == GENERIC else language


class ReadTool(ToolHandler):
    """``read_file``: which file, and the scanner for its contents."""

    names = frozenset({"read_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file, and highlight the body as the language it is."""
        path = argument(arguments, "path", "(unknown file)")
        return ToolRow(f"Read {path}", language_for_path(path))

    def body(self, name: str, output: str) -> str:
        """Drop the continuation hint; the row bounds the text it applies to."""
        return CONTINUATION.sub("", output).rstrip()


class WriteTool(ToolHandler):
    """``write_file``: the file being written."""

    names = frozenset({"write_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file being written."""
        return ToolRow(f"Wrote {argument(arguments, 'path', '(unknown file)')}")


class EditTool(ToolHandler):
    """``replace_in_file``: the file and how many edits the call carries."""

    names = frozenset({"replace_in_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Count the edits so a multi-edit call is visible before it lands."""
        path = argument(arguments, "path", "(unknown file)")
        edits = arguments.get("edits")
        count = len(edits) if isinstance(edits, Sequence) and not isinstance(edits, str) else 0
        suffix = f" ({count} edit{'' if count == 1 else 's'})" if count else ""
        return ToolRow(f"Edited {path}{suffix}")


class DeleteTool(ToolHandler):
    """``delete_file``: the file being removed."""

    names = frozenset({"delete_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file being removed."""
        return ToolRow(f"Deleted {argument(arguments, 'path', '(unknown file)')}")


class ShellTool(ToolHandler):
    """``run_shell``: the command itself, which is the whole story."""

    names = frozenset({"run_shell"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the command, not a JSON copy of it."""
        return ToolRow(f"Ran {argument(arguments, 'command', '(unknown command)')}")


class SearchTool(ToolHandler):
    """``glob`` and ``grep``: what was looked for, and where."""

    names = frozenset({"glob", "grep"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Phrase a listing and a content search differently."""
        pattern = argument(arguments, "pattern")
        if name == "glob":
            return ToolRow(f"Listed {pattern}" if pattern else "Listed files")
        where = argument(arguments, "path")
        return ToolRow(f"Searched {pattern or 'the workspace'}" + (f" in {where}" if where else ""))


class TodoTool(ToolHandler):
    """``todo_write``: a plan, so the number of steps is the story."""

    names = frozenset({"todo_write"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Say how much of the plan the call carries."""
        todos = arguments.get("todos")
        count = len(todos) if isinstance(todos, Sequence) and not isinstance(todos, str) else 0
        if not count:
            return ToolRow("Updated the plan")
        return ToolRow(f"Updated {count} todo{'' if count == 1 else 's'}")


class FallbackTool(ToolHandler):
    """Anything no other link claims: its name and flat arguments, never JSON."""

    def handles(self, kind: str, name: str = "") -> bool:
        """Claim every call the earlier links passed over."""
        return kind == TOOL

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show ``name key=value`` so an unknown tool still reads as a sentence."""
        return ToolRow(f"{name} {summarise(arguments)}".rstrip())


class ReasoningHandler(RenderHandler):
    """``thinking``: the reasoning channel, without the wrappers providers add.

    A model may open and close its reasoning with tags of its own, or echo an
    escape sequence it read in a tool result; neither belongs in the transcript,
    and both are removed per fragment so a half-streamed tag never shows.
    """

    kinds = frozenset({THINKING})

    def handles(self, kind: str, name: str = "") -> bool:
        """Claim the reasoning channel."""
        return kind == THINKING

    def text(self, text: str, *, opening: bool) -> str:
        """Strip provider tags and escapes from one reasoning fragment."""
        return ANSI.sub("", REASONING_TAGS.sub("", text))


class AnswerHandler(RenderHandler):
    """``answer``: the assistant's own text, without a chat preamble.

    A locally hosted model sometimes repeats ``Assistant:`` before answering;
    the transcript is already the assistant, so it is dropped — but only in the
    fragment that opens the message, because that is the only place a preamble
    can be, and a later fragment may legitimately start with the same word.
    """

    kinds = frozenset({ANSWER})

    def handles(self, kind: str, name: str = "") -> bool:
        """Claim the answer channel."""
        return kind == ANSWER

    def text(self, text: str, *, opening: bool) -> str:
        """Strip escapes always, and a chat preamble when the message opens."""
        cleaned = ANSI.sub("", text)
        return CHAT_PREAMBLE.sub("", cleaned, count=1) if opening else cleaned


#: The chain the application renders with, most specific handler first.
DEFAULT_RENDERERS = Renderers(
    (
        ReadTool(),
        WriteTool(),
        EditTool(),
        DeleteTool(),
        ShellTool(),
        SearchTool(),
        TodoTool(),
        FallbackTool(),
        ReasoningHandler(),
        AnswerHandler(),
    )
)
