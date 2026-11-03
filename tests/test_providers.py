"""Providers: what is described, how lists merge, and the Api enum."""

from __future__ import annotations

import pytest

from zettcode.config import ModelConfig
from zettcode.providers import (
    BUILTIN_PROVIDERS,
    CUSTOM,
    Api,
    Provider,
    check_url,
    find_provider,
    merge_providers,
)

# -- the description of a host ------------------------------------------------------------------------


def test_every_builtin_provider_has_a_unique_name():
    names = [provider.name for provider in BUILTIN_PROVIDERS]

    assert len(names) == len(set(names))


def test_the_builtins_name_the_three_protocols():
    assert {provider.api for provider in BUILTIN_PROVIDERS} == {Api.CHAT, Api.ANTHROPIC}


def test_the_anthropic_builtin_speaks_the_messages_api():
    assert find_provider("anthropic", BUILTIN_PROVIDERS).api == Api.ANTHROPIC


def test_no_builtin_lists_models_because_such_a_list_goes_stale():
    assert all(provider.models == () for provider in BUILTIN_PROVIDERS)


@pytest.mark.parametrize("name", ["", "Upper", "1abc", "has space", "a" * 33, "dot.name", "-lead"])
def test_a_provider_name_must_be_a_lower_case_word(name):
    with pytest.raises(ValueError, match="Provider name"):
        Provider(name, "Label")


def test_custom_is_reserved_because_it_means_a_host_nobody_described():
    with pytest.raises(ValueError, match="reserved"):
        Provider(CUSTOM, "Mine")


def test_a_provider_needs_a_label():
    with pytest.raises(ValueError, match="needs a label"):
        Provider("mine", "   ")


def test_a_provider_must_name_one_of_the_three_apis():
    with pytest.raises(ValueError, match="must be one of chat, responses, anthropic"):
        Provider("mine", "Mine", api="grpc")


@pytest.mark.parametrize("url", ["", "api.example.com", "ftp://x.example", "https://", "just text"])
def test_an_address_must_be_http_or_https_with_a_host(url):
    with pytest.raises(ValueError, match="http or https"):
        Provider("mine", "Mine", base_url=url)


def test_an_address_is_trimmed():
    assert check_url("  https://api.example.com/v1  ") == "https://api.example.com/v1"


def test_a_plain_http_address_is_allowed_because_local_servers_have_no_certificate():
    assert Provider("local", "Local", base_url="http://localhost:11434/v1").base_url.startswith("http://")


# -- finding and merging ------------------------------------------------------------------------------


def test_a_provider_is_found_whatever_the_case_or_padding():
    assert find_provider("  DeepSeek ", BUILTIN_PROVIDERS).name == "deepseek"


def test_an_unknown_provider_is_not_found():
    assert find_provider("nope", BUILTIN_PROVIDERS) is None


def test_the_first_provider_to_claim_a_name_keeps_it_when_lists_are_merged():
    mine = Provider("openai", "My OpenAI", base_url="https://evil.example/v1")
    extra = Provider("acme", "Acme", base_url="https://api.acme.example/v1")

    merged = merge_providers(BUILTIN_PROVIDERS, (mine, extra))

    assert find_provider("openai", merged).label == "OpenAI", "a plugin cannot take over a built-in's name"
    assert find_provider("acme", merged) is extra
    assert len(merged) == len(BUILTIN_PROVIDERS) + 1


# -- the Api enum ---------------------------------------------------------------------------------------------


def test_the_three_protocols_are_the_words_a_reader_types():
    assert [api.value for api in Api] == ["chat", "responses", "anthropic"]


def test_a_member_is_its_word_wherever_a_string_is_expected():
    assert Api.CHAT == "chat" and str(Api.ANTHROPIC) == "anthropic" and f"{Api.RESPONSES}" == "responses"


def test_a_model_reports_its_protocol_as_a_member():
    assert ModelConfig(model="m", token="t").api is Api.CHAT
    assert ModelConfig(model="m", token="t", responses_api=True).api is Api.RESPONSES
    assert ModelConfig(model="m", token="t", anthropic=True).api is Api.ANTHROPIC


@pytest.mark.parametrize(
    ("typed", "api"), [("chat", Api.CHAT), (" Responses ", Api.RESPONSES), ("ANTHROPIC", Api.ANTHROPIC)]
)
def test_parse_accepts_any_case_and_padding(typed, api):
    assert Api.parse(typed) is api


def test_parse_refuses_anything_else_and_lists_the_choices():
    with pytest.raises(ValueError, match="one of chat, responses, anthropic, not 'grpc'"):
        Api.parse("grpc")


@pytest.mark.parametrize(
    ("api", "keys"),
    [(Api.CHAT, {}), (Api.RESPONSES, {"responses_api": True}), (Api.ANTHROPIC, {"anthropic": True})],
)
def test_each_protocol_selects_itself_with_the_keys_the_loader_reads(api, keys):
    assert api.keys == keys


def test_the_keys_of_every_protocol_are_among_the_ones_a_rewrite_clears():
    from zettcode.providers import API_FLAG_KEYS

    assert {key for api in Api for key in api.keys} <= set(API_FLAG_KEYS)
    assert "chat" in API_FLAG_KEYS, "a file that spells the default out loses it when the protocol changes"


def test_every_protocol_has_a_description():
    assert all(api.description for api in Api)


#: Words a note may begin with a capital for: the proper nouns the protocols and vendors are called.
PROPER_NOUNS = ("Anthropic", "Responses", "Messages", "Chat")


def _wording_problems(text: str) -> list[str]:
    """Say what is wrong with one note or description, by the rule every list in the shell follows:
    a phrase that starts in lower case (unless it opens with a proper noun), has no leading article, and no full stop."""
    problems = []
    first = text.split(" ", 1)[0]
    if first.lower() in ("the", "a", "an"):
        problems.append("starts with an article")
    if first[:1].isupper() and first not in PROPER_NOUNS:
        problems.append("starts with a capital that is not a proper noun")
    if text.endswith("."):
        problems.append("ends with a full stop")
    return problems


def test_every_built_in_provider_has_a_note_and_every_note_is_worded_the_same_way():
    """The picker showed a note here, an article there and a bare address for the two that had no note."""
    for provider in BUILTIN_PROVIDERS:
        assert provider.note, f"{provider.name} has no note"
        assert _wording_problems(provider.note) == [], (provider.name, provider.note)


def test_every_protocol_is_described_by_the_same_rule_and_without_the():
    for api in Api:
        assert _wording_problems(api.description) == [], (api, api.description)
    assert [api.description for api in Api] == ["chat completions", "Responses API", "Anthropic Messages API"]


def test_the_providers_that_speak_the_same_protocol_say_so_in_the_same_words():
    chat = [p for p in BUILTIN_PROVIDERS if p.api is Api.CHAT]

    assert all(p.note.startswith("chat completions") for p in chat), [p.note for p in chat]


def test_a_provider_given_the_protocol_as_text_holds_it_as_a_member():
    assert Provider("p", "P", api="responses").api is Api.RESPONSES


def test_a_provider_with_an_unknown_protocol_is_refused_naming_it():
    with pytest.raises(ValueError, match="Provider 'p': the api must be one of"):
        Provider("p", "P", api="grpc")
