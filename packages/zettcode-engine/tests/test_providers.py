"""Providers and the models they offer: what is accepted, and what an entry becomes."""

from __future__ import annotations

import pytest

from zettcode.engine.provided import entries, merged, model_from
from zettcode.providers import Api, ProvidedModel, Provider, check_url


def _provider(**options: object) -> Provider:
    settings: dict[str, object] = {"base_url": "https://api.acme.example/v1"}
    settings.update(options)
    return Provider("acme", "Acme AI", **settings)  # type: ignore[arg-type]


# -- the description of a host ------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "Upper", "1abc", "has space", "a" * 33, "dot.name", "-lead"])
def test_a_provider_name_must_be_a_lower_case_word(name: str):
    with pytest.raises(ValueError, match="Provider name"):
        Provider(name, "Label")


def test_a_provider_needs_a_label():
    with pytest.raises(ValueError, match="needs a label"):
        Provider("acme", "   ")


def test_a_provider_must_name_one_of_the_three_apis():
    with pytest.raises(ValueError, match="must be one of chat, responses, anthropic"):
        Provider("acme", "Acme", api="grpc")


@pytest.mark.parametrize("url", ["", "api.example.com", "ftp://x.example", "https://", "just text"])
def test_an_address_must_be_http_or_https_with_a_host(url: str):
    with pytest.raises(ValueError, match="http or https"):
        Provider("acme", "Acme", base_url=url)


def test_a_token_variable_must_be_an_environment_name():
    with pytest.raises(ValueError, match="environment variable"):
        Provider("acme", "Acme", token_env="not a name")


def test_a_provider_may_take_no_key_at_all():
    assert Provider("local", "Local", base_url="http://localhost:11434/v1").token_env is None


def test_a_provider_lists_only_models():
    with pytest.raises(ValueError, match="ProvidedModel"):
        Provider("acme", "Acme", models=("m",))


# -- the models it offers -----------------------------------------------------------------------------


def test_a_provided_model_needs_an_id():
    with pytest.raises(ValueError, match="model id"):
        ProvidedModel("   ")


def test_a_provided_model_is_validated():
    with pytest.raises(ValueError, match="http or https"):
        ProvidedModel("m", base_url="ftp://x")
    with pytest.raises(ValueError, match="positive context window"):
        ProvidedModel("m", context_window=0)
    with pytest.raises(ValueError, match="between 1 and 100"):
        ProvidedModel("m", compact_percent=0)


def test_a_model_may_override_the_host_it_is_offered_at():
    model = ProvidedModel("m", api="responses", base_url="https://other.example/v1", multimodal=True)

    assert model.api is Api.RESPONSES
    assert model.base_url == "https://other.example/v1"
    assert model.multimodal is True


def test_a_model_is_shown_by_its_display_name_or_its_id():
    assert ProvidedModel("m").shown_name == "m"
    assert ProvidedModel("m", display_model="Mine").shown_name == "Mine"


# -- turning them into entries ------------------------------------------------------------------------


def test_a_provided_model_becomes_the_entry_a_request_uses(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "sk-acme")
    provider = _provider(token_env="ACME_API_KEY", models=(ProvidedModel("m", display_model="Mine"),))

    (entry,) = entries((provider,))

    assert entry.model == "m" and entry.display_model == "Mine"
    assert entry.base_url == "https://api.acme.example/v1" and entry.provider == "acme"
    assert entry.token == "sk-acme", "the token comes from the variable the provider names"
    assert entry.anthropic is False


def test_a_keyless_host_needs_no_variable():
    provider = Provider("local", "Local", base_url="http://localhost:11434/v1", models=(ProvidedModel("m"),))

    (entry,) = entries((provider,))

    assert entry.token == "" and entry.provider == "local"


def test_a_models_protocol_and_address_override_the_providers():
    provider = _provider(api=Api.CHAT, models=(ProvidedModel("m", api=Api.ANTHROPIC),))

    (entry,) = entries((provider,))

    assert entry.anthropic is True and entry.responses_api is False


def test_a_broken_level_is_refused_when_the_model_becomes_an_entry():
    provider = _provider(models=(ProvidedModel("m", reasoning_efforts=("banana",)),))

    with pytest.raises(ValueError, match="banana"):
        model_from(provider, provider.models[0])


