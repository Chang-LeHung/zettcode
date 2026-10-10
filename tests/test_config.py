from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.paths import DEFAULT_MCP_CONFIG


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ZETTCODE_CONFIG"):
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
        ({"anthropic": True, "token": ""}, "ANTHROPIC_API_KEY"),
        ({"anthropic": True, "responses_api": True}, "cannot use both APIs"),
    ],
)
def test_model_config_rejects_invalid_values(changes, message):
    with pytest.raises(ValueError, match=message):
        ModelConfig(**{"model": "m", "token": "t", **changes})


@pytest.mark.parametrize(
    ("written", "called_at"),
    [
        ("http://gw.test:8787/v1/messages", "http://gw.test:8787"),
        ("http://gw.test:8787/v1/messages/", "http://gw.test:8787"),
        ("https://api.openai.com/v1/responses", "https://api.openai.com/v1"),
        ("https://gw.test/v1/chat/completions", "https://gw.test/v1"),
        # Only the route goes: a prefix the API lives under stays where it is.
        ("https://gw.example/anthropic/v1/messages", "https://gw.example/anthropic"),
        ("https://gw.example/api/openai/v1/chat/completions", "https://gw.example/api/openai/v1"),
    ],
)
def test_a_base_url_that_carries_the_route_has_just_that_part_removed(written, called_at):
    """The client appends the route, so an entry that writes it out loses only the route.

    Writing the route out is a common enough reading of "the address the client
    calls" that the entry is corrected rather than refused; every request would
    otherwise go to a doubled path and come back as a 404 about an unknown
    route.
    """
    assert ModelConfig(model="m", token="t", base_url=written, anthropic=True).base_url == called_at


@pytest.mark.parametrize(
    "address",
    [
        "https://api.anthropic.com",
        "https://gw.test/anthropic",
        "https://gw.test/openai/v1",
        "http://localhost:11434/v1",
        "https://gw.test/messages",
    ],
)
def test_a_base_url_without_the_route_is_kept_as_written(address):
    """Only a value that ends with the route itself is trimmed, and it is trimmed."""
    assert ModelConfig(model="m", token="t", base_url=address, anthropic=True).base_url == address


@pytest.mark.parametrize(
    ("changes", "api"),
    [({}, "chat"), ({"responses_api": True}, "responses"), ({"anthropic": True}, "anthropic")],
)
def test_a_model_names_the_api_it_speaks(changes, api):
    """Three protocols are reachable, and one entry picks exactly one of them."""
    assert _model(**changes).api == api


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_iterations": 0}, "max_iterations"),
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


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"context_window": 0}, "context_window must be positive"),
        ({"compact_percent": 0}, "compact_percent must be between"),
        ({"compact_percent": 101}, "compact_percent must be between"),
    ],
)
def test_a_model_rejects_an_unusable_context_budget(changes, message):
    with pytest.raises(ValueError, match=message):
        ModelConfig(**{"model": "m", "token": "t", **changes})


def test_the_compaction_trigger_is_a_share_of_the_model_window():
    """One model's window and percentage decide where compaction fires."""
    model = ModelConfig(model="m", token="t", context_window=200_000, compact_percent=75)

    assert model.compaction_max_tokens == 150_000
    assert model.compaction_keep_tokens == 37_500
    # The share kept is a quarter of the trigger, never of a different window.
    small = ModelConfig(model="m", token="t", context_window=1_000, compact_percent=50)
    assert (small.compaction_max_tokens, small.compaction_keep_tokens) == (500, 125)


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
                "context_window = 200000",
                "compact_percent = 75",
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
    assert config.models[0].context_window == 200_000
    assert config.models[0].compact_percent == 75.0
    assert config.models[0].compaction_max_tokens == 150_000
    assert config.models[1].multimodal is False
    # A model that names no budget falls back to the default window and share.
    assert config.models[1].context_window == 128_000
    assert config.models[1].compact_percent == 80.0
    assert config.models[1].compaction_max_tokens == 102_400
    assert config.models[1].shown_name == "DeepSeek Chat"


def test_load_config_defaults_to_the_first_model(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    config = load_config(tmp_path, path=path)

    assert config.models[0].model == "m"
    assert config.store == (Path.home() / ".zettcode" / "sessions").resolve()
    assert config.transcript_max_entries == 1024
    assert config.skills_enabled is True
    assert config.skill_roots == ()
    assert config.mcp_enabled is True
    assert config.mcp_config is None
    assert DEFAULT_MCP_CONFIG == (Path.home() / ".zettcode" / "mcp.json")


def test_transcript_max_entries_comes_from_its_table(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[transcript]\nmax_entries = 64\n',
        encoding="utf-8",
    )

    assert load_config(tmp_path, path=path).transcript_max_entries == 64


def test_a_non_positive_transcript_cap_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="transcript_max_entries must be positive"):
        ZettCodeConfig(
            workspace=tmp_path,
            models=(_model(),),
            transcript_max_entries=0,
        )


def test_skill_roots_are_searched_before_the_default_directory(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[skills]\nroots = ["~/team-skills", ".agent/skills"]\n',
        encoding="utf-8",
    )

    config = load_config(tmp_path, path=path)
    home = Path.home()

    assert config.skill_search_roots() == (
        (home / "team-skills").resolve(),
        (tmp_path / ".agent" / "skills").resolve(),
        (home / ".zettcode" / "skills").resolve(),
    )


