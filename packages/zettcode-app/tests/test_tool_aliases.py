"""Explicit plugin aliases share local rendering in live and restored transcripts."""

from dataclasses import fields

import pytest
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage

from zettcode.app.agent.conversation.rendering import DEFAULT_RENDERERS
from zettcode.app.agent.conversation.replay import replay
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.engine.storage import SessionStore
from zettcode.plugin_api import Presenter
from zettcode.plugin_api.presenters import ToolRenderingAlias
from zettcode.presenters.presenters import DEFAULT_PRESENTERS
from zettcode.tui import DARK


class Aliases(Presenter):
    """A plugin explicitly opts known tool names into local rendering."""

    def tool_rendering_alias(self, name):
        names = {f"ssh__{tool}": tool for tool in ("read", "read_file", "write_file", "edit", "bash")}
        return ToolRenderingAlias(names[name], "ssh/") if name in names else None

    def handle(self, entry, next):
        return next(entry)

    def lines(self, entry, width, theme, frame):
        raise AssertionError("alias provider does not draw")


PRESENTERS = DEFAULT_PRESENTERS.replacing(Aliases())
CASES = [
    ("read", {"file_path": "app.py"}, "1\tdef hello():\n2\t    return 1\n... [more lines; offset=3]"),
    ("read_file", {"file_path": "app.py"}, "def hello():\n    return 1"),
    ("write_file", {"file_path": "app.py", "content": "def hello():\n    return 1\n"}, "Created app.py"),
    (
        "edit",
        {"file_path": "app.py", "old_string": "return 1", "new_string": "return 2\nreturn 3"},
        "Replaced 1 occurrence",
    ),
    ("bash", {"command": "printf hello", "work_dir": "src"}, "hello\n[stderr]\nwarning"),
]


@pytest.mark.parametrize("name", ["read", "read_file"])
def test_long_remote_line_hint_is_not_counted_as_file_content(name):
    transcript = Transcript(clock=lambda: 0, presenters=PRESENTERS)
    transcript.start_tool("call", f"ssh__{name}", {"file_path": "app.py"})
    transcript.complete_tool(
        "call",
        "1\tprint('long')\n... [line truncated; use ssh__bash for a bounded slice of this remote line]",
        wait=False,
    )
    entry = transcript.entries[0]
    assert entry.lines == 1 and entry.language == "python"
    assert entry.tool == f"ssh__{name}"


def shape(entry):
    return {
        field.name: getattr(entry, field.name)
        for field in fields(entry)
        if field.name not in {"tool", "title", "started_at", "duration", "block", "block_key"}
    }


@pytest.mark.parametrize("name,arguments,output", CASES)
@pytest.mark.parametrize("expanded", [False, True])
def test_aliases_render_like_local_tools_without_losing_identity(name, arguments, output, expanded):
    transcript = Transcript(clock=lambda: 0, presenters=PRESENTERS)
    local = Transcript(clock=lambda: 0)
    transcript.start_tool("call", f"ssh__{name}", arguments)
    local.start_tool("call", name, arguments)
    remote_entry, local_entry = transcript.entries[0], local.entries[0]
    assert type(remote_entry) is type(local_entry)
    assert remote_entry.title == "ssh/" + local_entry.title
    transcript.complete_tool("call", output, wait=False)
    local.complete_tool("call", output, wait=False)
    transcript.restate_tool("call", arguments)
    assert remote_entry.title == "ssh/" + local_entry.title
    remote_entry.expanded = local_entry.expanded = expanded
    assert shape(remote_entry) == shape(local_entry)
    if name.startswith("read"):
        assert remote_entry.lines == 2
        assert remote_entry.language == "python"
    if name == "write_file":
        assert remote_entry.added == 2 and remote_entry.diff
    if name == "edit":
        assert (remote_entry.added, remote_entry.removed) == (2, 1)
        assert remote_entry.diff
    remote_lines = PRESENTERS.lines(remote_entry, 120, DARK, 0)
    local_lines = DEFAULT_PRESENTERS.lines(local_entry, 120, DARK, 0)
    assert len(remote_lines) == len(local_lines)
    for remote_line, local_line in zip(remote_lines, local_lines, strict=True):
        assert [span.style for span in remote_line.spans] == [span.style for span in local_line.spans]
        assert [span.text.removeprefix("ssh/") for span in remote_line.spans] == [
            span.text for span in local_line.spans
        ]
    source = PRESENTERS.block(remote_entry, 120, DARK, 0)
    assert PRESENTERS.block(remote_entry, 120, DARK, 0) is source
    assert remote_entry.tool == f"ssh__{name}"
    assert DEFAULT_RENDERERS.describe(f"ssh__{name}", arguments).title != remote_entry.title


def test_unknown_namespaced_tools_have_no_suffix_fallback():
    transcript = Transcript(presenters=PRESENTERS)
    for name in ("other__read", "mcp__server__edit", "ssh__unknown"):
        transcript.start_tool(name, name, {"file_path": "app.py"})
        entry = transcript.entries[-1]
        assert type(entry).__name__ == "ToolEntry"
        assert entry.tool == name
        assert not entry.title.startswith(("Read ", "Edit "))
        PRESENTERS.block(entry, 120, DARK, 0)
        assert entry.tool == name


@pytest.mark.parametrize("name,arguments,output", CASES)
async def test_resume_uses_the_same_aliases_and_preserves_stored_names(tmp_path, name, arguments, output):
    tool = f"ssh__{name}"
    live = Transcript(clock=lambda: 0, presenters=PRESENTERS)
    live.start_tool("call", tool, arguments)
    live.complete_tool("call", output, wait=False)
    store = SessionStore(tmp_path)
    await store.append("s", "req", AssistantMessage(tool_calls=(ToolCall("call", tool, arguments),)))
    await store.append("s", "req", ToolMessage(tool_call_id="call", name=tool, content=output))
    restored = replay(store.read("s"), presenters=PRESENTERS, renderers=live.renderers).transcript
    remote = restored.entries[0]
    assert type(remote) is type(live.entries[0])
    assert shape(remote) == shape(live.entries[0])
    assert remote.title == live.entries[0].title
    assert remote.tool == tool
    assert PRESENTERS.lines(remote, 120, DARK, 0) == PRESENTERS.lines(live.entries[0], 120, DARK, 0)
    assert store.read("s").branch()[0].message[0].tool_calls[0].name == tool
