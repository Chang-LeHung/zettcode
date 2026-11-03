"""A tool result too long to send is kept in a file, and the model reads the rest of it from there."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from zett_agent.agent import AgentRunConfig
from zett_agent.client import create_agent
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import AssistantMessage, TextContent, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions
from zett_agent.tools.base import tool

from zettcode.engine.extensions.truncation import (
    MAX_RESULT_BYTES,
    MAX_RESULT_LINES,
    LongOutputExtension,
    over_budget,
)
from zettcode.engine.storage import SessionStore
from zettcode.engine.tools.files import read

#: A result over both budgets: more lines than a tool may send, and more bytes than one file of them.
LONG = "".join(f"line {n}\n" for n in range(1, 3001))

#: Where the text says the whole of a result is; the note names the file by absolute path.
WHERE = re.compile(r"the whole of it is at (\S+) \u2014 read that file with the read tool")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A project directory, which is the working directory the tools resolve paths against."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.fixture
def store(tmp_path: Path, workspace: Path) -> SessionStore:
    return SessionStore(tmp_path / "store", workspace)


def _extension(store: SessionStore) -> LongOutputExtension:
    return LongOutputExtension(store)


def _context(session_id: str | None = "s1") -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(session_id=session_id))


async def _after(
    extension: LongOutputExtension,
    message: ToolMessage,
    *,
    name: str = "docs__search",
    call_id: str = "c1",
    session_id: str | None = "s1",
    error: Exception | None = None,
) -> None:
    call = ToolCall(id=call_id, name=name, arguments={})
    await extension.after_tool(_context(session_id), call, message, error)


def _kept(store: SessionStore, session_id: str = "s1") -> list[Path]:
    folder = store.session_dir(session_id) / "tool-output"
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


# -- what is kept, and what the model is sent instead -------------------------------------------------


async def test_an_over_long_result_is_kept_whole_and_the_text_says_where(store: SessionStore):
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message)

    assert isinstance(message.content, str)
    (kept,) = _kept(store)
    assert kept.read_text(encoding="utf-8") == LONG, "the file holds the result exactly as the tool wrote it"
    assert WHERE.search(message.content), message.content[-300:]
    assert Path(WHERE.search(message.content).group(1)) == kept, "named by the absolute path, since it is outside"
    assert message.content.startswith("line 1\n") and message.content.rstrip().endswith("line 3000")
    assert "middle omitted" in message.content and len(message.content) < len(LONG)


async def test_the_kept_result_is_where_the_text_says_and_read_opens_it(store: SessionStore):
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message)

    path = WHERE.search(message.content).group(1)
    assert await read.handler(file_path=path, limit=2) == "line 1\nline 2\n\n... [more lines; continue with offset=3]"


async def test_the_kept_file_is_in_the_session_folder_and_never_in_the_project(store: SessionStore, workspace: Path):
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message)

    (kept,) = _kept(store)
    assert kept.is_relative_to(store.session_dir("s1") / "tool-output")
    assert not any(workspace.rglob("*.txt")), "the reader's project is left as it was found"


async def test_a_result_within_the_budget_is_left_exactly_as_it_was(store: SessionStore):
    small = "x" * (MAX_RESULT_BYTES - 1)
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=small)

    await _after(_extension(store), message)

    assert message.content == small and _kept(store) == []


def test_the_budget_leaves_room_for_every_note_a_tool_of_ours_ends_with():
    """A result our tools bounded is never taken apart here: the room for their note is the margin."""
    from zettcode.engine.tools.output import MAX_OUTPUT_BYTES, MAX_OUTPUT_LINES

    assert MAX_RESULT_BYTES > MAX_OUTPUT_BYTES and MAX_RESULT_LINES > MAX_OUTPUT_LINES
    assert MAX_RESULT_BYTES - MAX_OUTPUT_BYTES >= 1024, "a path and a sentence fit the margin"


async def test_a_result_of_our_own_read_tool_at_its_budget_is_left_exactly_as_it_was(
    store: SessionStore, workspace: Path
):
    """The margin above is real: a read that fills the budget comes back untouched and makes no file."""
    from zettcode.engine.tools.output import MAX_OUTPUT_BYTES

    (workspace / "wide.txt").write_text("z" * (MAX_OUTPUT_BYTES - 100) + "\n")
    text = await read.handler(file_path="wide.txt")
    message = ToolMessage(tool_call_id="c1", name="read", content=text)

    await _after(_extension(store), message, name="read")

    assert message.content == text and _kept(store) == []


async def test_the_marker_is_written_once_where_the_cut_is_even_if_the_text_quotes_it(store: SessionStore):
    """A tool result can contain the generic marker; the note that names the file belongs at the cut."""
    from zettcode.engine.tools.output import OMISSION

    body = "head\n" + OMISSION + "middle\n" + "row\n" * 6000
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=body)

    await _after(_extension(store), message)

    (kept,) = _kept(store)
    assert kept.read_text(encoding="utf-8") == body, "the file holds what the tool sent, marker and all"
    assert message.content.count(OMISSION) == 1, "the quoted marker is still in the head, where the tool put it"
    assert message.content.count("the whole of it is at") == 1, "one note names the file, at the cut"
    assert message.content.index(OMISSION) < message.content.index("the whole of it is at")
    assert message.content.endswith("row\n"), "the tail is the end of what the tool sent"


async def test_the_kept_file_is_byte_for_byte_what_the_tool_sent(store: SessionStore):
    """Text mode writes `\r\n` on Windows, and the preview reads the bytes back: the file must be exact.

    On POSIX this passes either way, which is why it is written against the bytes and not through a text-mode
    read: the Windows run of the suite is what it holds.
    """
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message)

    (kept,) = _kept(store)
    assert kept.read_bytes() == LONG.encode("utf-8")


async def test_a_result_with_carriage_return_lines_is_kept_like_any_other(store: SessionStore):
    """`splitlines()` counts CR alone as a line; a guard that counted only `\n` would send three thousand of them."""
    body = "x\r" * 3000
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=body)

    await _after(_extension(store), message)

    (kept,) = _kept(store)
    assert kept.read_bytes().decode("utf-8") == body, "read as bytes: text mode would translate the CRs"
    assert len(message.content) < len(body)


async def test_a_result_with_too_many_lines_is_kept_even_though_its_bytes_are_few(store: SessionStore):
    many = "x\n" * (MAX_RESULT_LINES + 1)
    message = ToolMessage(tool_call_id="c1", name="task", content=many)

    await _after(_extension(store), message, name="task")

    assert len(many.encode()) < MAX_RESULT_BYTES and over_budget(many)
    (kept,) = _kept(store)
    assert kept.read_text(encoding="utf-8") == many


async def test_a_failed_calls_message_is_kept_the_same_way(store: SessionStore):
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG, success=False)

    await _after(_extension(store), message, error=RuntimeError("the server answered with an essay"))

    assert _kept(store) and "middle omitted" in message.content


async def test_the_shells_own_kept_output_is_left_to_the_shell(store: SessionStore):
    text = (
        LONG
        + "\n... [output truncated; full streams kept at .zett-tool-output/shell-1/stdout.txt and .zett-tool-output/shell-1/stderr.txt]"
    )
    message = ToolMessage(tool_call_id="c1", name="bash", content=text)

    await _after(_extension(store), message, name="bash")

    assert message.content == text and _kept(store) == []


async def test_a_result_that_is_not_text_is_left_alone(store: SessionStore):
    parts = [TextContent(text="x" * (MAX_RESULT_BYTES + 1))]
    message = ToolMessage(tool_call_id="c1", name="read", content=parts)

    await _after(_extension(store), message, name="read")

    assert message.content == parts and _kept(store) == []


async def test_a_call_with_no_session_yet_is_left_alone(store: SessionStore):
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message, session_id=None)

    assert message.content == LONG


# -- the file ------------------------------------------------------------------------------------------


async def test_two_calls_that_share_a_name_get_their_own_files(store: SessionStore):
    first = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)
    second = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG.replace("line", "row"))

    await _after(_extension(store), first)
    await _after(_extension(store), second)

    kept = sorted(path.read_text(encoding="utf-8") for path in _kept(store))
    assert kept == sorted([LONG, LONG.replace("line", "row")])


async def test_a_name_from_the_model_cannot_leave_the_folder(store: SessionStore):
    message = ToolMessage(tool_call_id="../../escape", name="../etc/passwd", content=LONG)

    await _after(_extension(store), message, name="../etc/passwd", call_id="../../escape")

    (kept,) = _kept(store)
    assert kept.parent == store.session_dir("s1") / "tool-output"
    assert "/" not in kept.name and ".." not in kept.name


def test_two_writers_of_one_name_never_share_a_file(store: SessionStore):
    """The name is claimed by creating the file, so two calls that reach the folder together keep both texts."""
    import threading

    extension = _extension(store)
    call = ToolCall(id="c1", name="docs__search", arguments={})
    texts = [f"text {number}\n" * 20 for number in range(8)]

    threads = [threading.Thread(target=extension._write, args=(text, call, "s1")) for text in texts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    kept = _kept(store)
    assert len(kept) == len(texts)
    assert sorted(path.read_text(encoding="utf-8") for path in kept) == sorted(texts)


async def test_a_store_that_cannot_be_written_leaves_the_result_as_it_was(store: SessionStore, monkeypatch):
    def refuse(session_id: str) -> Path:
        raise OSError("no room")

    monkeypatch.setattr(store, "session_dir", refuse)
    message = ToolMessage(tool_call_id="c1", name="docs__search", content=LONG)

    await _after(_extension(store), message)

    assert message.content == LONG, "nothing here may fail a tool call"


# -- in a real agent, before anything is stored or sent -------------------------------------------------


@tool
async def essay() -> str:
    """Return a long answer, the way a tool from somewhere else can.

    Guidelines:
        - Nothing here bounds what it returns.
    """
    return LONG


class _RegistersEssay(AgentExtension):
    """A tool this repository does not ship: nothing bounds what it returns."""

    async def on_tool(self, context) -> None:
        context.register_tool(essay)


class _CallsEssayOnce:
    """A model that calls the unbounded tool once, then answers; it records what it was told."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.calls = 0
        self.told: str | None = None

    async def stream(self, request):
        self.calls += 1
        if self.calls == 1:
            message = AssistantMessage(content="", tool_calls=[ToolCall(id="c1", name="essay", arguments={})])
        else:
            self.told = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage)).content
            message = AssistantMessage(content="done")
        yield ModelEvent.completed(ModelResponse(message))


async def test_in_a_real_agent_the_model_and_the_stored_session_both_see_the_preview_and_the_file(store):
    """The hook runs before the result is appended, so the preview is what is persisted and sent."""
    model = _CallsEssayOnce()
    client = await create_agent(
        model,
        config=AgentRunConfig(session_id="s1"),
        system_prompt="x",
        extensions=[_RegistersEssay(), LongOutputExtension(store), store],
    )

    async for _ in client.stream("have a look", config=AgentRunConfig(session_id="s1"), model=model):
        pass

    (kept,) = _kept(store)
    assert kept.read_text(encoding="utf-8") == LONG
    assert model.told is not None and str(kept) in model.told and LONG not in model.told
    stored = [line.message[0] for line in store.read("s1").messages if isinstance(line.message[0], ToolMessage)]
    assert len(stored) == 1 and str(kept) in stored[0].content and LONG not in stored[0].content
