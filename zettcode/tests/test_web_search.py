"""Hosted web search: a model entry says whether it has one, which tool name it is called, and where it is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.config import (
    DEFAULT_ANTHROPIC_WEB_SEARCH_NAME,
    DEFAULT_DEEPSEEK_ANTHROPIC_WEB_SEARCH_NAME,
    DEFAULT_WEB_SEARCH_NAME,
    ModelConfig,
    load_config,
)
from zettcode.config_edit import entry_from_model
from zettcode.engine.extensions.capabilities import ModelCapabilities, web_search_tool
from zettcode.sdk import add_model, update_model


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ZETTCODE_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def _model(model: str = "m", **changes) -> ModelConfig:
    return ModelConfig(model=model, token="t", **changes)


def test_search_is_off_unless_an_entry_asks_for_it():
    model = _model()

    assert model.web_search is False and model.web_search_name is None


@pytest.mark.parametrize(
    ("changes", "tool_type"),
    [
        ({}, DEFAULT_WEB_SEARCH_NAME),
        ({"responses_api": True}, DEFAULT_WEB_SEARCH_NAME),
        ({"anthropic": True}, DEFAULT_ANTHROPIC_WEB_SEARCH_NAME),
        ({"model": "deepseek-v4", "anthropic": True}, DEFAULT_DEEPSEEK_ANTHROPIC_WEB_SEARCH_NAME),
        (
            {"model": "flash", "base_url": "https://api.deepseek.com/anthropic", "anthropic": True},
            DEFAULT_DEEPSEEK_ANTHROPIC_WEB_SEARCH_NAME,
        ),
    ],
    ids=["chat", "responses", "anthropic", "deepseek-by-id", "deepseek-by-address"],
)
def test_each_api_has_its_own_default_tool_name(changes, tool_type):
    """The names differ by API, and DeepSeek's Anthropic-compatible endpoint knows only the older dated one."""
    assert _model(web_search=True, **changes).search_name == tool_type


def test_an_entry_can_name_the_tool_its_provider_calls_search():
    model = _model(anthropic=True, web_search=True, web_search_name="  web_search_20250305  ")

    assert model.web_search_name == "web_search_20250305", "surrounding space is a paste, not part of the name"
    assert model.search_name == "web_search_20250305"
    assert _model(web_search_name="   ").web_search_name is None, "a blank name is no name"


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "deepseek-chat"},
        {"model": "x", "base_url": "https://api.deepseek.com/v1"},
        {"model": "deepseek-r", "responses_api": True},
    ],
    ids=["by-id", "by-address", "responses"],
)
def test_deepseek_is_searched_only_through_its_anthropic_compatible_endpoint(changes):
    with pytest.raises(ValueError, match="DeepSeek serves web search only on its Anthropic-compatible endpoint"):
        _model(web_search=True, **changes)
    assert _model(**changes).can_search is False, "the form says so before a reader switches it on"
    assert _model(
        web_search=True, anthropic=True, **{k: v for k, v in changes.items() if k != "responses_api"}
    ).can_search


def test_the_same_deepseek_model_without_search_is_fine_on_any_api():
    assert _model("deepseek-chat").web_search is False
    assert _model("deepseek-chat", responses_api=True).web_search is False


def test_other_providers_are_left_to_the_endpoint():
    """A gateway may serve what its vendor does not, so nothing else is refused up front."""
    for changes in ({}, {"responses_api": True}, {"anthropic": True}, {"base_url": "http://localhost:11434/v1"}):
        assert _model(web_search=True, **changes).can_search is True


def test_the_config_file_reads_both_keys_and_rejects_the_wrong_types(tmp_path: Path):
    def load(body: str) -> ModelConfig:
        path = tmp_path / "config.toml"
        path.write_text(f'[[models]]\nmodel = "a"\ntoken = "t"\n{body}\n', encoding="utf-8")
        return load_config(tmp_path, path=path).models[0]

    model = load('web_search = true\nweb_search_name = "web_search_2025"')
    assert model.web_search is True and model.web_search_name == "web_search_2025"
    assert load("").web_search is False
    for bad in ('web_search = "yes"', "web_search_name = 3"):
        with pytest.raises(ValueError, match="web_search"):
            load(bad)
    with pytest.raises(ValueError, match=r"models\[1\].*DeepSeek"):
        path = tmp_path / "config.toml"
        path.write_text('[[models]]\nmodel = "deepseek-chat"\ntoken = "t"\nweb_search = true\n', encoding="utf-8")
        load_config(tmp_path, path=path)


