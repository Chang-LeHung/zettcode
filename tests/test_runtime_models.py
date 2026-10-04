"""Model switching uses the configured OpenAI-compatible endpoint per request."""

from datetime import UTC, datetime, timedelta

import pytest
from zett_agent import McpExtension, SkillExtension, UserMessage

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.storage import SessionStore
from zettcode.config import ModelConfig, ZettCodeConfig


def test_the_system_prompt_head_changes_only_by_the_day(tmp_path):
    """The prompt head is part of the provider's cache key.

    A clock reading with seconds would make it unique to every launch, which
    drops the cache for the whole conversation; the day keeps the head reusable
    while still telling the model what today is.
    """
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    morning = datetime(2026, 10, 4, 9, 15, 3, tzinfo=UTC)
    late = datetime(2026, 10, 4, 23, 59, 59, tzinfo=UTC)

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
    from zett_agent import McpExtension

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
        return object()

    monkeypatch.setattr(runtime_module, "OpenAIProvider", FakeProvider)
    monkeypatch.setattr(runtime_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    # A developer's own ~/.zettcode/mcp.json must not decide what this test sees.
    monkeypatch.setattr(runtime_module, "DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")
    first = ModelConfig(model="shared-id", display_model="First", token="first", base_url="http://first.test")
    second = ModelConfig(model="shared-id", display_model="Second", token="second", base_url="http://tds.com:8787")
    config = ZettCodeConfig(workspace=tmp_path, models=(first, second), store=tmp_path / "sessions")
    await SessionStore(config.store, config.workspace).append(
        "existing-session", "old-request", UserMessage(content="earlier")
    )

    runtime = await runtime_module.ZettCodeRuntime.create(config)
    assert runtime.session_id != "existing-session"
    assert captured["config"].session_id == runtime.session_id
    assert runtime.active_model is first
    assert captured["model"] is created[0]
    assert captured["extensions"][-1].model is None
    assert any(isinstance(extension, SkillExtension) for extension in captured["extensions"])
    assert not any(isinstance(extension, McpExtension) for extension in captured["extensions"])

    selected = runtime.use_model("Second")
    assert selected is second
    assert runtime.model is created[1]
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
