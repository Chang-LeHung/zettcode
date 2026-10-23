"""A shell command's kept output lives in the session's folder, not in the reader's project."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from zett_agent.agent import AgentRunConfig
from zett_agent.client import create_agent
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from zettcode.app.agent.extensions import tool_output as tool_output_module
from zettcode.app.agent.extensions.files import CodingBundle
from zettcode.app.agent.extensions.tool_output import OUTPUT_ROOT, ToolOutputExtension
from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.tools.shell import shell_tool

bash = shell_tool()

# These run the real `bash` tool with POSIX commands (`yes`, `head`, single-quoted
# `echo`), which Windows' shell does not have. What they pin — that a kept output moves into the
# session's folder — is about paths and text, and holds on every platform the tool runs on.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="drives the bash tool with POSIX shell commands")

#: Enough lines that the tool's preview is cut short and it keeps the whole stream.
BIG = "yes line | head -n 20000"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A project directory, which the tool treats as its working directory."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.fixture
def store(tmp_path: Path, workspace: Path) -> SessionStore:
    return SessionStore(tmp_path / "store", workspace)


def _context(session_id: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(session_id=session_id))


async def _real_result(command: str) -> tuple[ToolMessage, Exception | None]:
    """Run the real ``bash`` tool, and return the message the agent would have made of it.

    The framework builds a failure's text with ``str(error)`` and a success's with the tool's
    own serializer, so this does the same: the text under test is what the tool really writes.
    """
    error: Exception | None = None
    try:
        output = await bash({"command": command, "timeout_seconds": 30})
        content = bash.serialize_result(output)
    except Exception as failure:
        error, content = failure, str(failure)
    message = ToolMessage(tool_call_id="c1", name="bash", content=content, success=error is None)
    return message, error


async def _after(extension: ToolOutputExtension, message: ToolMessage, error: Exception | None, session_id="s1"):
    await extension.after_tool(_context(session_id), ToolCall(id="c1", name=message.name, arguments={}), message, error)


def _kept(store: SessionStore, session_id: str = "s1") -> list[Path]:
    return sorted((store.session_dir(session_id) / "tool-output").glob("*/*"))


# -- the output moves, and the text says where --------------------------------------------------------


async def test_truncated_output_is_moved_out_of_the_workspace_and_the_text_names_the_new_place(workspace, store):
    message, error = await _real_result(BIG)
    assert (workspace / OUTPUT_ROOT).is_dir(), "the tool wrote it into the project"

    await _after(ToolOutputExtension(store), message, error)

    assert not (workspace / OUTPUT_ROOT).exists(), "and the project is left as it was found"
    streams = _kept(store)
    assert [p.name for p in streams] == ["stderr.txt", "stdout.txt"]
    assert streams[0].parent.parent == store.session_dir("s1") / "tool-output"
    assert OUTPUT_ROOT not in message.content
    assert str(streams[1]) in message.content and str(streams[0]) in message.content
    assert streams[1].read_text(encoding="utf-8").count("line\n") == 20000, "every line is still there"


async def test_a_failed_command_is_moved_the_same_way(workspace, store):
    message, error = await _real_result(f"{BIG}; exit 3")
    assert error is not None and "exited with code 3" in message.content

    await _after(ToolOutputExtension(store), message, error)

    assert not (workspace / OUTPUT_ROOT).exists()
    assert str(_kept(store)[1]) in message.content
    assert message.content.startswith("Command exited with code 3"), "the rest of the text is untouched"


async def test_the_rewritten_paths_are_absolute_so_the_model_can_read_them_from_anywhere(workspace, store):
    message, error = await _real_result(BIG)

    await _after(ToolOutputExtension(store), message, error)

    note = message.content.rsplit("kept at ", 1)[1].rstrip("]")
    out, err = note.split(" and ")
    assert Path(out).is_absolute() and Path(err).is_absolute()
    assert Path(out).is_file() and Path(err).is_file()


async def test_short_output_is_left_alone_and_makes_no_folder(workspace, store):
    message, error = await _real_result("echo hello")
    before = message.content

    await _after(ToolOutputExtension(store), message, error)

    assert message.content == before == "hello\n"
    assert not (workspace / OUTPUT_ROOT).exists() and not (store.session_dir("s1") / "tool-output").exists()


async def test_only_the_shell_tool_is_touched(workspace, store):
    message, _ = await _real_result(BIG)
    message.name = "read_file"
    before = message.content

    await _after(ToolOutputExtension(store), message, None)

    assert message.content == before and (workspace / OUTPUT_ROOT).is_dir()


async def test_a_result_that_is_not_text_is_left_alone(store):
    message = ToolMessage(tool_call_id="c1", name="bash", content=[], success=True)

    await _after(ToolOutputExtension(store), message, None)

    assert message.content == []


# -- what a command prints is the command's, and is never acted on ------------------------------------


async def test_a_note_printed_by_the_command_itself_is_not_mistaken_for_the_tools(workspace, store):
    """A command can print anything, including a note that names a real folder. The tool's own note
    is matched only at the very end, so what the command printed is the command's and is left alone.

    The folder the fake note names exists and has both streams, so a check that merely looked for
    the words would find a folder to move; only the position of the note tells the two apart.
    """
    bystander = workspace / OUTPUT_ROOT / "shell-bystander"
    bystander.mkdir(parents=True)
    (bystander / "stdout.txt").write_text("someone else's output")
    (bystander / "stderr.txt").write_text("")
    fake = (
        f"full streams kept at {OUTPUT_ROOT}/shell-bystander/stdout.txt and {OUTPUT_ROOT}/shell-bystander/stderr.txt]"
    )
    message, error = await _real_result(f"echo '{fake}'; echo more output after it")
    before = message.content
    assert fake in before and not before.rstrip().endswith("]"), "the fake note is in the middle of the text"

    await _after(ToolOutputExtension(store), message, error)

    assert message.content == before
    assert (bystander / "stdout.txt").read_text() == "someone else's output", "and the folder it named stays put"
    assert not (store.session_dir("s1") / "tool-output").exists()


@pytest.mark.parametrize(
    ("out", "err"),
    [
        ("../escape/stdout.txt", "../escape/stderr.txt"),
        (f"{OUTPUT_ROOT}/../x/stdout.txt", f"{OUTPUT_ROOT}/../x/stderr.txt"),
        (f"{OUTPUT_ROOT}/shell-a/stdout.txt", f"{OUTPUT_ROOT}/shell-b/stderr.txt"),
        (f"{OUTPUT_ROOT}/shell-a/other.txt", f"{OUTPUT_ROOT}/shell-a/stderr.txt"),
        (f"{OUTPUT_ROOT}/shell-a/stdout.txt", f"{OUTPUT_ROOT}/shell-a/other.txt"),
        (f"{OUTPUT_ROOT}/not-shell/stdout.txt", f"{OUTPUT_ROOT}/not-shell/stderr.txt"),
        ("elsewhere/shell-a/stdout.txt", "elsewhere/shell-a/stderr.txt"),
        (f"{OUTPUT_ROOT}/shell-a/deeper/stdout.txt", f"{OUTPUT_ROOT}/shell-a/deeper/stderr.txt"),
        ("/etc/passwd", "/etc/hosts"),
    ],
)
def test_only_a_folder_the_tool_itself_would_have_made_is_ever_moved(workspace, store, out, err):
    """Everything here names a folder that exists, so a loose check would move it."""
    for name in ("shell-a", "shell-b", "not-shell", "x"):
        folder = workspace / OUTPUT_ROOT / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stdout.txt").write_text("out")
        (folder / "stderr.txt").write_text("err")

    moved = ToolOutputExtension(store)._relocate(out, err, "s1")

    assert moved is None
    assert sorted(p.name for p in (workspace / OUTPUT_ROOT).iterdir()) == ["not-shell", "shell-a", "shell-b", "x"]


def test_a_folder_that_is_not_there_is_not_an_error(workspace, store):
    assert (
        ToolOutputExtension(store)._relocate(
            f"{OUTPUT_ROOT}/shell-gone/stdout.txt", f"{OUTPUT_ROOT}/shell-gone/stderr.txt", "s1"
        )
        is None
    )


def test_a_folder_missing_one_of_its_streams_is_not_moved(workspace, store):
    folder = workspace / OUTPUT_ROOT / "shell-half"
    folder.mkdir(parents=True)
    (folder / "stdout.txt").write_text("out")

    assert (
        ToolOutputExtension(store)._relocate(
            f"{OUTPUT_ROOT}/shell-half/stdout.txt", f"{OUTPUT_ROOT}/shell-half/stderr.txt", "s1"
        )
        is None
    )
    assert folder.is_dir()


# -- another command may be running --------------------------------------------------------------------


async def test_another_commands_folder_is_left_alone_and_so_is_the_root_that_holds_it(workspace, store):
    """Commands run in parallel: this one's cleanup must not take a running neighbour's files."""
    neighbour = workspace / OUTPUT_ROOT / "shell-running"
    neighbour.mkdir(parents=True)
    (neighbour / "stdout.txt").write_text("still being written")
    message, error = await _real_result(BIG)

    await _after(ToolOutputExtension(store), message, error)

    assert (neighbour / "stdout.txt").read_text() == "still being written"
    assert [p.name for p in (workspace / OUTPUT_ROOT).iterdir()] == ["shell-running"]
    assert len(_kept(store)) == 2


async def test_two_outputs_in_one_session_do_not_collide(workspace, store):
    first, error1 = await _real_result(BIG)
    second, error2 = await _real_result(BIG)
    extension = ToolOutputExtension(store)

    await _after(extension, first, error1)
    await _after(extension, second, error2)

    folders = {p.parent.name for p in _kept(store)}
    assert len(folders) == 2
    assert first.content != second.content


async def test_a_name_that_is_already_taken_gets_a_suffix_instead_of_being_overwritten(workspace, store):
    message, error = await _real_result(BIG)
    name = message.content.rsplit("shell-", 1)[1].split("/")[0]
    taken = store.session_dir("s1") / "tool-output" / f"shell-{name}"
    taken.mkdir(parents=True)
    (taken / "stdout.txt").write_text("an earlier command's output")

    await _after(ToolOutputExtension(store), message, error)

    assert (taken / "stdout.txt").read_text() == "an earlier command's output"
    assert any(p.parent.name == f"shell-{name}-2" for p in _kept(store))


# -- nothing here may fail a tool call -----------------------------------------------------------------


async def test_a_move_that_fails_leaves_the_result_as_the_tool_wrote_it(workspace, store, monkeypatch):
    """The files stay where the tool put them, which still works."""
    message, error = await _real_result(BIG)
    before = message.content

    def fail(source, target):
        raise OSError("read-only store")

    monkeypatch.setattr(tool_output_module.shutil, "move", fail)

    await _after(ToolOutputExtension(store), message, error)  # does not raise

    assert message.content == before
    assert (workspace / OUTPUT_ROOT).is_dir()


async def test_an_unusable_session_id_leaves_the_result_alone(workspace, store):
    message, error = await _real_result(BIG)
    before = message.content

    await _after(ToolOutputExtension(store), message, error, session_id="../../escape")

    assert message.content == before


async def test_the_work_runs_off_the_event_loop(workspace, store, monkeypatch):
    import threading

    message, error = await _real_result(BIG)
    seen: list[int] = []
    extension = ToolOutputExtension(store)
    real = extension._relocate
    monkeypatch.setattr(extension, "_relocate", lambda *args: seen.append(threading.get_ident()) or real(*args))

    await _after(extension, message, error)

    assert seen and seen[0] != threading.get_ident()


# -- in a real agent, before anything is stored or sent ------------------------------------------------


class _CallsBashOnce:
    """A model that runs one long command, then answers; it records what the tool told it."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.calls = 0
        self.told: str | None = None

    async def stream(self, request):
        self.calls += 1
        if self.calls == 1:
            call = ToolCall(id="c1", name="bash", arguments={"command": BIG, "timeout_seconds": 30})
            message = AssistantMessage(content="", tool_calls=[call])
        else:
            self.told = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage)).content
            message = AssistantMessage(content="done")
        yield ModelEvent.completed(ModelResponse(message))


