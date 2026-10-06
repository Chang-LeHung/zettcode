"""Model switching uses the configured OpenAI-compatible endpoint per request."""

import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from zett_agent.extensions.mcp import McpExtension
from zett_agent.extensions.skill import SkillExtension
from zett_agent.messages import UserMessage

from zettcode._compat import ExceptionGroup
from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.compaction import OnDemandCompaction
from zettcode.app.agent.storage import SessionStore
from zettcode.config import ModelConfig, ZettCodeConfig


def test_the_system_prompt_head_changes_only_by_the_day(tmp_path):
    """The prompt head is part of the provider's cache key.

    A clock reading with seconds would make it unique to every launch, which
    drops the cache for the whole conversation; the day keeps the head reusable
    while still telling the model what today is.
    """
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    morning = datetime(2026, 10, 4, 9, 15, 3, tzinfo=timezone.utc)
    late = datetime(2026, 10, 4, 23, 59, 59, tzinfo=timezone.utc)

    prompt = runtime_module.build_system_prompt(config, now=morning)

    assert "- Today: 2026-10-04" in prompt
    assert prompt == runtime_module.build_system_prompt(config, now=late)
    assert prompt != runtime_module.build_system_prompt(config, now=late + timedelta(days=1))


def _config_with(tmp_path, **changes) -> ZettCodeConfig:
    """Return a minimal config, with one workspace-local change applied.

    The MCP file defaults to one that does not exist, so a developer's own
    ``~/.zettcode/mcp.json`` cannot decide what a test sees.
    """
    defaults = {"mcp_config": tmp_path / "absent-mcp.json", **changes}
    return ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        **defaults,
    )


def test_configured_skill_roots_are_discovered_and_advertised(tmp_path):
    skill = tmp_path / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review a diff with the team checklist\n---\n\nRead the diff twice.\n",
        encoding="utf-8",
    )

    config = _config_with(tmp_path, skill_roots=(tmp_path / "skills",))
    (extension,) = runtime_module.integration_extensions(config)

    assert isinstance(extension, SkillExtension)
    catalog = {item.name: item for item in extension.skills}
    assert catalog["review"].description == "Review a diff with the team checklist"
    assert catalog["review"].path == (skill / "SKILL.md").resolve()


def test_mcp_is_loaded_only_when_a_server_file_exists(tmp_path):
    servers = tmp_path / "mcp.json"
    servers.write_text(
        '{"servers": {"docs": {"type": "streamable-http", "url": "http://127.0.0.1:9/mcp"}}}',
        encoding="utf-8",
    )

    loaded = runtime_module.integration_extensions(_config_with(tmp_path, mcp_config=servers))
    missing = runtime_module.integration_extensions(_config_with(tmp_path, mcp_config=tmp_path / "absent.json"))

    assert [isinstance(extension, McpExtension) for extension in loaded] == [False, True]
    assert isinstance(loaded[0], SkillExtension)
    assert [server.name for server in loaded[1].servers] == ["docs"]
    # With no server file there is nothing to load, so no MCP instructions are
    # added to the request at all.
    assert all(isinstance(extension, SkillExtension) for extension in missing)


def test_skills_and_mcp_can_be_disabled(tmp_path):
    servers = tmp_path / "mcp.json"
    servers.write_text('{"servers": {}}', encoding="utf-8")

    extensions = runtime_module.integration_extensions(
        _config_with(tmp_path, skills_enabled=False, mcp_enabled=False, mcp_config=servers)
    )

    assert extensions == ()


def test_the_runtime_module_costs_nothing_until_it_starts(tmp_path):
    """The provider and MCP SDKs must not be in the import graph the shell pays for."""
    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "import zettcode.app.agent.runtime as runtime_module",
            "from zettcode.config import ModelConfig, ZettCodeConfig",
            "config = ZettCodeConfig(",
            "    workspace=Path(sys.argv[1]),",
            "    models=(ModelConfig(model='m', token='t'),),",
            "    store=Path(sys.argv[1]),",
            ")",
            "runtime_module.ZettCodeRuntime.preview(config)",
            "print(*(name in sys.modules for name in ('openai', 'mcp')))",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


