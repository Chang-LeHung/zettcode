"""The models plugin: which keys it notices, and the official models each one offers."""

from __future__ import annotations

import pytest

from zettcode.models import VENDORS, ModelsPlugin
from zettcode.plugin_api import ModelConfig, PluginContext, ZettCodeConfig

ALL_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "ZAI_API_KEY",
    "ZHIPUAI_API_KEY",
    "ZHIPU_API_KEY",
    "MOONSHOT_API_KEY",
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ALL_ENV:
        monkeypatch.delenv(variable, raising=False)


def _context(tmp_path) -> PluginContext:
    config = ZettCodeConfig(
        workspace=tmp_path, store=tmp_path / "sessions", models=(), harness_dir=tmp_path / "harness"
    )
    return PluginContext(config)


def test_the_plugin_is_on_until_the_reader_turns_it_off():
    """A key in the environment is enough for the vendor to be offered: the first run needs no enabling."""
    assert ModelsPlugin.default_enabled() is True


def test_a_key_registers_its_host_and_its_official_models(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    (provider,) = ctx.providers
    assert (provider.name, provider.label, provider.token_env) == ("openai", "OpenAI", "OPENAI_API_KEY")
    assert provider.api == "responses"
    assert [(model.model, model.shown_name) for model in provider.models] == [
        ("gpt-6.2-astra", "GPT-6.2 Astra"),
        ("gpt-6.2-sol", "GPT-6.2 Sol"),
    ]
    assert provider.multimodal is True
    assert all(model.context_window == 1_050_000 and model.multimodal is None for model in provider.models)


def test_every_vendor_with_a_key_is_registered(tmp_path, monkeypatch):
    _clear(monkeypatch)
    for variable in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "ZAI_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.setenv(variable, "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    assert [provider.name for provider in ctx.providers] == ["openai", "anthropic", "deepseek", "zai", "moonshot"]
    assert next(provider for provider in ctx.providers if provider.name == "anthropic").models[0].model == (
        "claude-opus-5-5"
    )


def test_no_key_registers_nothing(tmp_path, monkeypatch):
    _clear(monkeypatch)
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    assert ctx.providers == ()


def test_zai_accepts_its_older_variable_and_keeps_the_one_it_found(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ZHIPUAI_API_KEY", "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    (provider,) = ctx.providers
    assert provider.name == "zai" and provider.token_env == "ZHIPUAI_API_KEY"
    assert provider.models[0].model == "glm-5.3"


def test_each_vendor_names_a_model_and_an_address():
    assert {vendor.name for vendor in VENDORS} == {"openai", "anthropic", "deepseek", "zai", "moonshot"}
    assert all(vendor.models and vendor.base_url.startswith("https://") for vendor in VENDORS)
    assert all(model.model and model.display for vendor in VENDORS for model in vendor.models)


def test_the_deepseek_ids_are_the_ones_its_endpoint_accepts():
    """``deepseek-v4.1-flash`` was the display name, and a request on it answered 400.

    The vendor's own ``/models`` lists ``deepseek-flash`` (named ``DeepSeek-V4.1-Flash``) and ``deepseek-v4-pro``
    (named ``DeepSeek-V4-Pro``), both with a 1,048,576-token window; the Flash takes images and the Pro takes text
    only. Their Messages endpoint is where the host serves its hosted tools, and the protocol this plugin was asked
    to use for it by default.
    """
    (deepseek,) = [vendor for vendor in VENDORS if vendor.name == "deepseek"]
    flash, pro = deepseek.models

    assert (deepseek.api, deepseek.base_url) == ("anthropic", "https://api.deepseek.com/anthropic")
    assert deepseek.multimodal is True
    assert (flash.model, flash.display) == ("deepseek-flash", "DeepSeek V4.1 Flash")
    assert (flash.context_window, flash.multimodal) == (1_048_576, None)
    assert (pro.model, pro.display) == ("deepseek-v4-pro", "DeepSeek V4 Pro")
    assert (pro.context_window, pro.multimodal) == (1_048_576, False)


def test_anthropic_offers_opus_and_sonnet(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    (provider,) = ctx.providers
    assert [(model.model, model.shown_name) for model in provider.models] == [
        ("claude-opus-5-5", "Claude Opus 5.5"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ]
    assert provider.multimodal is True
    assert all(model.context_window == 1_000_000 and model.multimodal is None for model in provider.models)


def test_kimi_is_reached_through_its_anthropic_compatible_endpoint(tmp_path, monkeypatch):
    """Kimi documents ``https://api.moonshot.ai/anthropic`` for Claude Code, so the host speaks Messages."""
    _clear(monkeypatch)
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    (provider,) = ctx.providers
    assert (provider.name, provider.label, provider.token_env) == ("moonshot", "Moonshot AI", "MOONSHOT_API_KEY")
    assert (provider.api, provider.base_url) == ("anthropic", "https://api.moonshot.ai/anthropic")
    assert [(model.model, model.shown_name) for model in provider.models] == [
        ("kimi-k3.1-pro", "Kimi K3.1 Pro"),
        ("kimi-k3", "Kimi K3"),
    ]
    assert provider.multimodal is True
    assert all(model.context_window == 1_048_576 and model.multimodal is None for model in provider.models)


def test_a_name_the_reader_already_uses_leaves_that_vendor_out(tmp_path, monkeypatch):
    """The plugin is on by default, so a conflict is the reader's entry winning, not a plugin that failed."""
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="mine", display_model="GPT-6.2 Astra"),),
        harness_dir=tmp_path / "harness",
    )
    ctx = PluginContext(config)

    ModelsPlugin().activate(ctx)

    assert ctx.providers == ()


def test_a_clash_on_the_second_model_leaves_the_whole_vendor_out(tmp_path, monkeypatch):
    """The host is registered with all its models at once, so one name it cannot have costs it the others too."""
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="mine", display_model="GPT-6.2 Sol"),),
        harness_dir=tmp_path / "harness",
    )
    ctx = PluginContext(config)

    ModelsPlugin().activate(ctx)

    assert ctx.providers == ()


def test_a_conflicting_vendor_does_not_cost_the_others(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="one", display_model="GPT-6.2 Astra"),),
        harness_dir=tmp_path / "harness",
    )
    ctx = PluginContext(config)

    ModelsPlugin().activate(ctx)

    assert [provider.name for provider in ctx.providers] == ["anthropic"]


def test_the_table_is_internally_consistent():
    models = [model for vendor in VENDORS for model in vendor.models]
    assert len({model.display for model in models}) == len(models)
    assert all(model.display and model.context_window > 0 for model in models)
    assert all(len({model.model for model in vendor.models}) == len(vendor.models) for vendor in VENDORS)