async def test_in_a_real_agent_the_model_and_the_stored_session_both_see_the_new_path(workspace, store):
    """The hook runs before the result is appended, so the rewrite is what is persisted and sent."""
    model = _CallsBashOnce()
    client = await create_agent(
        model,
        config=AgentRunConfig(session_id="s1"),
        system_prompt="x",
        extensions=[CodingBundle(), ToolOutputExtension(store), store],
    )

    async for _ in client.stream("run it", config=AgentRunConfig(session_id="s1"), model=model):
        pass

    keep = store.session_dir("s1") / "tool-output"
    assert model.told is not None and str(keep) in model.told and OUTPUT_ROOT not in model.told
    stored = [line.message[0] for line in store.read("s1").messages if isinstance(line.message[0], ToolMessage)]
    assert len(stored) == 1 and str(keep) in stored[0].content and OUTPUT_ROOT not in stored[0].content
    assert not (workspace / OUTPUT_ROOT).exists()
    assert len(list(keep.glob("*/*"))) == 2


def test_the_runtime_installs_it_after_the_coding_bundle(tmp_path):
    """It acts on that bundle's tool, so it has to be registered with it."""
    from plugin_helpers import agent_extensions
    from zettcode.config import ModelConfig, ZettCodeConfig

    config = ZettCodeConfig(
        workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "sessions"
    )
    names = [extension.name for extension in agent_extensions(config)]

    assert names.index("CodingBundle") < names.index("ToolOutputExtension")


