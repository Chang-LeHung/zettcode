"""Bounded readers and request-time availability, without a real SSH server."""

from types import SimpleNamespace

import pytest

from zettcode.plugin_api import ChildSession, ShellPolicy
from zettcode.ssh.plugin import RemoteTools, SSHPlugin
from zettcode.ssh.remote import MAX_FILE, MAX_OUTPUT, edit, read, read_file
from zettcode.ssh.transport import Askpass, Target, Transport


@pytest.mark.parametrize("reader", [read, read_file])
def test_large_logs_stream_small_ranges(tmp_path, reader):
    path = tmp_path / "log"
    with path.open("w", encoding="utf-8") as output:
        for _ in range(21000):
            output.write("x" * 1000 + "\n")
    assert path.stat().st_size > MAX_FILE
    assert reader(str(path), offset=20999, limit=1) == (
        "20999\t" + "x" * 1000 + "\n\n... [more lines; continue with offset=21000]"
    )
    assert reader(str(path), offset=21000, limit=1) == "21000\t" + "x" * 1000 + "\n"
    with pytest.raises(ValueError, match="File exceeds"):
        edit(str(path), "x", "y", replace_all=True)


@pytest.mark.parametrize("reader", [read, read_file])
def test_long_line_is_bounded_and_can_be_skipped(tmp_path, reader):
    path = tmp_path / "long"
    path.write_text("x" * (MAX_FILE + 1) + "\nlast", encoding="utf-8")
    result = reader(str(path), limit=1)
    assert "... [line truncated; use ssh__bash" in result
    assert len(result.encode()) < MAX_OUTPUT + 200
    assert reader(str(path), offset=2) == "2\tlast"


def test_missing_edit_match_explains_exact_copy(tmp_path):
    path = tmp_path / "file"
    path.write_text(" original\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not found.*whitespace.*prefixes"):
        edit(str(path), "1\toriginal", "changed", replace_all=True)
    assert path.read_text(encoding="utf-8") == " original\n"


def context():
    tools, messages = {}, []
    return SimpleNamespace(
        tools=tools,
        register_tool=lambda item: tools.update({item.name: item}),
        add_message=messages.append,
        messages=messages,
    )


@pytest.mark.parametrize("level", ["safe", "ask", "deny"])
async def test_tool_offers_follow_each_request_permission(level):
    policy = ShellPolicy()
    backend = RemoteTools(Target("alias", "/remote"), policy, "coding")
    policy.level = type(policy.level)("full")
    first = context()
    await backend.on_tool(first)
    assert "ssh__read" in first.tools
    policy.level = type(policy.level)(level)
    second = context()
    await backend.on_tool(second)
    await backend.on_state(second)
    assert not second.tools
    assert f"current: {level}" in second.messages[0].content
    assert "Do not substitute local tools" in second.messages[0].content
    policy.level = type(policy.level)("full")
    third = context()
    await backend.on_tool(third)
    assert third.tools["ssh__read"] is first.tools["ssh__read"]


async def test_restored_password_target_is_retained_but_not_offered(monkeypatch):
    policy = ShellPolicy()
    policy.level = type(policy.level)("full")
    plugin = SSHPlugin()
    plugin.policy = policy
    saved = {"host": "alias", "path": "/remote", "auth": "password"}
    plugin.restore_child(saved)

    async def forbidden(*args, **kwargs):
        pytest.fail("A missing password must not start a transport operation")

    monkeypatch.setattr(Transport, "run", forbidden)
    for backend in (plugin, plugin.child_extensions(ChildSession("subagent", "coding"))[0]):
        request = context()
        await backend.on_tool(request)
        await backend.on_state(request)
        assert not request.tools
        instruction = request.messages[0].content
        assert "never saved or inherited" in instruction and "daemon cannot" in instruction
        assert "key/agent" in instruction and "/ssh" not in instruction
    assert plugin.export_child(ChildSession("daemon")) == {**saved, "user": None}


def test_askpass_rejects_password_change_without_rewriting_secret():
    helper = Askpass()
    try:
        original = helper.environment("first")
        with pytest.raises(ValueError, match="cannot change password"):
            helper.environment("different")
        assert helper.environment("first") == original
    finally:
        helper.close()


@pytest.mark.parametrize("missing", ["secret", "askpass", "directory", "unreadable"])
def test_askpass_recreates_unavailable_helper_in_a_fresh_private_directory(tmp_path, monkeypatch, missing):
    import shutil
    import stat
    import tempfile
    from pathlib import Path

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    helper = Askpass()
    try:
        original = helper.environment("first")
        old = helper.directory
        assert old is not None
        if missing == "directory":
            shutil.rmtree(old)
        elif missing == "unreadable":
            read_text = Path.read_text

            def read(path, *args, **kwargs):
                if path == old / "secret":
                    raise PermissionError("unreadable helper")
                return read_text(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", read)
        else:
            (old / missing).unlink()
        renewed = helper.environment("currently provided")
        assert renewed["SSH_ASKPASS"] != original["SSH_ASKPASS"]
        assert not old.exists()
        directory = helper.directory
        assert directory is not None
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE((directory / "secret").stat().st_mode) == 0o600
        assert (directory / "secret").read_text() == "currently provided\n"
        assert (directory / "askpass").is_file()
        assert helper.environment("currently provided") == renewed
    finally:
        helper.close()
    assert not list(tmp_path.iterdir())


def test_only_requested_schema_is_built_and_serial_mode_survives(monkeypatch):
    from zett_agent.tools.base import ToolExecutionMode

    import zettcode.ssh.tools as tools

    built = []
    original = tools.tool

    def record(**options):
        built.append(options["name"])
        return original(**options)

    monkeypatch.setattr(tools, "tool", record)
    policy = ShellPolicy()
    backend = RemoteTools(Target("alias", "/remote"), policy, "coding")
    first = backend.tool("edit")
    assert backend.tool("edit") is first
    assert built == ["ssh__edit"]
    assert first.execution_mode == ToolExecutionMode.SERIAL
    other = RemoteTools(Target("other", "/elsewhere"), policy, "coding")
    assert other.tool("edit") is not first
