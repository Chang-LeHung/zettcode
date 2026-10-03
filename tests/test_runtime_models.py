"""Model switching uses the configured OpenAI-compatible endpoint per request."""

from datetime import UTC, datetime, timedelta

import pytest
from zett_agent import UserMessage

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