def test_the_entry_written_back_keeps_search_and_leaves_out_a_name_that_was_never_set():
    assert entry_from_model(_model(web_search=True))["web_search"] is True
    assert "web_search_name" not in entry_from_model(_model(web_search=True))
    assert entry_from_model(_model(web_search=True, web_search_name="x"))["web_search_name"] == "x"
    assert "web_search" not in entry_from_model(_model())


def test_search_is_written_and_removed_through_the_sdk(tmp_path: Path):
    path = tmp_path / "config.toml"
    add_model({"model": "a", "token": "t", "web_search": True, "web_search_name": "web_search"}, path=path)
    text = path.read_text(encoding="utf-8")
    assert "web_search = true" in text and 'web_search_name = "web_search"' in text

    update_model("a", {"web_search": None, "web_search_name": None}, path=path)
    after = path.read_text(encoding="utf-8")
    assert "web_search" not in after, "null removes the key rather than leaving `web_search = false`"


class _Context:
    """The three things the capability filter reads and changes."""

    def __init__(self, provider: object) -> None:
        self.model = provider
        self.tools: dict[str, object] = {}
        self.server_tools: dict[str, object] = {}

    def register_tool(self, tool) -> None:
        self.tools[tool.name] = tool

    def register_server_tool(self, tool) -> None:
        self.server_tools[tool.type] = tool


def _declared(model: ModelConfig):
    provider = object()
    capabilities = ModelCapabilities({model: provider})
    return provider, capabilities


async def test_a_model_with_search_is_given_the_tool_its_api_names():
    for model, tool_type, configuration in (
        (_model(web_search=True), "web_search", {}),
        (_model(responses_api=True, web_search=True), "web_search", {}),
        (_model(anthropic=True, web_search=True), "web_search_20260318", {"name": "web_search"}),
        (_model("deepseek-v4", anthropic=True, web_search=True), "web_search_20250305", {"name": "web_search"}),
        (
            _model(anthropic=True, web_search=True, web_search_name="web_search_20250305"),
            "web_search_20250305",
            {"name": "web_search"},
        ),
    ):
        provider, capabilities = _declared(model)
        context = _Context(provider)

        await capabilities.on_tool(context)

        (declared,) = context.server_tools.values()
        assert declared.type == tool_type and dict(declared.configuration) == configuration, model


async def test_a_model_without_search_is_given_none_and_an_unknown_provider_is_left_alone():
    provider, capabilities = _declared(_model())
    context = _Context(provider)
    await capabilities.on_tool(context)
    assert context.server_tools == {}

    stranger = _Context(object())
    await capabilities.on_tool(stranger)
    assert stranger.server_tools == {} and stranger.tools == {}


async def test_switching_model_changes_the_search_the_next_request_declares():
    """The decision follows the request's own model, so `/model` needs no rebuild."""
    searching, quiet = object(), object()
    capabilities = ModelCapabilities({_model("a", web_search=True): searching, _model("b"): quiet})

    first, second = _Context(searching), _Context(quiet)
    await capabilities.on_tool(first)
    await capabilities.on_tool(second)

    assert list(first.server_tools) == ["web_search"] and second.server_tools == {}


def test_the_declared_tool_is_the_wire_shape_the_providers_documentation_shows():
    anthropic = web_search_tool(_model(anthropic=True, web_search=True))
    chat = web_search_tool(_model(web_search=True))

    assert (anthropic.type, dict(anthropic.configuration)) == ("web_search_20260318", {"name": "web_search"})
    assert (chat.type, dict(chat.configuration)) == ("web_search", {})


def test_the_providers_render_the_declared_tool_as_their_own_wire_schema():
    """Not just our own shape: what the framework's request builders put in `tools`."""
    from zett_agent.providers.anthropic_compatible import messages_server_tools
    from zett_agent.providers.openai_compatible import chat_server_tools
    from zett_agent.providers.responses import responses_tools

    anthropic = web_search_tool(_model(anthropic=True, web_search=True))
    deepseek = web_search_tool(_model("deepseek-v4", anthropic=True, web_search=True))
    chat = web_search_tool(_model(web_search=True))

    assert messages_server_tools([anthropic]) == [{"type": "web_search_20260318", "name": "web_search"}]
    assert messages_server_tools([deepseek]) == [{"type": "web_search_20250305", "name": "web_search"}]
    assert chat_server_tools([chat]) == [{"type": "web_search"}]
    assert responses_tools([], [chat]) == [{"type": "web_search"}]
