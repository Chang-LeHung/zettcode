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

import difflib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from zettcode.tui import ELLIPSIS, SEPARATOR
from zettcode.tui.render import GENERIC, language_for

from .entries import DeleteEntry, EditEntry, EntryStatus, MessageEntry, ReadEntry, ToolEntry, WriteEntry
from .text import DECLINED_NOTE, limit_output

#: Output kinds the chain shapes; a link claims one or more of them.
TOOL = "tool"
THINKING = "thinking"
ANSWER = "answer"

#: Suffixes that look like a picture, copied from the read tool's accepted set: a row is opened from the arguments,
#: before the result exists, so the suffix is all it has. The durable answer is a boolean on the finished event, taken
#: from the result's own content — see :func:`is_picture_path`.
PICTURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


def is_picture_path(path: str) -> bool:
    """Return whether ``path`` looks like a picture by its suffix.

    A guess, and named like one: the read tool decides by the file's signature, so a PNG copied to ``.bin`` is counted
    as text and a text file named ``notes.png`` is not counted. Both are a line about a row nobody is reading closely;
    the exact answer needs the boolean the result will carry (see :data:`PICTURE_SUFFIXES`).
    """
    return Path(path).suffix.lower() in PICTURE_SUFFIXES


#: The hint a bounded read leaves behind; it is advice for the model, not the
#: reader, and the row already shows the text it applies to.
CONTINUATION = re.compile(r"\n?\.\.\. \[(?:line truncated|output truncated|more lines)[^\]]*\]\s*\Z")

#: Wrapper tags a model may leave around its reasoning channel.
REASONING_TAGS = re.compile(r"</?(?:think(?:ing)?|reasoning)>|<\|(?:thinking|reasoning)\|>", re.IGNORECASE)

#: A chat preamble a locally hosted model sometimes repeats in front of an answer.
CHAT_PREAMBLE = re.compile(r"^\s*(?:assistant|ai)\s*[:\uff1a]\s*", re.IGNORECASE)

#: Escape sequences a model may echo from output it has read.
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


#: One row of an edit's diff: ``("+", text)`` an addition, ``("-", text)`` a deletion, ``(" ", text)`` a line
#: kept for context, ``("@", label)`` the break between one edit and the next.
DiffRow = tuple[str, str]

#: Rows kept of one edit call's diff. The arguments are what the model sent and can be a whole file; the
#: row shows a handful and expands to a screenful, so what is stored only has to be more than that.
MAX_DIFF_ROWS = 400

#: Unchanged lines kept on each side of a change, so an edit reads in place without repeating the file.
DIFF_CONTEXT = 1


@dataclass(frozen=True, slots=True)
class ToolRow:
    """How one tool call appears as a transcript row.

    Attributes:
        title: The row's words, e.g. ``Read src/app.py``.
        language: Scanner for the row's output when it is source code, so a
            ``read_file`` body is highlighted; ``None`` draws it plain.

    This is only the words. What else a tool's row carries — the lines an edit changes, the change
    itself — belongs to that tool's entry, which its handler builds in :meth:`RenderHandler.open_tool`.
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

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """Return the entry for one call as it starts: the class that carries what this tool shows.

        The default is a plain :class:`ToolEntry` with the words :meth:`describe` gives it. A tool
        whose row shows more has its own entry class and builds it here, so the transcript, which
        opens every row the same way, never has to know which tool it is.

        Args:
            name: The tool's name.
            arguments: What the model called it with.
            id: The row's identity in the transcript.
            call_id: Identifier the matching result will carry.
            started_at: Clock reading the row opens on.
        """
        row = self.describe(name, arguments)
        return ToolEntry(id=id, call_id=call_id, tool=name, title=row.title, started_at=started_at)

    def body(self, name: str, output: str) -> str:
        """Return the text under a tool row; only a tool link changes this."""
        return output

    def finished(self, entry: ToolEntry, text: str, status: EntryStatus) -> None:
        """Adjust a row now that its result is in — a count, a size — and change nothing by default.

        Args:
            entry: The row, whose body is already set and bounded.
            text: The body as it came back, after :meth:`body` shaped it and before it was bounded.
            status: Whether the call completed, failed or was skipped: a row may only count what worked.
        """
        return None

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

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """Return the entry for one call, of the class its claiming link builds."""
        handler = self._claim(TOOL, name)
        if handler is None:
            return ToolEntry(id=id, call_id=call_id, tool=name, title=name, started_at=started_at)
        return handler.open_tool(name, arguments, id=id, call_id=call_id, started_at=started_at)

    def body(self, name: str, output: str) -> str:
        """Return the body for one call's result, through the claiming link."""
        handler = self._claim(TOOL, name)
        return output if handler is None else handler.body(name, output)

    def finished(self, entry: ToolEntry, text: str, status: EntryStatus) -> None:
        """Let the claiming link adjust a row once its result is in."""
        handler = self._claim(TOOL, entry.tool)
        if handler is not None:
            handler.finished(entry, text, status)

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


