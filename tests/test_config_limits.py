"""``/config``: whether a model takes images, how big its window is, and when a conversation is summarized."""

from __future__ import annotations

import pytest

from test_config_command import BASE, shell  # noqa: F401 - the fixture and the file it starts from
from zettcode.app.ui.config_form import (
    Draft,
    entry_for,
    limits_text,
    parse_add,
    parse_percent,
    parse_tokens,
    whole_if_whole,
)
from zettcode.config import DEFAULT_COMPACT_PERCENT, DEFAULT_CONTEXT_WINDOW, ModelConfig
from zettcode.providers import BUILTIN_PROVIDERS

# -- how a size and a share are written -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("128000", 128_000),
        ("128,000", 128_000),
        ("128_000", 128_000),
        ("128k", 128_000),
        ("200 K", 200_000),
        ("1m", 1_000_000),
        ("1.5M", 1_500_000),
        ("256000 tokens", 256_000),
        ("1000", 1_000),
    ],
)
def test_a_window_is_written_as_a_number_of_tokens_or_with_k_or_m(text, tokens):
    assert parse_tokens(text) == tokens


@pytest.mark.parametrize("text", ["", "abc", "-5k", "1e6", "k", "1.2.3m"])
def test_what_is_not_a_size_says_how_one_is_written(text):
    with pytest.raises(ValueError, match="128000, 128k or 1m"):
        parse_tokens(text)


@pytest.mark.parametrize("text", ["200", "0", "999"])
def test_a_window_too_small_to_be_one_is_taken_for_thousands_and_says_so(text):
    with pytest.raises(ValueError, match="write 200k"):
        parse_tokens(text)


@pytest.mark.parametrize(
    ("text", "percent"), [("80", 80.0), ("80%", 80.0), (" 92.5 ", 92.5), ("100", 100.0), ("0.5", 0.5)]
)
def test_a_share_is_a_percentage_with_or_without_the_sign(text, percent):
    assert parse_percent(text) == percent


@pytest.mark.parametrize("text", ["0", "-1", "100.1", "101", "x", "", "%"])
def test_a_share_outside_the_window_or_not_a_number_is_refused(text):
    with pytest.raises(ValueError):
        parse_percent(text)


def test_a_whole_share_is_written_without_a_point():
    assert whole_if_whole(80.0) == 80 and isinstance(whole_if_whole(80.0), int)
    assert whole_if_whole(92.5) == 92.5


def test_the_limits_of_a_model_are_said_in_one_line_with_the_size_it_comes_to():
    model = ModelConfig(model="m", token="t", context_window=200_000, compact_percent=75)

    assert limits_text(model) == "200,000 tokens \u00b7 compressed at 75% (150,000 tokens)"


# -- /config add ------------------------------------------------------------------------------------------------


def _draft(line: str) -> Draft:
    return parse_add(line, BUILTIN_PROVIDERS)


def test_the_flags_of_add_carry_the_window_and_the_share_into_the_entry():
    draft = _draft("custom --api chat --url https://x.example/v1 --model m --token t --context 200k --compact 75%")

    entry = entry_for(draft)

    assert entry["context_window"] == 200_000 and entry["compact_percent"] == 75
    assert isinstance(entry["compact_percent"], int)


def test_a_model_added_without_them_carries_neither_so_the_defaults_stay_the_defaults():
    entry = entry_for(_draft("custom --url https://x.example/v1 --model m --token t"))

    assert "context_window" not in entry and "compact_percent" not in entry and "multimodal" not in entry


def test_a_flag_that_is_wrong_names_itself():
    with pytest.raises(ValueError, match=r"--context: .*write 200k"):
        _draft("custom --context 200")
    with pytest.raises(ValueError, match=r"--compact: .*at most 100"):
        _draft("custom --compact 150")
    with pytest.raises(ValueError, match="--context needs a value"):
        _draft("custom --context")


async def test_add_from_the_line_writes_the_window_and_the_share_and_the_session_has_them(shell):  # noqa: F811
    fx = shell()

    await fx.command(
        "/config add custom --api chat --url https://x.example/v1 --model big --token sk-x --context 1m --compact 60"
    )

    written = fx.models[2]
    assert written["context_window"] == 1_000_000 and written["compact_percent"] == 60
    model = fx.app.agent.models[2]
    assert model.context_window == 1_000_000 and model.compaction_max_tokens == 600_000


# -- the panel --------------------------------------------------------------------------------------------------