async def test_a_preview_runtime_starts_once_and_only_then(tmp_path, monkeypatch):
    """The shell paints from the preview; the provider appears on the first turn."""
    created: list[object] = []

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.closed = False
            created.append(self)

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)

    runtime = runtime_module.ZettCodeRuntime.preview(_config_with(tmp_path))

    assert runtime.client is None and runtime.model is None
    # Compaction is armed from the preview: the budget belongs to the model, so
    # `/compact` has a threshold to force past even before the first turn.
    assert runtime.compaction.max_tokens == 102_400
    with pytest.raises(RuntimeError, match="has not started"):
        _ = runtime.provider
    assert created == []

    first = runtime.start()
    assert runtime.start() is first
    await first

    assert len(created) == 1
    assert runtime.started is runtime.client
    assert runtime.provider is created[0]
    await runtime.aclose()
    assert created[0].closed is True


async def test_a_text_only_model_is_not_offered_the_image_tool():
    """`view_image` reads a picture; a model that cannot take one is not offered it."""
    from zett_agent.agent import Agent, AgentRunConfig
    from zett_agent.events import AgentEventType
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.extensions.coding import CodingExtension
    from zett_agent.messages import AssistantMessage
    from zett_agent.model import ModelEvent, ModelResponse, RetryOptions
    from zett_agent.tools.images import view_image

    from zettcode.app.agent.capabilities import ModelCapabilities

    class Context:
        """The two things the filter reads."""

        def __init__(self, model: object) -> None:
            self.model = model
            self.tools = {view_image.name: view_image, "read_file": object()}

    text_only = ModelConfig(model="text", token="t")
    takes_images = ModelConfig(model="vision", token="t", multimodal=True)

    class Model:
        retry = RetryOptions(max_retries=0)

        async def stream(self, request):
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))

    model = Model()
    providers = {text_only: model, takes_images: object()}
    capabilities = ModelCapabilities(providers)

    gated = Context(providers[text_only])
    await capabilities.on_tool(gated)
    assert view_image.name not in gated.tools and "read_file" in gated.tools

    allowed = Context(providers[takes_images])
    await capabilities.on_tool(allowed)
    assert view_image.name in allowed.tools

    # A request whose model this runtime did not build keeps the tools it has.
    unknown = Context(object())
    await capabilities.on_tool(unknown)
    assert view_image.name in unknown.tools

    # Through the real hooks the filter runs after the bundle that registers the
    # tool, which is the ordering the whole thing depends on.
    class Probe(AgentExtension):
        priority = 200

        def __init__(self) -> None:
            self.offered: list[list[str]] = []

        async def on_tool(self, context) -> None:
            self.offered.append(sorted(context.tools))

    probe = Probe()
    agent = await Agent.create(
        model,
        config=AgentRunConfig(session_id="test"),
        extensions=[CodingExtension(), capabilities, probe],
    )

    streamed = [event async for event in agent.stream("hello", config=AgentRunConfig(session_id="test"))]

    assert streamed[-1].type is AgentEventType.RUN_COMPLETED
    assert view_image.name not in probe.offered[0]
    assert "read_file" in probe.offered[0]


async def test_the_approval_memory_remembers_exact_commands_for_the_run():
    """The prompt promises one exact command for this run, not an allowlist."""
    from zett_agent.extensions.shell_approval import ShellApprovalMode

    from zettcode.app.agent.approval import ShellApprovalMemory

    memory = ShellApprovalMemory()

    assert await memory.get_session_mode("session-1") is ShellApprovalMode.REVIEW
    assert await memory.is_allowed("session-1", "rm -rf build") is False

    await memory.set_session_mode("session-1", ShellApprovalMode.ALLOW_ALL)
    await memory.allow_command("rm -rf build")

    assert await memory.get_session_mode("session-1") is ShellApprovalMode.ALLOW_ALL
    assert await memory.is_allowed("session-1", "rm -rf build") is True
    assert await memory.is_allowed("session-1", "rm -rf dist") is False
    # The policy is per session, and clearing it reviews again.
    assert await memory.get_session_mode("session-2") is ShellApprovalMode.REVIEW
    await memory.clear_session_mode("session-1")
    assert await memory.get_session_mode("session-1") is ShellApprovalMode.REVIEW


