"""What a model entry becomes when its adapter is built: the key, the temperature, and the protocol."""

from __future__ import annotations

import pytest

from zettcode.app.agent.runtime import _build_provider
from zettcode.config import KEYLESS_TOKEN, ModelConfig


class Recorder:
    """Stands for an adapter and keeps the arguments it was built with."""

    built: list[tuple[tuple, dict]] = []

    def __init__(self, *args, **kwargs):
        type(self).built.append((args, kwargs))


@pytest.fixture
def adapters(monkeypatch):
    class OpenAI(Recorder):
        built: list[tuple[tuple, dict]] = []

    class Anthropic(Recorder):
        built: list[tuple[tuple, dict]] = []

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", OpenAI)
    monkeypatch.setattr("zett_agent.providers.anthropic.AnthropicProvider", Anthropic)
    return OpenAI, Anthropic


def test_a_model_with_no_key_is_built_with_a_stand_in_so_a_local_server_works(adapters):
    openai, _ = adapters

    _build_provider(ModelConfig(model="llama3", base_url="http://localhost:11434/v1"))

    ((args, kwargs),) = openai.built
    assert args == ("llama3", KEYLESS_TOKEN)
    assert kwargs["base_url"] == "http://localhost:11434/v1"


def test_a_key_that_was_given_is_sent_as_it_was(adapters):
    openai, _ = adapters
    _build_provider(ModelConfig(model="gpt-5", token="sk-real"))
    assert openai.built[0][0] == ("gpt-5", "sk-real")


def test_a_temperature_is_handed_to_an_openai_compatible_adapter_and_only_when_there_is_one(adapters):
    openai, _ = adapters

    _build_provider(ModelConfig(model="a", token="t", temperature=0.2))
    _build_provider(ModelConfig(model="b", token="t"))
    _build_provider(ModelConfig(model="c", token="t", temperature=0.0))

    assert openai.built[0][1]["temperature"] == 0.2
    assert "temperature" not in openai.built[1][1], "none is sent unless one was asked for"
    assert openai.built[2][1]["temperature"] == 0.0, "zero is a temperature, not the absence of one"


def test_a_temperature_reaches_the_responses_adapter_too(adapters):
    openai, _ = adapters
    _build_provider(ModelConfig(model="a", token="t", responses_api=True, temperature=0.7))
    assert openai.built[0][1]["temperature"] == 0.7 and openai.built[0][1]["response"] is True


def test_anthropics_adapter_has_no_temperature_so_it_goes_in_the_body_of_the_request(adapters):
    _, anthropic = adapters

    _build_provider(ModelConfig(model="claude", token="k", anthropic=True, temperature=0.4))
    _build_provider(ModelConfig(model="claude", token="k", anthropic=True))

    assert anthropic.built[0][1]["extra_body"] == {"temperature": 0.4}
    assert "extra_body" not in anthropic.built[1][1]


def test_the_chat_flag_changes_nothing_about_the_adapter(adapters):
    openai, _ = adapters
    _build_provider(ModelConfig(model="a", token="t", chat=True))
    _build_provider(ModelConfig(model="a", token="t"))
    assert openai.built[0] == openai.built[1]