async def test_a_model_in_the_panel_offers_images_the_window_and_when_to_compress(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")

    fx.choose("GPT-4o")

    screen = fx.screen()
    assert "Images" in screen and "text only" in screen
    assert "Context window" in screen and "128,000 tokens" in screen, "the default is the placeholder"
    assert "Compress at" in screen and "80 (% of the window)" in screen


async def test_images_are_a_switch_that_starts_on_the_current_answer(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    assert fx.panel.values["multimodal"] is False
    row = next(line for line in fx.screen().splitlines() if "Images" in line)
    assert "\u25cf" + "\u2500" * 9 in row and row.rstrip().endswith("text only")


async def test_turning_images_on_writes_multimodal_and_the_session_takes_images_at_once(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.go("multimodal")

    fx.harness.press("right")
    fx.harness.press("enter")

    assert fx.models[1]["multimodal"] is True and fx.app.agent.models[1].multimodal is True
    assert "updated GPT-4o" in " ".join(fx.notices())


async def test_turning_images_off_removes_the_key_because_off_is_the_default(shell):  # noqa: F811
    fx = shell(BASE + '\n[[models]]\nmodel = "vision"\ntoken = "sk-v"\nmultimodal = true\n')
    await fx.command("/config")
    fx.choose("vision")
    assert fx.panel.values["multimodal"] is True
    fx.go("multimodal")

    fx.harness.write(" ")
    fx.harness.press("enter")

    assert "multimodal" not in fx.models[2] and fx.app.agent.models[2].multimodal is False


async def test_the_window_takes_k_and_m_and_the_notice_says_where_it_compresses(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("context_window", "200k")

    fx.harness.press("enter")

    assert fx.models[1]["context_window"] == 200_000 and fx.app.agent.models[1].context_window == 200_000
    assert "200,000 tokens" in " ".join(fx.notices()) and "160,000 tokens" in " ".join(fx.notices())


async def test_a_window_written_as_a_few_hundred_is_refused_with_how_to_write_it_and_nothing_is_written(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("context_window", "200")

    fx.harness.press("enter")

    assert "write 200k" in fx.panel.refusal and fx.panel.focus_key() == "context_window"
    assert "context_window" not in fx.models[1]


async def test_clearing_the_window_goes_back_to_the_default(shell):  # noqa: F811
    fx = shell(BASE.replace('token = "sk-two"', 'token = "sk-two"\ncontext_window = 200000'))
    await fx.command("/config")
    fx.choose("GPT-4o")
    assert fx.panel.editor("context_window").text == "200000"
    fx.edit("context_window", "")

    fx.harness.press("enter")

    assert "context_window" not in fx.models[1]
    assert fx.app.agent.models[1].context_window == DEFAULT_CONTEXT_WINDOW


async def test_a_window_the_reader_did_not_touch_is_not_rewritten_however_the_file_spells_it(shell):  # noqa: F811
    fx = shell(BASE.replace('token = "sk-two"', 'token = "sk-two"\ncompact_percent = 75.0'))
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("temperature", "0.3")

    fx.harness.press("enter")

    assert "compact_percent = 75.0" in fx.text and fx.models[1]["temperature"] == 0.3


async def test_the_share_takes_a_percentage_and_moves_the_point_a_request_is_summarized_at(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("compact_percent", "50%")

    fx.harness.press("enter")

    assert fx.models[1]["compact_percent"] == 50
    assert fx.app.agent.models[1].compaction_max_tokens == 64_000
    assert "compressed at 50%" in " ".join(fx.notices())


@pytest.mark.parametrize("text", ["0", "101", "lots"])
async def test_a_share_that_is_not_one_is_refused_and_nothing_is_written(shell, text):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("compact_percent", text)

    fx.harness.press("enter")

    assert fx.panel.refusal and fx.panel.focus_key() == "compact_percent"
    assert "compact_percent" not in fx.models[1]


async def test_clearing_the_share_goes_back_to_the_default(shell):  # noqa: F811
    fx = shell(BASE.replace('token = "sk-two"', 'token = "sk-two"\ncompact_percent = 50'))
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("compact_percent", "")

    fx.harness.press("enter")

    assert "compact_percent" not in fx.models[1]
    assert fx.app.agent.models[1].compact_percent == DEFAULT_COMPACT_PERCENT


async def test_changing_the_model_in_use_moves_its_compaction_point_in_the_running_session(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("gpt-5-mini")
    fx.edit("context_window", "1m")

    fx.harness.press("enter")

    assert fx.app.agent.active_model.context_window == 1_000_000
    assert fx.app.agent.runtime.compaction.max_tokens == 800_000


async def test_the_window_and_the_share_are_saved_by_one_enter_with_the_other_rows(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("context_window", "1m")
    fx.edit("compact_percent", "60")
    fx.go("multimodal")
    fx.harness.press("right")

    fx.harness.press("enter")

    written = fx.models[1]
    assert written["context_window"] == 1_000_000 and written["compact_percent"] == 60 and written["multimodal"] is True


async def test_the_rest_of_the_file_is_left_as_it_was(shell):  # noqa: F811
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("context_window", "200k")

    fx.harness.press("enter")

    assert "# my config" in fx.text and "# second" in fx.text and "[skills]" in fx.text
    assert fx.models[0] == {"model": "gpt-5-mini", "token": "sk-one"}


# -- the listing -------------------------------------------------------------------------------------------------


async def test_the_list_shows_what_each_model_takes_and_where_it_is_compressed(shell):  # noqa: F811
    fx = shell(
        BASE.replace(
            'token = "sk-two"', 'token = "sk-two"\nmultimodal = true\ncontext_window = 200000\ncompact_percent = 75'
        )
    )

    await fx.command("/config list")

    shown = "\n".join(entry.text for entry in fx.app.transcript.entries)
    assert "images" in shown and "context window" in shown and "compress at" in shown
    assert "| yes | 200,000 | 75% |" in shown and "| no | 128,000 | 80% |" in shown