def test_load_config_reads_the_mcp_server_file(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[mcp]\nconfig = "~/elsewhere/mcp.json"\n',
        encoding="utf-8",
    )

    config = load_config(tmp_path, path=path)

    assert config.mcp_config == (Path.home() / "elsewhere" / "mcp.json").resolve()


def test_project_instructions_skills_and_mcp_can_be_turned_off(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[agents_md]\nenabled = false\n'
        "\n[ask_user]\nenabled = false\n"
        "\n[skills]\nenabled = false\n\n[mcp]\nenabled = false\n\n[update]\nenabled = false\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path, path=path)

    assert config.agents_md_enabled is False
    assert config.ask_user_enabled is False
    assert config.skills_enabled is False
    assert config.mcp_enabled is False
    assert config.update_enabled is False


def test_the_harness_switches_default_to_a_task_tool_without_a_plan(tmp_path: Path):
    """``task`` is on, ``todo_write`` is off, and the file may say either way."""
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    defaults = load_config(tmp_path, path=path)
    assert defaults.subagent_enabled is True
    assert defaults.todowrite_enabled is False

    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[harness]\nsubagent = false\ntodowrite = true\n',
        encoding="utf-8",
    )
    configured = load_config(tmp_path, path=path)
    assert configured.subagent_enabled is False
    assert configured.todowrite_enabled is True


def test_the_release_check_is_on_unless_the_config_turns_it_off(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    config = load_config(tmp_path, path=path)

    assert config.update_enabled is True
    assert config.update_file == (Path.home() / ".zettcode" / "update.json").resolve()


def test_project_instructions_are_read_unless_the_config_turns_them_off(tmp_path: Path):
    """AGENTS.md is the one integration a project cannot opt into by accident."""
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    assert load_config(tmp_path, path=path).agents_md_enabled is True


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


def test_an_anthropic_model_takes_the_key_named_after_its_api(tmp_path: Path, monkeypatch):
    """An Anthropic entry reads ``ANTHROPIC_API_KEY``, not an OpenAI-named variable."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "from-openai")
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "claude-sonnet-4-5"\nanthropic = true\n', encoding="utf-8")

    model = load_config(tmp_path, path=path).models[0]

    assert model.token == "from-anthropic"
    assert model.anthropic is True
    assert model.responses_api is False
    assert model.api == "anthropic"


def test_load_config_removes_the_route_a_base_url_writes_out(tmp_path: Path):
    """A file may write the route out; the route is what the client adds itself."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "claude-sonnet-4-5"\nanthropic = true\nbase_url = "http://gw.test:8787/v1/messages"\ntoken = "t"\n',
        encoding="utf-8",
    )

    model = load_config(tmp_path, path=path).models[0]

    assert model.base_url == "http://gw.test:8787"
    assert model.api == "anthropic"


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
        ('[[models]]\nmodel = "m"\nanthropic = "yes"\ntoken = "t"\n', "must be bool"),
        (
            '[[models]]\nmodel = "m"\nanthropic = true\nresponses_api = true\ntoken = "t"\n',
            "cannot use both APIs",
        ),
        ('[[models]]\nmodel = 7\ntoken = "t"\n', "must be str"),
        ('[[models]]\nmodel = "m"\ncontext_window = 1.5\ntoken = "t"\n', "context_window' must be int"),
        ('[[models]]\nmodel = "m"\ncontext_window = true\ntoken = "t"\n', "context_window' must be int"),
        ('[[models]]\nmodel = "m"\ncompact_percent = "80"\ntoken = "t"\n', "compact_percent' must be a number"),
        ('[[models]]\nmodel = "m"\ncompact_percent = true\ntoken = "t"\n', "compact_percent' must be a number"),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nrotos = ["."]\n',
            "Unknown config keys in the \\[skills\\] table",
        ),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nroots = "~/.skills"\n', "must be an array of strings"),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nroots = [7]\n', "must be an array of strings"),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[skills]\nenabled = "yes"\n', "must be bool"),
        ('mcp = "off"\n[[models]]\nmodel = "m"\ntoken = "t"\n', "must be a table"),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[mcp]\nconfig = 7\n', "must be str"),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[transcript]\nmax_entries = true\n',
            "transcript.max_entries'.*must be int",
        ),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[transcript]\nmax = 64\n',
            "Unknown config keys in the \\[transcript\\] table",
        ),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[agents_md]\nfile = "CLAUDE.md"\n',
            "Unknown config keys in the \\[agents_md\\] table",
        ),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[agents_md]\nenabled = "yes"\n', "must be bool"),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[ask_user]\nask = "sometimes"\n',
            "Unknown config keys in the \\[ask_user\\] table",
        ),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[ask_user]\nenabled = "yes"\n', "must be bool"),
        (
            '[[models]]\nmodel = "m"\ntoken = "t"\n[update]\ninterval = "daily"\n',
            "Unknown config keys in the \\[update\\] table",
        ),
        ('[[models]]\nmodel = "m"\ntoken = "t"\n[update]\nenabled = "yes"\n', "must be bool"),
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