def test_the_file_wins_a_name_a_provided_model_shares():
    from zettcode.config import ModelConfig

    file_model = ModelConfig("m", display_model="Mine")
    provider = _provider(models=(ProvidedModel("other", display_model="Mine"), ProvidedModel("second")))

    offered = merged((file_model,), entries((provider,)))

    assert [model.model for model in offered] == ["m", "second"]


def test_a_model_whose_key_is_missing_says_which_one(monkeypatch):
    from zettcode.sdk.models import model_info

    monkeypatch.delenv("ACME_API_KEY", raising=False)
    provider = _provider(token_env="ACME_API_KEY", models=(ProvidedModel("m"),))

    (entry,) = entries((provider,))

    assert entry.token == "" and entry.token_env == "ACME_API_KEY"
    assert model_info(entry).token_env == "ACME_API_KEY"


def test_a_model_whose_key_is_present_carries_no_such_note(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "sk-acme")
    provider = _provider(token_env="ACME_API_KEY", models=(ProvidedModel("m"),))

    (entry,) = entries((provider,))

    assert entry.token == "sk-acme" and entry.token_env is None


def test_a_runtime_with_only_provided_models_asks_the_reader_to_pick_one(tmp_path):
    from zettcode.config import NO_MODEL_CHOSEN, ZettCodeConfig
    from zettcode.engine.core import ZettCodeEngine
    from zettcode.engine.extensions.compaction import OnDemandCompaction
    from zettcode.engine.plugins import Plugins
    from zettcode.engine.plugins.services import COMPACTION, LLM

    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(),
        harness_dir=tmp_path / "harness",
    )
    provider = _provider(token_env=None, models=(ProvidedModel("m"),))
    seen: dict[str, object] = {}

    def load(config, shared):
        seen.update(shared)
        return Plugins(services={**shared, COMPACTION: OnDemandCompaction(None)}, providers=(provider,))

    runtime = ZettCodeEngine.preview(config, load)

    assert runtime.active_model is None and [model.model for model in runtime.models] == ["m"]
    assert runtime.no_model_refusal == NO_MODEL_CHOSEN
    assert [model.model for model in seen[LLM].models] == ["m"]
    with pytest.raises(ValueError, match="pick one with /model"):
        _ = runtime.required_model

    before = runtime.provided_models
    with pytest.raises(ValueError, match="stay available"):
        runtime.replace_provided(())
    assert runtime.provided_models == before and runtime.active_model is None

    second = _provider(models=(ProvidedModel("m2"),))
    runtime.replace_provided(entries((second,)))

    assert [model.model for model in seen[LLM].models] == ["m2"]


# -- discovery -----------------------------------------------------------------------------------------


def test_every_protocol_has_a_label_and_a_description():
    assert [api.label for api in Api] == [
        "OpenAI Chat API",
        "OpenAI Responses API",
        "Anthropic Messages API",
    ]
    assert all(api.description for api in Api)


def test_a_protocol_is_parsed_case_insensitively():
    assert Api.parse(" Anthropic ") is Api.ANTHROPIC
    with pytest.raises(ValueError, match="chat, responses, anthropic"):
        Api.parse("grpc")


def test_each_protocol_writes_its_key():
    assert Api.CHAT.keys == {} and Api.RESPONSES.keys == {"responses_api": True}
    assert Api.ANTHROPIC.keys == {"anthropic": True}


def test_an_address_is_trimmed_and_checked():
    assert check_url("  https://api.example.com/v1  ") == "https://api.example.com/v1"
    assert Provider("local", "Local", base_url="http://localhost:11434/v1").base_url.startswith("http://")


def test_a_provided_model_is_marked_with_the_provider_that_offered_it(monkeypatch):
    from zettcode.config import ModelConfig
    from zettcode.sdk.models import model_info

    monkeypatch.setenv("ACME_API_KEY", "sk-acme")
    provider = _provider(token_env="ACME_API_KEY", models=(ProvidedModel("m"),))

    (entry,) = entries((provider,))

    assert model_info(entry).provider == "acme"
    assert model_info(ModelConfig("m")).provider is None
