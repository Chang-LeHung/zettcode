from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig, load_config


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ZETTCODE_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def _model(model: str = "model", token: str = "secret", **changes) -> ModelConfig:
    """Return a minimal model entry for a config under test."""
    return ModelConfig(model=model, token=token, **changes)


def test_config_resolves_paths(tmp_path: Path):
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "data" / "sessions",
        models=(_model(),),
    )

    assert config.workspace == tmp_path.resolve()
    assert config.store == (tmp_path / "data" / "sessions").resolve()
    assert len(config.models) == 1


def test_shown_model_falls_back_to_the_model_id(tmp_path: Path):
    config = ZettCodeConfig(workspace=tmp_path, store=tmp_path / "s", models=(_model(model="gpt-4o"),))
    named = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "s",
        models=(_model(model="gpt-4o", display_model="GPT-4o"),),
    )

    assert config.models[0].shown_name == "gpt-4o"
    assert named.models[0].shown_name == "GPT-4o"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model": ""}, "Model cannot be empty"),
        ({"token": ""}, "Missing token"),
    ],
)
def test_model_config_rejects_invalid_values(changes, message):
    with pytest.raises(ValueError, match=message):
        ModelConfig(**{"model": "m", "token": "t", **changes})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_iterations": 0}, "max_iterations"),
        ({"compaction_keep_tokens": 0}, "compaction_keep_tokens"),
        ({"compaction_max_tokens": 10, "compaction_keep_tokens": 10}, "must be greater"),
    ],
)
def test_config_rejects_invalid_limits(tmp_path: Path, changes, message):
    with pytest.raises(ValueError, match=message):
        ZettCodeConfig(
            workspace=tmp_path,
            store=tmp_path / "sessions",
            models=(_model(),),
            **changes,
        )


def test_load_config_reads_models_and_storage(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "",
                "[[models]]",
                'model = "gpt-4o"',
                'display_model = "GPT-4o"',
                'token = "openai-token"',
                'base_url = "https://api.openai.com/v1"',
                "responses_api = true",
                "multimodal = true",
                "",
                "[[models]]",
                'model = "deepseek-chat"',
                'display_model = "DeepSeek Chat"',
                'token = "deepseek-token"',
                'base_url = "https://api.deepseek.com/v1"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path, path=path)

    assert config.store == (Path.home() / ".zettcode" / "sessions").resolve()
    assert [model.model for model in config.models] == ["gpt-4o", "deepseek-chat"]
    assert config.models[1].token == "deepseek-token"
    assert config.models[1].base_url == "https://api.deepseek.com/v1"
    assert config.models[0].multimodal is True
    assert config.models[0].responses_api is True
    assert config.models[1].multimodal is False
    assert config.models[1].shown_name == "DeepSeek Chat"


def test_load_config_defaults_to_the_first_model(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    config = load_config(tmp_path, path=path)

    assert config.models[0].model == "m"
    assert config.store == (Path.home() / ".zettcode" / "sessions").resolve()


@pytest.mark.parametrize("setting", ['store = "elsewhere"', 'session = "s1"', 'model = "m"'])
def test_load_config_rejects_session_and_selection_settings(tmp_path: Path, setting: str):
    path = tmp_path / "config.toml"
    path.write_text(f'{setting}\n[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown config keys"):
        load_config(tmp_path, path=path)


def test_load_config_falls_back_to_the_environment_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-environment")
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\n', encoding="utf-8")

    assert load_config(tmp_path, path=path).models[0].token == "from-environment"


def test_load_config_reads_the_env_override_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "custom.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    assert load_config(tmp_path).models[0].model == "m"


def test_load_config_requires_at_least_one_model(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="No models configured"):
        load_config(tmp_path, path=path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('provider = "openai"\n[[models]]\nmodel = "m"\ntoken = "t"\n', "Unknown config keys"),
        ('[[models]]\nmodel = "m"\ntoken = "t"\napi_key = "x"\n', "Unknown config keys in Config models\\[1\\]"),
        ('[[models]]\nmodel = "m"\nmodle = "x"\ntoken = "t"\n', "Unknown config keys in Config models\\[1\\]"),
        ('models = "nope"\n', "must be an array of tables"),
        ('[[models]]\ntoken = "t"\n', "missing 'model'"),
        ("models = []\n", "No models configured"),
        ('[[models]]\nmodel = "m"\nmultimodal = "yes"\ntoken = "t"\n', "must be bool"),
        ('[[models]]\nmodel = 7\ntoken = "t"\n', "must be str"),
    ],
)
def test_load_config_reports_configuration_errors(tmp_path: Path, text, message):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(tmp_path, path=path)


def test_load_config_rejects_broken_toml(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("model = \n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid config file"):
        load_config(tmp_path, path=path)
