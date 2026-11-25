from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shlex
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.messages import ImageContent, SystemMessage, ToolMessage

from zettcode.plugin_api import POLICY, ChildSession, PluginContext, ShellPolicy, shell_environment
from zettcode.ssh import SSHPlugin, __version__
from zettcode.ssh.remote import MAX_OUTPUT
from zettcode.ssh.transport import MAX_RESPONSE, Target, Transport, bounded


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """A fake OpenSSH executable: exercise real stdin, subprocess, quoting and the standalone payload."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "ssh"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, shlex, sys\n"
        "args = shlex.split(sys.argv[-1])\n"
        "assert args[:3] == ['python3', '-I', '-c']\n"
        "os.execv(sys.executable, [sys.executable, *args[1:]])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    remote = tmp_path / "remote ' $ (project)"
    remote.mkdir()
    return Transport(Target("user@build-alias", str(remote)), persistent=False), remote


async def test_all_tools_use_json_and_utf8_without_shell_injection(fake_ssh):
    transport, remote = fake_ssh
    name = "a '; touch PWNED; # 中文.txt"
    assert "Created" in await transport.run("write_file", {"file_path": name, "content": "你好\nunique\nlast\n"})
    assert (remote / name).read_text(encoding="utf-8") == "你好\nunique\nlast\n"
    assert not (remote / "PWNED").exists()
    assert (
        await transport.run("read", {"file_path": name, "limit": 1})
        == "1\t你好\n\n... [more lines; continue with offset=2]"
    )
    assert (
        await transport.run("read_file", {"file_path": name, "offset": 2, "limit": 1})
        == "2\tunique\n\n... [more lines; continue with offset=3]"
    )
    assert "Replaced 1 occurrence" in await transport.run(
        "edit", {"file_path": name, "old_string": "unique", "new_string": "新"}
    )
    assert name in await transport.run("glob", {"pattern": "*.txt"})
    assert f"{name}:2: 新" in await transport.run("grep", {"pattern": "新", "file_pattern": "*.txt"})
    with pytest.raises(RuntimeError, match="exit code: 7") as failure:
        await transport.run("bash", {"command": "printf 'remote output'; exit 7"})
    assert "remote output" in str(failure.value)
    (remote / "sub").mkdir()
    result = await transport.run("bash", {"command": "pwd", "work_dir": "sub"})
    assert str(remote / "sub") in result


async def test_images_and_text_only_reader(fake_ssh):
    transport, remote = fake_ssh
    content = b"\x89PNG\r\n\x1a\n\xff"
    (remote / "image.png").write_bytes(content)
    parts = await transport.run("read", {"file_path": "image.png"})
    assert isinstance(parts[1], ImageContent) and parts[1].source.data == content
    with pytest.raises(RuntimeError, match="UnicodeDecodeError"):
        await transport.run("read_file", {"file_path": "image.png"})


async def test_exact_edits_atomic_modes_and_line_endings(fake_ssh):
    transport, remote = fake_ssh
    path = remote / "file"
    path.write_bytes(b"a\r\na\r\n")
    path.chmod(0o640)
    for old in ("absent", "a"):
        with pytest.raises(RuntimeError, match="not found" if old == "absent" else "unique match"):
            await transport.run("edit", {"file_path": "file", "old_string": old, "new_string": "b"})
        assert path.read_bytes() == b"a\r\na\r\n"
    await transport.run("edit", {"file_path": "file", "old_string": "a", "new_string": "中", "replace_all": True})
    assert path.read_bytes() == "中\r\n中\r\n".encode()
    assert path.stat().st_mode & 0o777 == 0o640
    assert not list(remote.glob(".zettcode-ssh-*"))


async def test_bounded_reads_search_output_and_bash(fake_ssh):
    transport, remote = fake_ssh
    (remote / "long").write_text("中" * MAX_OUTPUT, encoding="utf-8")
    result = await transport.run("read_file", {"file_path": "long"})
    assert "line truncated" in result and len(result.encode()) < MAX_OUTPUT + 200
    for name in ("a.txt", "b.txt", "c.txt"):
        (remote / name).write_text("hello\nhello\n", encoding="utf-8")
    assert "truncated" in await transport.run("glob", {"pattern": "*.txt", "max_results": 1})
    assert "truncated" in await transport.run("grep", {"pattern": "HELLO", "case_sensitive": False, "max_results": 1})
    result = await transport.run("bash", {"command": "python3 -c 'print(\"x\" * 100000)'"})
    assert "truncated" in result and len(result) < MAX_OUTPUT + 200
    with pytest.raises(RuntimeError, match="timed out"):
        await transport.run("bash", {"command": "sleep 2", "timeout_seconds": 0.05})


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("read_file", {"file_path": "file", "offset": 0}),
        ("read_file", {"file_path": "file", "limit": 2001}),
        ("edit", {"file_path": "file", "old_string": "", "new_string": "x"}),
        ("grep", {"pattern": "["}),
        ("glob", {"pattern": "*", "max_results": True}),
        ("read", {"file_path": "file", "unexpected": True}),
    ],
)
async def test_remote_validation(fake_ssh, operation, arguments):
    transport, _ = fake_ssh
    with pytest.raises(RuntimeError):
        await transport.run(operation, arguments)


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"host": "alias"},
        {"host": "-oProxyCommand=bad", "path": "/tmp"},
        {"host": "alias;bad", "path": "/tmp"},
        {"host": "alias", "path": "relative"},
        {"host": "alias", "path": "/tmp\n"},
        {"host": 3, "path": "/tmp"},
        {"host": "alias", "path": "/tmp", "token": "secret"},
    ],
)
def test_malformed_inherited_target(state):
    with pytest.raises(ValueError):
        SSHPlugin().restore_child(state)


@pytest.fixture
def plugin():
    instance = SSHPlugin()
    instance.policy = ShellPolicy()
    instance.policy.level = type(instance.policy.level)("full")
    instance.restore_child({"host": "alias", "path": "/srv/remote project"})
    return instance


def test_restore_never_probes_and_export_has_no_credentials(plugin):
    target = plugin.target
    assert "not connected" in plugin.status()
    assert plugin.export_child(ChildSession("daemon")) == {
        "host": "alias",
        "path": "/srv/remote project",
        "user": None,
        "auth": "key",
    }
    restored = SSHPlugin()
    restored.restore_child(plugin.export_child(ChildSession("daemon")))
    assert restored.target == target and not restored._transports
    local = SSHPlugin()
    assert local.export_child(ChildSession("daemon")) is None
    assert local.child_extensions(ChildSession("subagent", "coding")) == ()


@pytest.mark.parametrize("level", ["deny", "ask", "safe"])
@pytest.mark.parametrize(
    "profile,operation",
    [
        ("coding", "read"),
        ("coding", "write_file"),
        ("coding", "edit"),
        ("coding", "bash"),
        ("explore", "read"),
        ("explore", "glob"),
        ("explore", "grep"),
    ],
)
async def test_permissions_refuse_every_remote_action(plugin, monkeypatch, level, profile, operation):
    plugin.policy.level = type(plugin.policy.level)(level)

    async def forbidden(*args, **kwargs):
        pytest.fail("No SSH process may start below full permission")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    backend = plugin.backend(profile)
    with pytest.raises(PermissionError, match="local safe sandbox cannot protect"):
        await backend.invoke(operation, {})


async def test_the_remote_tools_are_added_beside_the_local_ones(plugin, monkeypatch):
    """The local names stay as they are; the remote operations arrive under ssh__ names."""
    seen = []

    async def remote(self, operation, arguments):
        seen.append((self.target, operation))
        return "remote"

    monkeypatch.setattr(Transport, "run", remote)
    tools = {}
    messages = []
    context = SimpleNamespace(
        tools={"read": object(), "read_file": object(), "bash": object()},
        register_tool=lambda tool: tools.update({tool.name: tool}),
        add_message=messages.append,
    )
    plugin.policy.level = type(plugin.policy.level)("full")
    await plugin.on_tool(context)
    assert {"read", "read_file", "bash"} <= set(context.tools), "no local tool is replaced"
    assert set(tools) == {"ssh__read", "ssh__write_file", "ssh__edit", "ssh__bash"}, (
        "coding mirrors the local bundle: read, write, edit and the shell; searching is the shell's job"
    )
    await plugin.on_state(context)
    text = messages[0].content
    assert "ssh__read" in text and "still work on this machine" in text
    assert await tools["ssh__read"].handler(file_path="x") == "remote"
    assert seen == [(plugin.target, "read")]


async def test_dynamic_policy_and_child_snapshots(plugin, monkeypatch):
    child = plugin.child_extensions(ChildSession("subagent", "coding"))[0]
    seen = []

    async def remote(self, operation, arguments):
        seen.append((self.target, operation))
        return "remote"

    monkeypatch.setattr(Transport, "run", remote)
    plugin.policy.level = type(plugin.policy.level)("full")
    assert await child.invoke("read", {"file_path": "x"}) == "remote"
    plugin.restore_child({"host": "other", "path": "/other"})
    assert child.target.host == "alias"
    plugin.policy.level = type(plugin.policy.level)("safe")
    with pytest.raises(PermissionError):
        await child.invoke("read", {"file_path": "x"})
    assert len(seen) == 1


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("explore", {"ssh__read", "ssh__glob", "ssh__grep"}),
        ("coding", {"ssh__read", "ssh__write_file", "ssh__edit", "ssh__bash"}),
        ("reasoning", set()),
    ],
)
async def test_fresh_profile_tools(plugin, profile, expected):
    first = plugin.child_extensions(ChildSession("subagent", profile))
    second = plugin.child_extensions(ChildSession("subagent", profile))
    tools = {}
    messages = []
    context = SimpleNamespace(
        tools=tools, register_tool=lambda tool: tools.update({tool.name: tool}), add_message=messages.append
    )
    for extension in first:
        await extension.on_tool(context)
        await extension.on_state(context)
    assert set(tools) == expected
    if expected:
        assert first[0] is not second[0]
        assert "SSH remote tools" in messages[0].content
    if profile == "explore":
        for operation in ("bash", "write_file", "edit"):
            with pytest.raises(PermissionError, match="child cannot use"):
                await first[0].invoke(operation, {})
    if profile == "reasoning":
        assert first == ()


class Writer:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


@pytest.fixture(autouse=True)
def fake_process_groups(monkeypatch):
    original = os.killpg
    processes = {}
    monkeypatch.setattr(Process, "instances", processes)

    def killpg(pid, signal):
        if pid in processes:
            processes[pid].kill()
        else:
            original(pid, signal)

    monkeypatch.setattr(os, "killpg", killpg)


class Process:
    instances: dict[int, Process] = {}

    def __init__(self, output=b'{"ok":true,"result":"remote"}', error=b"", code=0, hang=False):
        self.pid = 99999999 + len(self.instances)
        self.instances[self.pid] = self
        self.stdin = Writer()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.stderr.feed_data(error)
        if not hang:
            self.stdout.feed_eof()
            self.stderr.feed_eof()
        self.returncode = None if hang else code
        self.code = code
        self.killed = False
        self.waited = False
        self.finished = asyncio.Event()
        if not hang:
            self.finished.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        self.waited = True
        return self.returncode


async def test_subprocess_quoting_stdin_and_environment(monkeypatch):
    process = Process()
    seen = []

    async def spawn(*args, **kwargs):
        seen.append((args, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    target = Target("user@alias", "/srv/' 中文; $(nope)")
    with shell_environment({"ZETTCODE_PLUGIN_CHILD_STATE": "secret", "ZETTCODE_PLUGIN_ARGS": "secret", "KEEP": "yes"}):
        assert await Transport(target, persistent=False).run("read_file", {"file_path": "'; evil"}) == "remote"
    argv, options = seen[0]
    assert argv[:2] == ("ssh", "-T")
    assert "BatchMode=yes" in argv and "StrictHostKeyChecking=yes" in argv
    assert argv[-3:-1] == ("--", target.host)
    assert shlex.split(argv[-1])[:3] == ["python3", "-I", "-c"]
    assert target.path not in argv[-1] and "'; evil" not in argv[-1]
    assert "ZETTCODE_PLUGIN_CHILD_STATE" not in options["env"] and options["env"]["KEEP"] == "yes"
    assert "ZETTCODE_PLUGIN_ARGS" not in options["env"]
    request = json.loads(process.stdin.data)
    assert request["workspace"] == target.path and request["arguments"]["file_path"] == "'; evil"
    assert process.waited and process.stdin.closed


@pytest.mark.parametrize(
    "process,error",
    [
        (lambda: Process(error=b"host verification failed", code=255), "SSH failed"),
        (lambda: Process(output=b"login banner"), "Invalid SSH protocol"),
        (lambda: Process(output=b'{"ok":false,"error":"missing file"}'), "Remote operation failed"),
        (lambda: Process(output=b'{"ok":true}'), "Missing SSH protocol"),
        (lambda: Process(output=b"x" * (MAX_RESPONSE + 1)), "output limit"),
    ],
)
async def test_ssh_errors_are_reported_not_retried(plugin, monkeypatch, process, error):
    instance = process()

    async def spawn(*args, **kwargs):
        return instance

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    plugin.policy.level = type(plugin.policy.level)("full")
    plugin._transports[plugin.target] = Transport(plugin.target, persistent=False)
    with pytest.raises((ValueError, RuntimeError), match=error):
        await plugin.backend().tool("read_file").handler(file_path="file")
    assert instance.waited


async def test_timeout_kills_and_reaps_ssh(monkeypatch):
    process = Process(hang=True)
    original = asyncio.wait_for

    async def spawn(*args, **kwargs):
        return process

    async def short(awaitable, timeout):
        return await original(awaitable, 0.01)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(asyncio, "wait_for", short)
    with pytest.raises(asyncio.TimeoutError):
        await Transport(Target("alias", "/tmp"), persistent=False).run("read_file", {"file_path": "file"})
    assert process.killed and process.waited


async def test_cancellation_kills_and_reaps_ssh(monkeypatch):
    process = Process(hang=True)
    started = asyncio.Event()

    async def spawn(*args, **kwargs):
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        Transport(Target("alias", "/tmp"), persistent=False).run("read_file", {"file_path": "file"})
    )
    await started.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited


async def test_bounded_stream():
    stream = asyncio.StreamReader()
    stream.feed_data(b"12345")
    stream.feed_eof()
    with pytest.raises(ValueError):
        await bounded(stream, 4)


def test_package_metadata():
    from importlib.metadata import distribution

    package = distribution("zettcode-ssh")
    assert package.version == __version__ == "0.5.2"
    assert [(point.name, point.value) for point in package.entry_points] == [("ssh", "zettcode.ssh:SSHPlugin")]
    assert any(line.startswith("zettcode-plugin-api") for line in package.requires)


def test_restore_before_activation_and_malformed_config(tmp_path):
    from zettcode.plugin_api import ModelConfig, ZettCodeConfig

    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="fake", token="test"),),
        store=tmp_path / "store",
        plugin_settings={"ssh": {"host": "configured", "path": "/configured"}},
    )
    plugin = SSHPlugin()
    plugin.restore_child({"host": "inherited", "path": "/inherited"})
    context = PluginContext(config, {POLICY: ShellPolicy()}, name="ssh")
    plugin.activate(context)
    assert plugin.target == Target("inherited", "/inherited")
    assert not context.commands.commands  # No VS Code/server slash command; terminal panel only.
    for settings in (
        {"host": "alone"},
        {"host": 3, "path": "/tmp"},
        {"path": "relative", "host": "alias"},
        {"unknown": True},
    ):
        config = replace(config, plugin_settings={"ssh": settings})
        with pytest.raises(ValueError):
            SSHPlugin().activate(PluginContext(config, {POLICY: ShellPolicy()}, name="ssh"))


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")
async def test_framework_remote_and_local_reads_sit_beside_each_other(tmp_path, monkeypatch, fake_ssh):
    from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
    from zettcode.engine.plugins import load_plugins
    from zettcode.sdk.builtins import AGENT_PLUGINS
    from zettcode.sdk.client import Client

    _, remote = fake_ssh
    (remote / "file").write_text("REMOTE\n", encoding="utf-8")

    def plugins(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin], entry_points=())

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", plugins)
    model = wire(
        monkeypatch,
        ScriptedModel(
            asks_for(call("ssh__read_file", {"file_path": "file"}), call("read_file", {"file_path": "file"})),
            "done",
        ),
    )
    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": str(remote)}})
    (config.workspace / "file").write_text("LOCAL\n", encoding="utf-8")
    async with Client(config=config, permission="full") as client:
        async with client.prompt("read both") as run:
            async for _ in run:
                pass
    results = [item for item in model.requests[-1].messages if isinstance(item, ToolMessage)]
    by_name = {item.name: item.content for item in results}
    assert by_name["ssh__read_file"] == "1\tREMOTE\n"
    assert by_name["read_file"] == "1\tLOCAL\n", "the local tool was not replaced"
    offered = {tool.name for tool in model.requests[0].tools}
    assert {"read_file", "ssh__read_file", "bash", "ssh__bash"} <= offered
    assert any(
        "SSH remote tools" in item.content for item in model.requests[-1].messages if isinstance(item, SystemMessage)
    )


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")
@pytest.mark.parametrize("profile", ["explore", "coding", "reasoning"])
async def test_framework_child_tools_and_instructions(tmp_path, monkeypatch, plugin, profile):
    from sdk_helpers import ScriptedModel
    from zettcode.engine.extensions.capabilities import ModelCapabilities
    from zettcode.engine.extensions.subagents import subagent_extension
    from zettcode.engine.storage import SessionStore
    from zettcode.sdk.builtins import _shared_with_children

    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("LOCAL_SENTINEL", encoding="utf-8")
    model = ScriptedModel("child done")
    store = SessionStore(tmp_path / "store", tmp_path)
    extension = subagent_extension(
        model=model,
        persistence=store,
        capabilities=ModelCapabilities({}),
        workspace=tmp_path,
        shares=_shared_with_children(messaging=False),
        child_extensions=plugin.child_extensions,
    )
    from sdk_helpers import asks_for, call

    model.steps = [
        asks_for(call("task", {"description": "child", "prompt": "work", "subagent_type": profile})),
        "child done",
        "parent done",
    ]
    parent = await Agent.create(model, config=AgentRunConfig(session_id="parent"), extensions=[extension])
    async for _ in parent.stream("delegate"):
        pass
    child_request = model.requests[1]
    names = {tool.name for tool in child_request.tools}
    remote_read = {"ssh__read", "ssh__glob", "ssh__grep"}
    remote_write = {"ssh__write_file", "ssh__edit", "ssh__bash"}
    if profile == "reasoning":
        assert not (remote_read | remote_write) & names
    elif profile == "explore":
        assert remote_read <= names and not remote_write & names
        assert "read" in names, "the child's own local tools are still there"
    else:
        assert ({"ssh__read"} | remote_write) <= names
        assert "ssh__glob" not in names and "ssh__grep" not in names, "coding searches with its shell, as locally"
        # This synthetic parent was built without the local bundle, so the child has none to inherit; a real
        # parent's own tools are kept, pinned by test_runtime_review.py's actual-client test.
    system = "\n".join(item.content for item in child_request.messages if isinstance(item, SystemMessage))
    if profile != "reasoning":
        assert "SSH remote tools" in system and "still work on this machine" in system
    await store.close()


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")
async def test_a_daemon_that_inherited_the_target_gets_the_remote_tools(tmp_path, monkeypatch):
    """The state a daemon restores is the target; the tools it then offers are the ssh__ ones."""
    from sdk_helpers import ScriptedModel, config_for, wire
    from zettcode.engine.plugins import load_plugins
    from zettcode.plugin_api import CHILD_STATE
    from zettcode.sdk.builtins import AGENT_PLUGINS
    from zettcode.sdk.client import Client

    def plugins(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin], entry_points=())

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", plugins)
    model = wire(monkeypatch, ScriptedModel("done"))
    state = {"ssh": {"host": "alias", "path": "/remote", "user": None, "auth": "key"}}
    config = config_for(tmp_path)
    async with Client(config=config, permission="full", shared={CHILD_STATE: state}) as client:
        async with client.prompt("what tools do you have") as run:
            async for _ in run:
                pass
    offered = {tool.name for tool in model.requests[0].tools}
    assert {"ssh__read_file", "ssh__bash", "ssh__edit"} <= offered
    assert "ssh__read" not in offered, "the configured model is text-only, so the picture reader is not offered"
    assert {"read_file", "bash"} <= offered, "the daemon's own local tools are untouched"
    plugin = next(item for item in client._agent.runtime.plugins.plugins if item.name == "ssh")
    assert plugin.target == Target("alias", "/remote")


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")
async def test_a_multimodal_model_is_offered_the_remote_picture_reader(tmp_path, monkeypatch):
    from sdk_helpers import ScriptedModel, config_for, models, wire
    from zettcode.engine.plugins import load_plugins
    from zettcode.plugin_api import CHILD_STATE
    from zettcode.sdk.builtins import AGENT_PLUGINS
    from zettcode.sdk.client import Client

    def plugins(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin], entry_points=())

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", plugins)
    model = wire(monkeypatch, ScriptedModel("done"))
    state = {"ssh": {"host": "alias", "path": "/remote", "user": None, "auth": "key"}}
    config = config_for(tmp_path, models=models("scripted", multimodal=True))
    async with Client(config=config, permission="full", shared={CHILD_STATE: state}) as client:
        async with client.prompt("what tools do you have") as run:
            async for _ in run:
                pass
    offered = {tool.name for tool in model.requests[0].tools}
    assert "ssh__read" in offered and "ssh__read_file" not in offered, "one reader, not both"
    prompt = " ".join(str(item.content) for item in model.requests[0].messages)
    assert "ssh__read" in prompt


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")
async def test_active_client_spawn_exports_current_ssh_target(tmp_path, monkeypatch):
    from sdk_helpers import config_for
    from zettcode.engine.plugins import load_plugins
    from zettcode.sdk.builtins import AGENT_PLUGINS
    from zettcode.sdk.client import Client

    def plugins(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin], entry_points=())

    seen = []

    async def spawn(workspace, **options):
        seen.append(options["plugin_state"])
        return "spawned"

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", plugins)
    monkeypatch.setattr("zettcode.sdk.daemons.spawn_daemon", spawn)
    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": "/remote"}})
    async with Client(config=config) as client:
        assert await client.spawn_daemon(name="worker") == "spawned"
        plugin = next(item for item in client._agent.runtime.plugins.plugins if item.name == "ssh")
        plugin.restore_child({"host": "other", "path": "/changed"})
        await client.spawn_daemon(name="second")
        await plugin.aclose()
        plugin.target = None
        await client.spawn_daemon(name="local")
    assert seen == [
        {"ssh": {"host": "alias", "path": "/remote", "user": None, "auth": "key"}},
        {"ssh": {"host": "other", "path": "/changed", "user": None, "auth": "key"}},
        {},
    ]
