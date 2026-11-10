"""``/config add``: parsing a line, the draft a panel fills in, and the entry it becomes."""

from __future__ import annotations

import pytest

from zettcode.app.ui.config_form import Draft, describe, entry_for, parse_add
from zettcode.providers import Api

# -- the entry a draft becomes ----------------------------------------------------------------------------


def test_a_draft_needs_a_model_id():
    with pytest.raises(ValueError, match="model id"):
        entry_for(Draft())


def test_a_draft_becomes_the_keys_the_file_writes():
    draft = parse_add('--model m --token t --url https://llm.example/v1 --name "My Model"')

    assert entry_for(draft) == {
        "model": "m",
        "token": "t",
        "base_url": "https://llm.example/v1",
        "display_model": "My Model",
    }


def test_an_empty_token_is_not_written_so_the_environment_can_supply_one():
    draft = parse_add("--model m")

    assert entry_for(draft) == {"model": "m"}


def test_each_protocol_writes_its_own_key():
    assert entry_for(parse_add("--model m --token t --api responses")) == {
        "model": "m",
        "token": "t",
        "responses_api": True,
    }
    assert entry_for(parse_add("--model m --token t --api anthropic")) == {
        "model": "m",
        "token": "t",
        "anthropic": True,
    }
    assert entry_for(parse_add("--model m --token t --api chat")) == {
        "model": "m",
        "token": "t",
        "chat": True,
    }


def test_an_entry_that_names_no_protocol_is_chat_without_a_key():
    assert entry_for(parse_add("--model m --token t")) == {"model": "m", "token": "t"}


def test_an_address_has_to_be_an_http_url():
    with pytest.raises(ValueError, match="http or https"):
        entry_for(parse_add("--model m --url ftp://x"))


def test_multimodal_context_compact_and_web_search_are_written():
    entry = entry_for(
        parse_add(
            "--model m --token t --multimodal --context 200k --compact 70 "
            "--web-search --search-tool web_search_20250305"
        )
    )

    assert entry["multimodal"] is True
    assert entry["context_window"] == 200_000
    assert entry["compact_percent"] == 70
    assert entry["web_search"] is True
    assert entry["web_search_name"] == "web_search_20250305"


def test_a_temperature_is_written_and_an_anthropic_one_stops_at_one():
    assert entry_for(parse_add("--model m --temperature 0.2"))["temperature"] == 0.2
    with pytest.raises(ValueError, match="from 0 to 1"):
        parse_add("--model m --temperature 1.5 --api anthropic")


# -- parsing /config add ----------------------------------------------------------------------------------


def test_a_line_is_flags_and_values():
    draft = parse_add("--model deepseek-chat --token sk-1")

    assert draft.model == "deepseek-chat" and draft.token == "sk-1" and draft.api is Api.CHAT


def test_a_draft_asks_for_the_protocol_before_the_rest():
    assert parse_add("").missing() == ["api", "model", "token"]
    assert parse_add("--api responses").missing() == ["model", "token"]
    assert parse_add("--api responses --model m").missing() == ["token"]
    assert parse_add("--api responses --model m --token t").missing() == []


def test_the_panel_starts_with_chat_until_it_is_told_otherwise():
    assert Draft().api is Api.CHAT
    assert parse_add("--api anthropic").api is Api.ANTHROPIC


def test_a_model_id_on_its_own_is_refused_with_the_usage():
    with pytest.raises(ValueError, match="Put the model after --model"):
        parse_add("gpt-5")


def test_an_empty_line_says_how_to_write_one():
    assert parse_add("").missing() == ["api", "model", "token"]


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ("--model m --colour red", "Unknown option '--colour'"),
        ("--model", "--model needs a value"),
        ("--model --token t", "--model needs a value"),
        ("--model a --model b", "--model was given twice"),
        ("--api grpc", "--api: the api must be one of chat, responses, anthropic"),
        ("--url ftp://x", "--url must be an http or https address"),
        ('--name "unterminated', "cannot read that"),
    ],
)
def test_a_line_that_cannot_be_read_says_why(line, said):
    with pytest.raises(ValueError, match=said):
        parse_add(line)


def test_undo_takes_back_the_last_answer():
    draft = Draft(token="t", given={"token"}, trail=[("token", "t")])

    assert draft.undo() == "t"
    assert draft.token == "" and "token" not in draft.given


def test_describe_says_what_a_model_is():
    entry = entry_for(parse_add("--model m --token t --api anthropic --name Mine"))

    assert "Mine" in describe(entry)
    assert "anthropic" in describe(entry) and "default address" in describe(entry)


def test_describing_an_entry_never_shows_the_token():
    entry = entry_for(parse_add("--model m --token sk-secret"))

    described = describe(entry)

    assert "sk-secret" not in described and "m" in described