def test_error_reasons_are_unwrapped_from_their_groups_and_deduplicated():
    """A task-group failure says nothing; the reasons are its leaves."""
    grouped = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [
            ExceptionGroup("unhandled errors in a TaskGroup", [ConnectionError("All connection attempts failed")]),
            ConnectionError("All connection attempts failed"),
            ValueError("bad config"),
            KeyError("silent"),
        ],
    )

    assert runtime_module.describe_error(grouped) == "All connection attempts failed; bad config; 'silent'"
    assert runtime_module.describe_error(ValueError("plain")) == "plain"


async def test_a_dead_mcp_server_is_named_in_the_failure(tmp_path, monkeypatch):
    from zett_agent.extensions.mcp import McpExtension

    servers = tmp_path / "mcp.json"
    servers.write_text(
        '{"servers": {"docs": {"type": "streamable-http", "url": "http://127.0.0.1:1/mcp"}}}',
        encoding="utf-8",
    )
    config = _config_with(tmp_path, skills_enabled=False, mcp_config=servers)
    (extension,) = runtime_module.integration_extensions(config)

    async def failing(self, context):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [ConnectionError("All connection attempts failed")])

    monkeypatch.setattr(McpExtension, "on_tool", failing)

    with pytest.raises(RuntimeError, match=r"MCP unavailable \(docs\): All connection attempts failed"):
        await extension.on_tool(object())


async def test_runtime_switches_models_and_closes_every_provider(tmp_path, monkeypatch):
    created = []
    captured = {}

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.model = model
            self.token = token
            self.base_url = base_url
            self.response = response
            self.closed = False
            created.append(self)

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return type("FakeClient", (), {"event_dispatcher": None})()

    # The provider and the client are imported when the runtime starts, so the
    # doubles replace them where that import reads from.
    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    # A developer's own ~/.zettcode/mcp.json must not decide what this test sees.
    monkeypatch.setattr(runtime_module, "DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")
    first = ModelConfig(model="shared-id", display_model="First", token="first", base_url="http://first.test")
    second = ModelConfig(
        model="shared-id",
        display_model="Second",
        token="second",
        base_url="http://tds.com:8787",
        context_window=200_000,
        compact_percent=75,
    )
    config = ZettCodeConfig(workspace=tmp_path, models=(first, second), store=tmp_path / "sessions")
    await SessionStore(config.store, config.workspace).append(
        "existing-session", "old-request", UserMessage(content="earlier")
    )

    runtime = await runtime_module.ZettCodeRuntime.create(config)
    assert runtime.session_id != "existing-session"
    assert captured["config"].session_id == runtime.session_id
    assert runtime.active_model is first
    assert captured["model"] is created[0]
    compaction = next(extension for extension in captured["extensions"] if isinstance(extension, OnDemandCompaction))
    assert compaction.model is None
    assert any(isinstance(extension, SkillExtension) for extension in captured["extensions"])
    assert not any(isinstance(extension, McpExtension) for extension in captured["extensions"])
    # The tool list follows the model, so the capability filter is part of the run.
    from zettcode.app.agent.capabilities import ModelCapabilities

    assert any(isinstance(extension, ModelCapabilities) for extension in captured["extensions"])
    # The prompt can offer "always allow" only because the runtime hands the
    # extension something to remember the command in.
    assert runtime.approval.storage is not None

    selected = runtime.use_model("Second")
    assert selected is second
    assert runtime.model is created[1]
    # The compaction budget belongs to the model, so it moves with the choice.
    assert runtime.compaction.max_tokens == second.compaction_max_tokens == 150_000
    assert runtime.compaction.keep_recent_tokens == second.compaction_keep_tokens == 37_500
    assert created[1].base_url == "http://tds.com:8787"
    assert created[1].token == "second"
    assert runtime.use_model("First") is first
    assert runtime.model is created[0]
    assert len(created) == 2

    with pytest.raises(ValueError, match="Ambiguous model"):
        runtime.use_model("shared-id")
    assert runtime.active_model is first
    assert runtime.use_model(second) is second
    assert runtime.model is created[1]
    with pytest.raises(ValueError, match="Unknown model"):
        runtime.use_model("missing")
    assert runtime.active_model is second

    await runtime.aclose()
    assert all(provider.closed for provider in created)
