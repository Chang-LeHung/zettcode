"""Exercise the actual client/task lifecycle, not just child factories."""

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
    tools = [call("read_file", {"file_path": "file"})]
    if profile == "coding":
        tools.extend([call("write_file", {"file_path": "file", "content": "remote"}), call("bash", {"command": "pwd"})])
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
        assert not child_tools
    elif profile == "explore":
        assert "read_file" in child_tools and not {"bash", "write_file", "edit"} & child_tools
    if seen:
        results = [item for item in model.requests[2].messages if isinstance(item, ToolMessage)]
        assert results and all(item.success and item.content == "REMOTE_SENTINEL" for item in results)


async def test_invalid_config_is_fatal_not_local_fallback(tmp_path, clients):
    from sdk_helpers import config_for
    from zettcode.sdk.client import Client

    config = config_for(tmp_path, plugin_settings={"ssh": {"host": "alias", "path": "relative"}})
    with pytest.raises(ValueError, match="fail-closed plugin.*ssh"):
        Client(config=config, permission="full")


async def test_parent_jit_management_cannot_run_locally(tmp_path, monkeypatch, clients):
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
    assert not ran
    result = next(item for item in model.requests[-1].messages if isinstance(item, ToolMessage))
    assert "repo_create" not in {tool.name for tool in model.requests[0].tools}
    assert not result.success and "Unknown tool: repo_create" in result.content
