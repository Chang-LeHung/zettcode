"""``/config add``: parsing a line, the draft a panel fills in, and the entry it becomes."""

from __future__ import annotations

import pytest

from zettcode.app.ui.config_form import Draft, describe, entry_for, parse_add
from zettcode.config import ModelConfig
from zettcode.providers import BUILTIN_PROVIDERS, CUSTOM, Api, Provider, find_provider

PROVIDERS = BUILTIN_PROVIDERS


def test_every_builtin_provider_is_a_valid_unique_entry_that_makes_a_model():
    names = [provider.name for provider in BUILTIN_PROVIDERS]

    assert len(names) == len(set(names))
    for provider in BUILTIN_PROVIDERS:
        draft = Draft.for_provider(provider)
        draft.model, draft.token = "some-model", "some-token"
        ModelConfig(**_model_kwargs(entry_for(draft)))  # the loader's own rules accept it


def _model_kwargs(entry):
    return {
        "model": entry["model"],
        "token": entry["token"],
        "display_model": entry.get("display_model"),
        "base_url": entry.get("base_url"),
        "anthropic": bool(entry.get("anthropic")),
        "responses_api": bool(entry.get("responses_api")),
        "multimodal": bool(entry.get("multimodal")),
    }


# -- parsing /config add ----------------------------------------------------------------------------------


def test_a_preset_needs_only_a_model_and_a_token():
    draft = parse_add("deepseek --model deepseek-chat --token sk-1", PROVIDERS)

    assert draft.missing() == []
    assert entry_for(draft) == {"model": "deepseek-chat", "token": "sk-1", "base_url": "https://api.deepseek.com"}


def test_a_preset_asks_for_what_the_line_left_out_in_order():
    assert parse_add("deepseek", PROVIDERS).missing() == ["model", "token"]
    assert parse_add("deepseek --model m", PROVIDERS).missing() == ["token"]
    assert parse_add("deepseek --token t", PROVIDERS).missing() == ["model"]


def test_anthropic_gets_the_messages_api_and_its_own_address():
    entry = entry_for(parse_add("anthropic --model claude-x --token k", PROVIDERS))

    assert entry == {"model": "claude-x", "token": "k", "base_url": "https://api.anthropic.com", "anthropic": True}


def test_a_custom_endpoint_asks_for_its_protocol_and_address_first():
    assert parse_add("custom", PROVIDERS).missing() == ["api", "url", "model", "token"]


def test_a_custom_endpoint_given_everything_on_one_line_needs_nothing_more():
    draft = parse_add("custom --api chat --url https://llm.example/v1 --model m --token t --name Mine", PROVIDERS)

    assert draft.missing() == []
    assert entry_for(draft) == {
        "model": "m",
        "token": "t",
        "display_model": "Mine",
        "base_url": "https://llm.example/v1",
        "chat": True,
    }, "--api chat is said outright in the file"


def test_the_responses_api_is_written_as_responses_api():
    entry = entry_for(parse_add("custom --api responses --url https://x.example/v1 --model m --token t", PROVIDERS))

    assert entry["responses_api"] is True and "anthropic" not in entry


def test_a_custom_anthropic_endpoint_does_not_ask_for_an_address_because_the_sdk_has_one():
    draft = parse_add("custom --api anthropic --model m --token t", PROVIDERS)

    assert draft.missing() == []
    assert entry_for(draft) == {"model": "m", "token": "t", "anthropic": True}


def test_the_api_of_a_preset_can_be_overridden_for_the_responses_api():
    entry = entry_for(parse_add("openai --api responses --model m --token t", PROVIDERS))

    assert entry["responses_api"] is True and entry["base_url"] == "https://api.openai.com/v1"


def test_the_address_of_a_preset_can_be_overridden_for_a_proxy():
    entry = entry_for(parse_add("openai --url https://proxy.example/v1 --model m --token t", PROVIDERS))

    assert entry["base_url"] == "https://proxy.example/v1"


def test_multimodal_is_a_flag_with_no_value():
    entry = entry_for(parse_add("deepseek --model m --token t --multimodal", PROVIDERS))

    assert entry["multimodal"] is True


def test_values_with_spaces_can_be_quoted():
    entry = entry_for(parse_add('deepseek --model m --token t --name "My Fast Model"', PROVIDERS))

    assert entry["display_model"] == "My Fast Model"