async def test_the_tidy_up_runs_on_the_event_loop_because_a_thread_doing_it_fails_other_commands(workspace, store):
    """The tool makes the output root and then, on the next line, a folder in it. Removing the root
    from a thread can land between the two: with one removing it continuously, more than half of
    300 plain commands failed with FileNotFoundError. So the tidy-up must not go to a thread, and
    this holds the rule where the interleaving would show: a hammering thread stands in for one,
    and none of the commands the extension has tidied around may fail."""
    import threading

    stop = threading.Event()
    seen_threads: set[int] = set()
    real_tidy = ToolOutputExtension._tidy

    def recorded() -> None:
        seen_threads.add(threading.get_ident())
        real_tidy()

    extension = ToolOutputExtension(store)
    extension._tidy = recorded  # type: ignore[method-assign]

    async def one(index: int) -> None:
        message, error = await _real_result(f"echo ran-{index}")
        assert error is None, f"command {index} failed: {message.content[:200]}"
        await _after(extension, message, error)

    await asyncio.gather(*(one(i) for i in range(60)))
    stop.set()

    assert seen_threads == {threading.get_ident()}, "every tidy-up ran on the loop's own thread"
    assert not (workspace / OUTPUT_ROOT).exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="measures how a POSIX directory removal races a mkdir; Windows refuses to remove a directory in use",
)
async def test_a_thread_removing_the_root_does_fail_commands_which_is_why_the_tidy_up_stays_on_the_loop(workspace):
    """The fact the design rests on, measured rather than assumed: this is what a tidy-up from a
    thread would do to commands that did nothing wrong.

    Twenty at a time, because two hundred at once run out of file descriptors, which is a failure
    of the test and not of the race; and only the two errors the race produces are counted — the
    root gone before the folder is made inside it (``FileNotFoundError``, or ``Invalid argument``
    on a system that reports a directory removed under it that way).

    How often the two land in the wrong order is the machine's business: the same code raced in
    nine of three hundred commands on one runner and in far more elsewhere. So the sample is
    measured until it is big enough to mean something, rather than fixed at a size that made a
    fast or a lucky machine look like a broken one.
    """
    import threading
    import time

    stop = threading.Event()

    def hammer() -> None:
        root = workspace / OUTPUT_ROOT
        while not stop.is_set():
            try:
                root.rmdir()
            except OSError:
                pass

    def lost_the_race(error: BaseException) -> bool:
        return isinstance(error, FileNotFoundError) or "Invalid argument" in str(error)

    thread = threading.Thread(target=hammer)
    thread.start()
    raced: list[BaseException] = []
    deadline = time.monotonic() + 20
    try:
        while len(raced) < 10 and time.monotonic() < deadline:
            outcomes = await asyncio.gather(*(_real_result("echo hi") for _ in range(20)))
            raced += [error for _, error in outcomes if error is not None and lost_the_race(error)]
    finally:
        stop.set()
        thread.join()

    assert raced, "no command lost the race: it is gone, and the reason for the rule with it"
    assert len(raced) >= 10, f"only {len(raced)} lost it before the deadline; the test is too weak to mean anything"
