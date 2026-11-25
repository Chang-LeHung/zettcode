"""Exercise the actual client and task lifecycle: the ssh__ tools are added, local ones are untouched."""

from __future__ import annotations

import importlib.util

import pytest
from zett_agent.messages import ToolMessage

from zettcode.ssh import SSHPlugin
from zettcode.ssh.transport import Transport

pytestmark = pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout SDK integration")


@pytest.fixture
def clients(monkeypatch):
    from zettcode.engine.plugins import load_plugins
    from zettcode.sdk.builtins import AGENT_PLUGINS

    def load(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin], entry_points=())

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)


@pytest.mark.parametrize("profile", ["explore", "coding", "reasoning"])
async def test_actual_task_remote_tool_calls(tmp_path, monkeypatch, clients, profile):
    from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
    from zettcode.sdk.client import Client

    seen = []

    async def remote(self, operation, arguments):
        seen.append((self.target.host, self.target.path, operation, arguments))
        return "REMOTE_SENTINEL"

    monkeypatch.setattr(Transport, "run", remote)
    task = asks_for(call("task", {"description": "review", "prompt": "operate", "subagent_type": profile}))
    tools = [call("ssh__read_file", {"file_path": "file"})]
    if profile == "coding":
        tools.extend(
            [
                call("ssh__write_file", {"file_path": "file", "content": "remote"}),
                call("ssh__bash", {"command": "pwd"}),
            ]
        )
    model = wire(
        monkeypatch,
        ScriptedModel(task, *([asks_for(*tools)] if profile != "reasoning" else []), "child done", "parent done"),
    )
    config = config_for(tmp_path, subagent_enabled=True, plugin_settings={"ssh": {"host": "alias", "path": "/remote"}})
    local = config.workspace / "file"
    local.write_text("LOCAL_SENTINEL", encoding="utf-8")
    async with Client(config=config, permission="full") as client:
        async with client.prompt("delegate") as run:
            async for _ in run:
                pass
    assert local.read_text(encoding="utf-8") == "LOCAL_SENTINEL"
    assert [item[2] for item in seen] == (
        ["read_file", "write_file", "bash"] if profile == "coding" else ["read_file"] if profile == "explore" else []
    )
    assert all(item[:2] == ("alias", "/remote") for item in seen)
    child_tools = {tool.name for tool in model.requests[1].tools}
    if profile == "reasoning":
        assert (
            not {
                "ssh__read",
                "ssh__read_file",
                "ssh__glob",
                "ssh__grep",
                "ssh__bash",
                "ssh__edit",
                "ssh__write_file",
            }
            & child_tools
        )
    elif profile == "explore":
        assert "ssh__read_file" in child_tools
        assert not {"ssh__bash", "ssh__write_file", "ssh__edit"} & child_tools
        # The local coding tools are still the child's own; nothing was replaced.
        assert "read_file" in child_tools
    else:
        assert {"ssh__read_file", "ssh__bash", "ssh__write_file"} <= child_tools
        assert "bash" in child_tools and "read_file" in child_tools
    if seen:
        results = [item for item in model.requests[2].messages if isinstance(item, ToolMessage)]
        assert results and all(item.success and item.content == "REMOTE_SENTINEL" for item in results)


async def test_local_tools_stay_local_beside_the_remote_ones(tmp_path, monkeypatch, clients):
    """Asking for read_file reads this machine; ssh__read_file reaches the host; the parent's tools both exist."""
    from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
    from zettcode.sdk.client import Client

    calls = []

    async def remote(self, operation, arguments):
        calls.append(operation)
        return "REMOTE"

    monkeypatch.setattr(Transport, "run", remote)
    model = wire(
        monkeypatch,
        ScriptedModel(asks_for(call("read_file", {"file_path": "local.txt"})), "done"),
    )
    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": "/remote"}})
    (config.workspace / "local.txt").write_text("LOCAL\n", encoding="utf-8")
    async with Client(config=config, permission="full") as client:
        names = {tool.name for tool in client.tools} if hasattr(client, "tools") else set()
        async with client.prompt("read") as run:
            async for _ in run:
                pass
    result = next(item for item in model.requests[-1].messages if isinstance(item, ToolMessage))
    assert result.content == "1\tLOCAL\n"
    assert calls == [], "a local tool call never reaches the SSH host"
    offered = {tool.name for tool in model.requests[0].tools}
    assert {"read_file", "ssh__read_file"} <= offered
    assert names == set() or {"read_file", "ssh__read_file"} <= names


async def test_invalid_config_reports_the_plugin_and_keeps_local_tools(tmp_path, monkeypatch, clients):
    """Nothing local is replaced, so a broken SSH configuration must not stop the program from starting."""
    from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
    from zettcode.sdk.client import Client

    model = wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"file_path": "file"})), "done"))
    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": "relative"}})
    (config.workspace / "file").write_text("LOCAL\n", encoding="utf-8")
    async with Client(config=config, permission="full") as client:
        failures = dict(client._agent.runtime.plugins.failed)
        assert any("ssh" in name for name in failures), failures
        async with client.prompt("read") as run:
            async for _ in run:
                pass
    result = next(item for item in model.requests[-1].messages if isinstance(item, ToolMessage))
    assert result.content == "1\tLOCAL\n"


async def test_local_harness_tools_keep_working(tmp_path, monkeypatch, clients):
    """The local just-in-time tools are the machine's own; SSH adds tools, it does not take them away."""
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.tools.base import tool

    from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
    from zettcode.sdk.client import Client

    ran = []

    @tool
    def repo_create() -> str:
        """Simulate a local harness management tool.

        Guidelines:
            - Test only.
        """
        ran.append(True)
        return "local"

    class HarnessTools(AgentExtension):
        async def on_tool(self, context):
            context.register_tool(repo_create)

    model = wire(monkeypatch, ScriptedModel(asks_for(call("repo_create", {})), "done"))
    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": "/remote"}})
    from zettcode.engine.plugins import load_plugins
    from zettcode.plugin_api import Plugin
    from zettcode.sdk.builtins import AGENT_PLUGINS

    class HarnessPlugin(Plugin):
        name = "review-harness"

        def activate(self, ctx):
            ctx.agent.register_extension(HarnessTools())

    monkeypatch.setattr(
        "zettcode.sdk.builtins.load_agent_plugins",
        lambda config, shared: load_plugins(
            config, shared=shared, builtins=[*AGENT_PLUGINS, SSHPlugin, HarnessPlugin], entry_points=()
        ),
    )
    async with Client(config=config, permission="full") as client:
        async with client.prompt("harness") as run:
            async for _ in run:
                pass
    assert ran == [True]
    result = next(item for item in model.requests[-1].messages if isinstance(item, ToolMessage))
    assert result.success and result.content == "local"
