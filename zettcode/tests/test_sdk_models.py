"""Setting models up from code: the config file's `[[models]]` entries, with no client needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode import config
from zettcode.sdk import add_model, list_models, remove_model, update_model
from zettcode.sdk.models import add_model as add


def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_a_machine_with_no_config_lists_no_models_and_nothing_is_created(tmp_path: Path):
    path = config_file(tmp_path)

    assert list_models(path) == ()
    assert not path.exists()


def test_the_first_model_is_written_into_a_file_that_did_not_exist(tmp_path: Path):
    path = config_file(tmp_path)

    models = add({"model": "gpt-5", "token": "sk-1", "display_model": "Fast"}, path=path)

    assert [(model.name, model.model) for model in models] == [("Fast", "gpt-5")]
    assert models[0].active is False, "only a client knows which model is in use"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("[[models]]") and 'model = "gpt-5"' in text and 'token = "sk-1"' in text
    assert config.read_models(path)[0].shown_name == "Fast"


def test_a_second_model_is_added_after_the_last_and_the_rest_of_the_file_is_kept(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('# my models\n[[models]]\nmodel = "a"\ntoken = "t"\n\n[ui]\npet = "penguin"\n', encoding="utf-8")

    models = add({"model": "b", "token": "t2"}, path=path)

    text = path.read_text(encoding="utf-8")
    assert [model.model for model in models] == ["a", "b"]
    assert text.startswith("# my models") and '[ui]\npet = "penguin"' in text
    assert text.index('model = "b"') < text.index("[ui]")


def test_an_entry_that_is_not_a_usable_model_writes_nothing(tmp_path: Path):
    path = config_file(tmp_path)

    with pytest.raises(ValueError):
        add({"model": "", "token": "t"}, path=path)

    assert not path.exists(), "a refused write leaves no half-made file"


def test_an_entry_that_is_not_a_usable_model_leaves_the_existing_file_as_it_was(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "a"\ntoken = "t"\n', encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        add({"model": "", "token": "t"}, path=path)  # no model id

    assert path.read_text(encoding="utf-8") == before


def test_updating_a_model_keeps_every_key_it_did_not_name_and_the_token(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text(
        '[[models]]\nmodel = "a"\ntoken = "secret"\ndisplay_model = "A"\ncontext_window = 100000\n', encoding="utf-8"
    )

    models = update_model("A", {"context_window": 200000, "multimodal": True}, path=path)

    assert models[0].context_window == 200_000 and models[0].multimodal is True
    text = path.read_text(encoding="utf-8")
    assert 'token = "secret"' in text and 'display_model = "A"' in text


def test_a_model_with_only_an_id_is_a_model_and_its_token_is_not_written(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = config_file(tmp_path)

    models = add({"model": "llama3", "base_url": "http://localhost:11434/v1", "chat": True}, path=path)

    assert [model.model for model in models] == ["llama3"]
    text = path.read_text(encoding="utf-8")
    assert "token" not in text and "chat = true" in text


def test_chat_and_temperature_are_written_and_read_back(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "a"\ntoken = "t"\n', encoding="utf-8")

    update_model("a", {"chat": True, "temperature": 0.2}, path=path)

    text = path.read_text(encoding="utf-8")
    assert "chat = true" in text and "temperature = 0.2" in text
    read = config.read_models(path)[0]
    assert read.chat is True and read.temperature == 0.2


def test_a_key_changed_to_none_is_taken_out_of_the_entry(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text(
        '[[models]]\nmodel = "a"\ntoken = "secret"\nanthropic = true\ntemperature = 0.5\n', encoding="utf-8"
    )

    update_model("a", {"anthropic": None, "temperature": None, "chat": True}, path=path)

    text = path.read_text(encoding="utf-8")
    assert "anthropic" not in text and "temperature" not in text, "removed, not left as false"
    assert 'token = "secret"' in text and "chat = true" in text
    assert config.read_models(path)[0].api == "chat"


def test_a_temperature_of_zero_is_kept_and_is_not_the_same_as_none(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "a"\ntoken = "t"\n', encoding="utf-8")

    update_model("a", {"temperature": 0}, path=path)

    assert config.read_models(path)[0].temperature == 0.0


def test_a_model_can_be_named_by_its_id_when_it_has_a_display_name(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "gpt-5"\ntoken = "t"\ndisplay_model = "Fast"\n', encoding="utf-8")

    assert update_model("gpt-5", {"display_model": "Quick"}, path=path)[0].name == "Quick"


def test_updating_something_that_is_not_configured_says_what_is(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "a"\ntoken = "t"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="No model called 'nope'.*a"):
        update_model("nope", {"multimodal": True}, path=path)
    with pytest.raises(ValueError, match="No model called 'nope'.*a"):
        remove_model("nope", path=path)


def test_removing_a_model_keeps_the_others_and_the_last_one_cannot_go(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text('[[models]]\nmodel = "a"\ntoken = "t"\n\n[[models]]\nmodel = "b"\ntoken = "t"\n', encoding="utf-8")

    left = remove_model("a", path=path)

    assert [model.model for model in left] == ["b"]
    with pytest.raises(ValueError, match="only model"):
        remove_model("b", path=path)
    assert "b" in path.read_text(encoding="utf-8")


def test_a_file_that_does_not_parse_is_reported_and_untouched(tmp_path: Path):
    path = config_file(tmp_path)
    path.write_text("[[models]\nmodel = ", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid config"):
        add_model({"model": "a", "token": "t"}, path=path)
    assert path.read_text(encoding="utf-8") == "[[models]\nmodel = "


def test_a_missing_token_falls_back_to_the_environment_like_the_configuration_does(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    path = config_file(tmp_path)

    # The file's entry may leave the token out; the configuration resolves it from the environment.
    models = add({"model": "a"}, path=path)

    assert models[0].model == "a" and config.read_models(path)[0].token == "sk-env"