def test_the_provider_name_may_be_typed_in_any_case():
    assert parse_add("DeepSeek", PROVIDERS).provider.name == "deepseek"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("", "Name the provider"),
        ("--model m", "Name the provider"),
        ("nope --model m", "Unknown provider 'nope'"),
        ("deepseek --colour red", "Unknown option '--colour'"),
        ("deepseek --model", "--model needs a value"),
        ("deepseek --model --token t", "--model needs a value"),
        ("deepseek --model a --model b", "--model was given twice"),
        ("deepseek --api grpc", "--api: the api must be one of chat, responses, anthropic"),
        ("deepseek --url ftp://x", "--url must be an http or https address"),
        ('deepseek --name "unterminated', "cannot read that"),
    ],
)
def test_a_line_that_cannot_be_understood_says_what_is_wrong(line, message):
    with pytest.raises(ValueError, match=message):
        parse_add(line, PROVIDERS)


def test_the_error_for_a_missing_provider_lists_the_ones_that_exist():
    with pytest.raises(ValueError) as caught:
        parse_add("", PROVIDERS)

    assert "deepseek" in str(caught.value) and CUSTOM in str(caught.value) and "Usage:" in str(caught.value)


# -- turning a draft into an entry --------------------------------------------------------------------------


def test_a_draft_needs_a_model_id_and_nothing_else_the_token_may_be_empty():
    draft = Draft.for_provider(find_provider("deepseek", PROVIDERS))
    with pytest.raises(ValueError, match="model id is required"):
        entry_for(draft)
    draft.model = "m"

    assert entry_for(draft) == {"model": "m", "base_url": "https://api.deepseek.com"}, "no token key is written"
    assert Draft.for_provider(find_provider("deepseek", PROVIDERS)).missing() == ["model", "token"], (
        "the form still shows the token line, and an empty answer is a valid one"
    )
    given = parse_add('deepseek --model m --token ""', PROVIDERS)
    assert given.missing() == [] and "token" not in entry_for(given)


def test_a_custom_draft_without_an_address_is_not_an_entry():
    draft = Draft(model="m", token="t")

    with pytest.raises(ValueError, match="needs an address"):
        entry_for(draft)


def test_values_are_trimmed_and_blank_names_are_dropped():
    draft = Draft.for_provider(find_provider("deepseek", PROVIDERS))
    draft.model, draft.token, draft.name = "  m ", " t\n", "   "

    entry = entry_for(draft)

    assert entry["model"] == "m" and entry["token"] == "t" and "display_model" not in entry


def test_the_multimodal_default_of_a_provider_carries_into_its_entries():
    seeing = Provider("eyes", "Eyes", base_url="https://eyes.example/v1", multimodal=True)
    draft = Draft.for_provider(seeing)
    draft.model, draft.token = "m", "t"

    assert entry_for(draft)["multimodal"] is True


def test_a_provider_without_an_address_asks_for_one_that_may_be_left_empty():
    bare = Provider("bare", "Bare")

    assert Draft.for_provider(bare).missing() == ["url", "model", "token"]


def test_describing_an_entry_never_shows_the_token():
    line = describe({"model": "m", "token": "SECRET-KEY", "display_model": "Shown", "anthropic": True})

    assert "SECRET-KEY" not in line and line.startswith("Shown")
    assert "anthropic" in line and "default address" in line


# -- taking an answer back ----------------------------------------------------------------------------------


def test_undo_with_nothing_answered_is_nothing():
    assert Draft.for_provider(find_provider("deepseek", PROVIDERS)).undo() is None


@pytest.mark.parametrize("field", ["model", "token"])
def test_undoing_an_answer_makes_it_the_next_thing_asked(field):
    draft = Draft.for_provider(find_provider("deepseek", PROVIDERS))
    draft.model, draft.token = "m", "t"
    draft.trail = [("model", "m"), ("token", "")]

    undone = draft.undo()

    assert undone == "" and draft.missing()[0] == "token"
    if field == "model":
        draft.undo()
        assert draft.missing()[0] == "model" and draft.model == ""


def test_undoing_the_address_and_the_api_of_a_custom_endpoint_asks_them_again():
    draft = Draft()
    draft.api, draft.url, draft.model = Api.RESPONSES, "https://x.example/v1", "m"
    draft.given |= {"api", "url"}
    draft.trail = [("api", Api.RESPONSES), ("url", "https://x.example/v1"), ("model", "m")]

    assert draft.undo() == "m"
    assert draft.undo() == "https://x.example/v1" and draft.url is None and draft.missing()[0] == "url"
    assert draft.undo() == Api.RESPONSES and draft.api == Api.CHAT and draft.missing()[0] == "api"


def test_undo_hands_back_one_answer_at_a_time_newest_first():
    draft = Draft()
    draft.trail = [("api", "chat"), ("url", "u"), ("model", "m")]

    assert [draft.undo(), draft.undo(), draft.undo(), draft.undo()] == ["m", "u", "chat", None]
