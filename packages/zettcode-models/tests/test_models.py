"""The models plugin: which keys it notices, and the official model each one offers."""

from __future__ import annotations

import pytest

from zettcode.models import VENDORS, ModelsPlugin
from zettcode.plugin_api import ModelConfig, PluginContext, ZettCodeConfig

ALL_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY")


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ALL_ENV:
        monkeypatch.delenv(variable, raising=False)


def _context(tmp_path) -> PluginContext:
    config = ZettCodeConfig(
        workspace=tmp_path, store=tmp_path / "sessions", models=(), harness_dir=tmp_path / "harness"
    )
    return PluginContext(config)


def test_the_plugin_stays_off_until_the_reader_enables_it():
    assert ModelsPlugin.default_enabled() is False


def test_a_key_registers_its_host_and_its_official_model(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    (provider,) = ctx.providers
    assert (provider.name, provider.label, provider.token_env) == ("openai", "OpenAI", "OPENAI_API_KEY")
    (model,) = provider.models
    assert model.model == "gpt-6.1-sol" and model.shown_name == "GPT-6.1 Sol"
    assert model.context_window == 1_050_000 and model.multimodal is True


def test_every_vendor_with_a_key_is_registered(tmp_path, monkeypatch):
    _clear(monkeypatch)
    for variable in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "ZAI_API_KEY"):
        monkeypatch.setenv(variable, "sk-test")
    ctx = _context(tmp_path)

    ModelsPlugin().activate(ctx)

    assert [provider.name for provider in ctx.providers] == ["openai", "anthropic", "deepseek", "zai"]
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
    assert {vendor.name for vendor in VENDORS} == {"openai", "anthropic", "deepseek", "zai"}
    assert all(vendor.model and vendor.base_url.startswith("https://") for vendor in VENDORS)


def test_a_shown_name_clash_is_reported_rather_than_silently_skipped(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="mine", display_model="GPT-6.1 Sol"),),
        harness_dir=tmp_path / "harness",
    )
    ctx = PluginContext(config)

    with pytest.raises(ValueError, match="already shown as 'GPT-6.1 Sol'"):
        ModelsPlugin().activate(ctx)


def test_every_clash_is_named_in_one_refusal(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(
            ModelConfig(model="one", display_model="GPT-6.1 Sol"),
            ModelConfig(model="two", display_model="Claude Opus 5.5"),
        ),
        harness_dir=tmp_path / "harness",
    )

    with pytest.raises(ValueError) as caught:
        ModelsPlugin().activate(PluginContext(config))

    message = str(caught.value)
    assert "OpenAI" in message and "GPT-6.1 Sol" in message
    assert "Anthropic" in message and "Claude Opus 5.5" in message


def test_the_table_is_internally_consistent():
    assert len({vendor.display for vendor in VENDORS}) == len(VENDORS)
    assert all(vendor.display and vendor.context_window > 0 for vendor in VENDORS)
    assert all(vendor.model != vendor.display for vendor in VENDORS)