def edit_changes(arguments: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """Return the text pairs an ``edit`` call replaces: one pair now, a list of them from an older transcript.

    A call carries ``old_string`` and ``new_string``. A session stored before that shape gave the arguments an
    ``edits`` list, and it is read the same way so the row of an old transcript still shows its diff. Anything
    that is not two strings is dropped rather than guessed at.
    """
    legacy = arguments.get("edits")
    if isinstance(legacy, Sequence) and not isinstance(legacy, str):
        return tuple(
            (edit["old_text"], edit["new_text"])
            for edit in legacy
            if isinstance(edit, Mapping)
            and isinstance(edit.get("old_text"), str)
            and isinstance(edit.get("new_text"), str)
        )
    old_string, new_string = arguments.get("old_string"), arguments.get("new_string")
    if isinstance(old_string, str) and isinstance(new_string, str):
        return ((old_string, new_string),)
    return ()


def edited_lines(changes: Sequence[tuple[str, str]]) -> tuple[int, int]:
    """Return the lines an ``edit`` call adds and removes.

    The tool answers ``Replaced 1 occurrence in app.py``, which says that a change landed but not how large it was:
    a two-line fix and a two-hundred-line rewrite read the same. The call carries both texts, so the difference is
    counted here — with :class:`difflib.SequenceMatcher` rather than by subtracting lengths, because a replacement
    that keeps the lines around it should not read as a rewrite, and that is what a reader comparing two rows is
    looking at.

    Args:
        changes: The old and new text of each change, as :func:`edit_changes` reads them.

    Returns:
        ``(added, removed)`` across every change; ``(0, 0)`` when the call carried nothing countable.

    A change that replaces every occurrence counts once, not once per occurrence: how many the file holds is
    something only the file knows, and the tool's own answer is where that number appears.
    """
    added = removed = 0
    for old_text, new_text in changes:
        matcher = difflib.SequenceMatcher(None, old_text.splitlines(), new_text.splitlines())
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag in ("replace", "delete"):
                removed += old_end - old_start
            if tag in ("replace", "insert"):
                added += new_end - new_start
    return (added, removed)


def edit_diff(changes: Sequence[tuple[str, str]], *, limit: int = MAX_DIFF_ROWS) -> tuple[DiffRow, ...]:
    """Return the rows of the change an ``edit`` call makes.

    Each change carries the text it replaces and the text it puts there, so the change can be shown
    without reading the file: the lines that differ, and one unchanged line around each so it reads in
    place. Changes are told apart by a labelled break when there is more than one — which only an older
    transcript has — and what is kept is cut at ``limit`` rows with a last row saying so, because the
    arguments can be a whole file.

    Args:
        changes: The old and new text of each change, as :func:`edit_changes` reads them.
        limit: Most rows to keep.
    """
    rows: list[DiffRow] = []
    for number, (old_text, new_text) in enumerate(changes, start=1):
        if len(changes) > 1:
            rows.append(("@", f"edit {number} of {len(changes)}"))
        old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
        opcodes = difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes()
        for index, (tag, old_start, old_end, new_start, new_end) in enumerate(opcodes):
            if tag == "equal":
                kept = old_lines[old_start:old_end]
                first, last = index == 0, index == len(opcodes) - 1
                if len(kept) > DIFF_CONTEXT * (2 - first - last):
                    head = [] if first else kept[:DIFF_CONTEXT]
                    tail = [] if last else kept[-DIFF_CONTEXT:]
                    rows.extend((" ", line) for line in head)
                    if not first and not last:
                        rows.append(("@", ELLIPSIS))
                    rows.extend((" ", line) for line in tail)
                else:
                    rows.extend((" ", line) for line in kept)
                continue
            rows.extend(("-", line) for line in old_lines[old_start:old_end])
            rows.extend(("+", line) for line in new_lines[new_start:new_end])
    return _capped(rows, limit)


def _capped(rows: list[DiffRow], limit: int) -> tuple[DiffRow, ...]:
    """Keep ``limit`` rows, and say how many were not kept."""
    if len(rows) > limit:
        rows = [*rows[:limit], ("@", f"{ELLIPSIS} {len(rows) - limit} more rows not kept")]
    return tuple(rows)


def write_diff(content: object, *, limit: int = MAX_DIFF_ROWS) -> tuple[DiffRow, ...]:
    """Return the rows of the change a ``write_file`` call makes: every line of the file, added.

    A write replaces the file, and what it replaced is not in the call, so nothing can be shown as
    removed and nothing as unchanged; the new content is the change. A file past ``limit`` lines is
    cut there with a last row saying so, and an empty or unreadable ``content`` is no change to show.

    Args:
        content: The call's ``content`` argument as the model sent it.
        limit: Most rows to keep.
    """
    if not isinstance(content, str):
        return ()
    return _write_rows(content.splitlines(), limit)


def _write_rows(lines: list[str], limit: int) -> tuple[DiffRow, ...]:
    """The kept lines as additions, without building a row for every line of a file that is too long."""
    rows: list[DiffRow] = [("+", line) for line in lines[:limit]]
    if len(lines) > limit:
        rows.append(("@", f"{ELLIPSIS} {len(lines) - limit} more rows not kept"))
    return tuple(rows)


def written_lines(content: object) -> int:
    """Return how many lines a ``write_file`` call writes: what the file will hold, not what it held.

    The tool overwrites, and what it overwrote is not in the call, so this is the size of the new
    file — which is the number a reader asks of a row that says it created one.
    """
    return len(content.splitlines()) if isinstance(content, str) else 0


def summarise(arguments: Mapping[str, object], *, limit: int = 48) -> str:
    """Return ``key=value`` pairs for a tool no handler claims.

    The row is for a reader: no braces, no quotes around plain text, and a long
    value is cut rather than wrapped. A structured value becomes its size, which
    is the only part of it a row can say in words.
    """
    parts: list[str] = []
    for key, value in arguments.items():
        collapsed = " ".join(_value_text(value).split())
        parts.append(f"{key}={collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + ELLIPSIS}")
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


def file_path(arguments: Mapping[str, object], default: str = "") -> str:
    """Return the path a file tool was called for.

    ``file_path`` is the argument now; a session stored before the rename carries ``path``, and is still shown the
    file it changed rather than as an unknown one.
    """
    return argument(arguments, "file_path") or argument(arguments, "path") or default


def language_for_path(path: str) -> str | None:
    """Return the scanner for a file's contents, or ``None`` when it is not code."""
    language = language_for(Path(path).suffix.lstrip("."))
    return None if language == GENERIC else language


class ReadTool(ToolHandler):
    """``read_file`` and ``read``: which file, and the scanner for its contents."""

    names = frozenset({"read_file", "read"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file, and highlight the body as the language it is."""
        path = file_path(arguments, "(unknown file)")
        return ToolRow(f"Read {path}", language_for_path(path))

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """A read row, which knows the language its body is in, and whether the file is a picture."""
        row = self.describe(name, arguments)
        path = file_path(arguments)
        return ReadEntry(
            id=id,
            call_id=call_id,
            tool=name,
            title=row.title,
            language=row.language,
            picture=is_picture_path(path),
            started_at=started_at,
        )

    def body(self, name: str, output: str) -> str:
        """Drop the continuation hint; the row bounds the text it applies to."""
        return CONTINUATION.sub("", output).rstrip()

    def finished(self, entry: ToolEntry, text: str, status: EntryStatus) -> None:
        """Count what the read returned, on the row, if it returned text and the call worked.

        The count is of what came back — a range asked for is not the same number — and of the whole of it, not of
        the preview the row keeps, so a read past the output limit is counted in full. A picture carries no lines,
        and a failed call's body is the error message rather than the file, so neither is counted.
        """
        if status is not EntryStatus.COMPLETED or not isinstance(entry, ReadEntry) or entry.picture:
            return
        entry.lines = len(text.splitlines())


class WriteTool(ToolHandler):
    """``write_file``: the file being written."""

    names = frozenset({"write_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file being written: the row is the call, so it says what the call does, not what it did."""
        return ToolRow(f"Write {file_path(arguments, '(unknown file)')}")

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """A write row, which says how many lines the file will hold and shows them as additions."""
        content = arguments.get("content")
        return WriteEntry(
            id=id,
            call_id=call_id,
            tool=name,
            title=self.describe(name, arguments).title,
            path=file_path(arguments),
            added=written_lines(content),
            diff=write_diff(content),
            started_at=started_at,
        )


class EditTool(ToolHandler):
    """``edit``: the file, and the size of the one change the call makes.

    A session stored before the tool was renamed calls it ``replace_in_file``, and is still shown the same way; one
    stored before a call carried a single change gave it a list under ``edits``, and that list is read too.
    """

    names = frozenset({"edit", "replace_in_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file; the size of the change is drawn beside the title, before it lands.

        `+12 -3` beside the file says whether this is a tweak or a rewrite, which is the question a reader asks
        the row. One change a call is why the title counts nothing: a count of one is noise on every row.
        """
        return ToolRow(f"Edit {file_path(arguments, '(unknown file)')}")

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """An edit row, which carries the lines it changes and the change itself.

        The counts ride outside the title: they are drawn in the colours an addition and a
        deletion get, which a title made of one string cannot be.
        """
        changes = edit_changes(arguments)
        added, removed = edited_lines(changes)
        return EditEntry(
            id=id,
            call_id=call_id,
            tool=name,
            title=self.describe(name, arguments).title,
            path=file_path(arguments),
            added=added,
            removed=removed,
            diff=edit_diff(changes),
            started_at=started_at,
        )


class DeleteTool(ToolHandler):
    """``delete_file``: the file being removed."""

    names = frozenset({"delete_file"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the file being removed."""
        return ToolRow(f"Deleted {file_path(arguments, '(unknown file)')}")

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """A delete row, which knows which file went."""
        return DeleteEntry(
            id=id,
            call_id=call_id,
            tool=name,
            title=self.describe(name, arguments).title,
            path=file_path(arguments),
            started_at=started_at,
        )


class ShellTool(ToolHandler):
    """``bash``: the command itself, which is the whole story."""

    names = frozenset({"bash"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the command, not a JSON copy of it."""
        return ToolRow(f"Bash {argument(arguments, 'command', '(unknown command)')}")


class SearchTool(ToolHandler):
    """``glob`` and ``grep``: what was looked for, and where."""

    names = frozenset({"glob", "grep"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Phrase a listing and a content search differently."""
        pattern = argument(arguments, "pattern")
        if name == "glob":
            return ToolRow(f"Listed {pattern}" if pattern else "Listed files")
        where = argument(arguments, "file_pattern") or argument(arguments, "path")
        return ToolRow(f"Searched {pattern or 'the workspace'}" + (f" in {where}" if where else ""))


class WebSearchTool(ToolHandler):
    """``web_search``: a search the endpoint ran, so the row says what was searched for."""

    names = frozenset({"web_search"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Name the query; the call is the endpoint's, so nothing else of it is ours to show."""
        query = argument(arguments, "query")
        return ToolRow(f'Searched the web for "{query}"' if query else "Searched the web")


class AskUserTool(ToolHandler):
    """``ask_user``: the one row that waited for a person, so it is named as a thing, not as a verb.

    The body is what the person did, not the protocol: the tool answers with the payload the shell sent, and that
    JSON is neither readable nor useful in a transcript.
    """

    names = frozenset({"ask_user"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show the question that was put, under the name the shell gives that tool."""
        question = argument(arguments, "question")
        return ToolRow(f"Ask-User: {question}" if question else "Ask-User")

    def body(self, name: str, output: str) -> str:
        """Say what the person did: declined, answered, or answered with a picture.

        Anything that is not the answer payload is left exactly as it came, so a failure or another tool's result
        is never rewritten by this row.
        """
        payload = _ask_payload(output)
        if payload is None:
            return output
        if payload.get("declined") is True:
            return DECLINED_NOTE
        answer = payload.get("answer")
        if isinstance(answer, str) and answer.strip():
            return f"You answered: {answer.strip()}"
        if isinstance(payload.get("parts"), list) and payload["parts"]:
            return "You answered with a picture."
        return output


def _ask_payload(output: str) -> Mapping[str, object] | None:
    """Return the payload of an ``ask_user`` result, or ``None`` when the text is not one."""
    try:
        result = json.loads(output)
    except ValueError:
        return None
    payload = result.get("payload") if isinstance(result, Mapping) else None
    return payload if isinstance(payload, Mapping) else None


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


class SkillTool(ToolHandler):
    """``read_skill``: the skill whose instructions the call loads."""

    names = frozenset({"read_skill"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show which skill is being read, as the catalog named it."""
        return ToolRow(f"Read skill {argument(arguments, 'name', '(unknown skill)')}")


class TaskTool(ToolHandler):
    """``task``: work handed to a subagent, named by the profile that runs it."""

    names = frozenset({"task"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Say which subagent was chosen, and what it was asked to do."""
        profile = argument(arguments, "subagent_type", "(unknown)")
        summary = argument(arguments, "description")
        title = f"Subagent {profile}"
        return ToolRow(f"{title} {SEPARATOR} {summary}" if summary else title)

    def body(self, name: str, output: str) -> str:
        """Show the child's report, not the envelope that carried it back."""
        try:
            payload = json.loads(output)
        except (TypeError, ValueError):
            return output
        if isinstance(payload, Mapping) and isinstance(payload.get("content"), str):
            return payload["content"]
        return output


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class MessageTool(ToolHandler):
    """``send_message``: a message to another session, kept whole so the row can show it."""

    names = frozenset({"send_message"})

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Say who it is for; an id is shortened to its end, which is how a session is named without a title."""
        return ToolRow(f"Message to {self._recipient(argument(arguments, 'to', '(unknown)'))}")

    @staticmethod
    def _recipient(to: str) -> str:
        """Return the recipient as a reader can use it: a name as it is, an id by its last characters."""
        return f"session {to[-6:]}" if _UUID.fullmatch(to) else to

    def open_tool(
        self, name: str, arguments: Mapping[str, object], *, id: int, call_id: str, started_at: float
    ) -> ToolEntry:
        """A message row, which holds the text that was sent."""
        message = arguments.get("message")
        return MessageEntry(
            id=id,
            call_id=call_id,
            tool=name,
            title=self.describe(name, arguments).title,
            to=argument(arguments, "to"),
            message=limit_output(message) if isinstance(message, str) else "",
            started_at=started_at,
        )


class NamespacedTool(ToolHandler):
    """A tool whose name carries where it came from: ``server__tool``, so the row names the server.

    The server is part of what the call was: the same ``search`` in two servers is two different tools, with
    different reach and different answers, and a row that drops the server makes them look like one.

    The name is all a renderer knows, so the row says what the name says — ``github/create_issue`` — and not that
    the tool speaks MCP: a plugin registers a namespaced name of its own with the same shape, and the runtime does
    not mark its remote tools here. A name without both parts is shown as it arrived.
    """

    def handles(self, kind: str, name: str = "") -> bool:
        """Claim a namespaced name that no earlier link claimed."""
        return kind == TOOL and "__" in name.strip("_") and not name.startswith("__")

    def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
        """Show ``server/tool``, so the row names where the capability came from.

        The runtime names a remote tool ``<server>__<tool>``; a name that prefixed the family with ``mcp`` —
        ``mcp__github__create_issue`` — is read the same way, and one without both parts keeps its own name.
        """
        remote = name[5:] if name.startswith("mcp__") else name
        server, _, tool = remote.partition("__")
        label = f"{server}/{tool}" if server and tool else name
        return ToolRow(f"{label} {summarise(arguments)}".rstrip())


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
        WebSearchTool(),
        AskUserTool(),
        TodoTool(),
        SkillTool(),
        TaskTool(),
        MessageTool(),
        NamespacedTool(),
        FallbackTool(),
        ReasoningHandler(),
        AnswerHandler(),
    )
)
