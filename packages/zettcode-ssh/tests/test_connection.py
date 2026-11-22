"""Persistent worker, typed tools and terminal panel regressions."""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from zett_agent.tools.base import AgentTool, ToolExecutionMode

from zettcode.plugin_api import PasteEvent, TextEvent
from zettcode.ssh.panel import SSHPage
from zettcode.ssh.plugin import SSHPlugin
from zettcode.ssh.tools import ALL, descriptor
from zettcode.ssh.transport import Target, Transport


@pytest.fixture
async def connection(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    script = directory / "ssh"
    script.write_text(
        f"#!{sys.executable} -I\nimport os, shlex, sys\n"
        "args = shlex.split(sys.argv[-1])\n"
        "os.execv(sys.executable, [sys.executable, *args[1:]])\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    transport = Transport(Target("alias", str(tmp_path)))
    try:
        yield transport, tmp_path
    finally:
        await transport.aclose()


async def test_persistent_stderr_is_drained_beyond_diagnostic_limit(connection):
    transport, directory = connection
    script = directory / "bin" / "ssh"
    script.write_text(
        f"#!{sys.executable} -I\nimport os, shlex, sys\n"
        "os.write(2, b'diagnostic' * 30000)\n"
        "args = shlex.split(sys.argv[-1])\n"
        "os.execv(sys.executable, [sys.executable, *args[1:]])\n",
        encoding="utf-8",
    )
    assert await asyncio.wait_for(transport.run("ping", {}), 5) == str(directory)
    assert transport.status == "connected"


async def test_diagnostic_stream_keeps_exactly_the_first_16_kib():
    from zettcode.ssh.transport import diagnostic_stream

    stream = asyncio.StreamReader()
    for _ in range(30):
        stream.feed_data(b"diagnostic" * 1000)
    stream.feed_eof()
    kept = await diagnostic_stream(stream, 16 * 1024)
    assert kept == (b"diagnostic" * 3000)[: 16 * 1024]


async def test_one_channel_reused_for_all_operations_and_failures(connection):
    transport, directory = connection
    assert await transport.run("ping", {}) == str(directory)
    process = transport._process
    assert process is not None
    await transport.run("write_file", {"file_path": "file", "content": "before\n"})
    with pytest.raises(RuntimeError, match="unique match"):
        await transport.run("edit", {"file_path": "file", "old_string": "missing", "new_string": "wrong"})
    await transport.run("edit", {"file_path": "file", "old_string": "before", "new_string": "after"})
    reads = await asyncio.gather(*(transport.run("read_file", {"file_path": "file"}) for _ in range(5)))
    assert reads == ["1\tafter\n"] * 5
    assert transport._process is process and transport.status == "connected"
    await transport.aclose()
    assert process.returncode is not None
    with pytest.raises(RuntimeError, match="closed by its owner"):
        await transport.run("ping", {})


async def test_disconnect_latches_and_never_retries_write(connection):
    transport, directory = connection
    await transport.run("ping", {})
    process = transport._process
    process.kill()
    await process.wait()
    with pytest.raises(RuntimeError):
        await transport.run("write_file", {"file_path": "must-not-exist", "content": "bad"})
    assert not (directory / "must-not-exist").exists()
    # A new explicit request reconnects, but the failed write was not automatically replayed.
    await transport.run("ping", {})
    assert not (directory / "must-not-exist").exists()
    assert transport._process is not process


async def test_cancelled_request_closes_channel_and_cannot_desynchronize(connection):
    transport, _ = connection
    await transport.run("ping", {})
    process = transport._process
    task = asyncio.create_task(transport.run("bash", {"command": "sleep 0.2", "timeout_seconds": 1}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode is not None
    assert await transport.run("ping", {})
    assert transport._process is not process


async def test_terminal_command_only_and_connection_apply(connection):
    from zettcode.plugin_api import POLICY, CommandContext, PluginContext, ShellPolicy, ZettCodeConfig

    transport, directory = connection
    policy = ShellPolicy()
    policy.level = type(policy.level)("full")
    plugin = SSHPlugin()
    ctx = PluginContext(
        ZettCodeConfig(workspace=directory, models=(), store=directory / "store"), {POLICY: policy}, name="ssh"
    )
    from zettcode.app.plugins.groups import TuiGroups

    group = TuiGroups(ctx)
    ctx.attach_tui(group)
    plugin.activate(ctx)
    assert not ctx.commands.commands
    assert group.registered_commands[0].name == "/ssh" and group.registered_commands[0].when_busy == "refuse"
    closed, notices = [], []
    host = SimpleNamespace(client=SimpleNamespace(busy=False), close_page=lambda: closed.append(True))
    command = CommandContext("", SimpleNamespace(notify=notices.append), host)
    result = await plugin.open_panel(command)
    # bottom_panel owns exactly one overlay child, the target editor.
    page = result.widget.children[0]
    page.values = ["alias", str(directory)]
    page.mark = 2
    page.confirm(SimpleNamespace(invalidate=lambda: None))
    await page.pending
    assert plugin.target == Target("alias", str(directory))
    assert plugin.backend().transport.status == "connected"
    await plugin.aclose()


async def test_typed_decorator_validates_before_handler():
    seen = []

    async def handler(**arguments):
        seen.append(arguments)
        return "ok"

    for name in ALL:
        assert isinstance(descriptor(name, handler), AgentTool)
    reading = descriptor("read_file", handler)
    with pytest.raises(ValueError):
        await reading.handler(file_path="file", offset=0)
    assert not seen
    assert await reading.handler(file_path="file", limit=1) == "ok"
    assert seen == [{"file_path": "file", "offset": 1, "limit": 1}]
    assert descriptor("edit", handler).execution_mode is ToolExecutionMode.SERIAL


def test_children_share_channel_but_not_extension():
    from zettcode.plugin_api import ChildSession, ShellPolicy

    plugin = SSHPlugin()
    plugin.target = Target("alias", "/remote")
    plugin.policy = ShellPolicy()
    a = plugin.child_extensions(ChildSession("subagent", "coding"))[0]
    b = plugin.child_extensions(ChildSession("subagent", "explore"))[0]
    assert a is not b and a.transport is b.transport is plugin.backend().transport
    restored = SSHPlugin()
    restored.restore_child(plugin.export_child(ChildSession("daemon")))
    restored.policy = ShellPolicy()
    assert restored.backend().transport is not a.transport


async def test_panel_drafts_errors_apply_and_cancel():
    applied, closed = [], []

    async def apply(target):
        applied.append(target)

    host = SimpleNamespace(invalidate=lambda: None)
    page = SSHPage(target=None, status=lambda: "off", on_apply=apply, on_close=lambda: closed.append(True))
    page.handle(TextEvent(text="alias"), host)
    page.mark = 1
    page.handle(PasteEvent(text="relative"), host)
    page.mark = 2
    page.confirm(host)
    assert page.error and not applied and not closed
    page.values[1] = "/remote"
    page.confirm(host)
    await page.pending
    assert applied == [Target("alias", "/remote")] and closed == [True]

    gate = asyncio.Event()

    async def blocking(target):
        await gate.wait()
        applied.append(target)

    page = SSHPage(target=None, status=lambda: "off", on_apply=blocking, on_close=lambda: closed.append(True))
    page.values = ["alias", "/other"]
    page.mark = 2
    page.confirm(host)
    await asyncio.sleep(0)
    page.pending.cancel()
    await page.pending
    assert "Cancelled" in page.error and len(applied) == 1
