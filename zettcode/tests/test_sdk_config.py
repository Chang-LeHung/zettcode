"""Building the configuration a client runs with: where it comes from, what is laid over it, and every way it can be wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.sdk.client import EMBEDDED_DEFAULTS, build_config
from zettcode.sdk.errors import ConfigurationError, ZettCodeError

MODEL = {"model": "gpt-x", "token": "sk-test"}


def build(workspace, *, config=None, path=None, models=None, **settings) -> ZettCodeConfig:
    return build_config(workspace, config, path, models, settings)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "from-file"\ntoken = "sk-file"\ndisplay_model = "Filey"\n\n[transcript]\ntips = false\n',
        encoding="utf-8",
    )
    return path


# -- where it comes from --------------------------------------------------------------------------


def test_models_given_in_code_need_no_config_file(workspace):
    config = build(workspace, models=[MODEL])

    assert [m.model for m in config.models] == ["gpt-x"] and config.workspace == workspace.resolve()


def test_models_may_be_entries_or_dicts_in_any_mix(workspace):
    config = build(workspace, models=[ModelConfig(**MODEL), {"model": "b", "token": "t", "multimodal": True}])

    assert [m.model for m in config.models] == ["gpt-x", "b"] and config.models[1].multimodal


def test_a_config_file_is_read_when_nothing_else_is_given(workspace, config_file):
    config = build(workspace, path=config_file)

    assert config.models[0].shown_name == "Filey" and config.tips is False


def test_a_ready_made_config_is_used_as_it_is_with_only_the_workspace_set(workspace, tmp_path):
    ready = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(**MODEL),), sessions_enabled=True)

    config = build(workspace, config=ready)

    assert config.workspace == workspace.resolve()
    assert config.sessions_enabled is True, "a configuration of your own is not second-guessed"


def test_a_ready_made_config_supplies_the_workspace_when_none_is_given(tmp_path):
    ready = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(**MODEL),))

    assert build(None, config=ready).workspace == tmp_path.resolve()


def test_with_no_workspace_and_no_config_the_current_directory_is_used(workspace, monkeypatch):
    monkeypatch.chdir(workspace)

    assert build(None, models=[MODEL]).workspace == workspace.resolve()


def test_models_win_over_a_config_file_which_is_then_not_read_at_all(workspace, tmp_path):
    broken = tmp_path / "broken.toml"
    broken.write_text("this is [ not toml", encoding="utf-8")

    config = build(workspace, models=[MODEL], path=broken)

    assert config.models[0].model == "gpt-x"


def test_the_embedding_defaults_apply_to_built_and_loaded_configurations_but_not_a_given_one(
    workspace, config_file, tmp_path
):
    assert EMBEDDED_DEFAULTS == {"sessions_enabled": False, "update_enabled": False}
    for config in (build(workspace, models=[MODEL]), build(workspace, path=config_file)):
        assert config.sessions_enabled is False and config.update_enabled is False
    ready = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(**MODEL),))
    assert build(workspace, config=ready).update_enabled is True


def test_a_setting_can_turn_an_embedding_default_back_on(workspace):
    assert build(workspace, models=[MODEL], sessions_enabled=True).sessions_enabled is True


# -- settings laid over it ------------------------------------------------------------------------


def test_settings_are_laid_over_the_configuration_by_field_name(workspace):
    config = build(workspace, models=[MODEL], skills_enabled=False, max_iterations=7, reduced_motion=True)

    assert (config.skills_enabled, config.max_iterations, config.reduced_motion) == (False, 7, True)


def test_a_path_may_be_given_as_text(workspace, tmp_path):
    config = build(
        workspace,
        models=[MODEL],
        store=str(tmp_path / "s"),
        mcp_config=str(tmp_path / "m.json"),
        skill_roots=[str(tmp_path / "skills"), tmp_path / "more"],
    )

    assert config.store == (tmp_path / "s").resolve() and config.mcp_config == tmp_path / "m.json"
    assert all(isinstance(root, Path) for root in config.skill_roots) and len(config.skill_roots) == 2


def test_a_tilde_in_a_path_setting_is_expanded(workspace):
    config = build(workspace, models=[MODEL], store="~/some-store")

    assert "~" not in str(config.store)


@pytest.mark.parametrize(
    ("name", "suggestion"),
    [("skils_enabled", "skills_enabled"), ("max_iteration", "max_iterations"), ("stor", "store")],
)
def test_a_misspelt_setting_is_reported_with_the_one_that_was_meant(workspace, name, suggestion):
    with pytest.raises(ConfigurationError, match=f"did you mean '{suggestion}'"):
        build(workspace, models=[MODEL], **{name: 1})


def test_an_unrelated_unknown_setting_is_reported_without_a_wrong_suggestion(workspace):
    with pytest.raises(ConfigurationError) as caught:
        build(workspace, models=[MODEL], qqqqqqqq=1)

    assert "qqqqqqqq" in str(caught.value) and "did you mean" not in str(caught.value)


def test_all_the_unknown_settings_are_named_at_once(workspace):
    with pytest.raises(ConfigurationError) as caught:
        build(workspace, models=[MODEL], aaa=1, zzz=2)

    assert "aaa" in str(caught.value) and "zzz" in str(caught.value)


def test_the_workspace_is_not_a_setting(workspace):
    with pytest.raises(ConfigurationError, match="first argument"):
        build_config(workspace, None, None, [MODEL], {"workspace": workspace})


@pytest.mark.parametrize(
    "bad",
    [
        {"max_iterations": "many"},
        {"max_iterations": -3},
        {"reasoning_effort": "ultra-max"},
        {"shell_approval": "sometimes"},
        {"store": 5},
        {"skill_roots": 7},
    ],
)
def test_a_value_the_configuration_cannot_hold_is_a_configuration_error_not_whatever_it_raised(workspace, bad):
    with pytest.raises(ConfigurationError):
        build(workspace, models=[MODEL], **bad)


@pytest.mark.parametrize("given", ["high", "HIGH", " High "])
def test_a_choice_may_be_given_as_text_in_any_case_and_becomes_its_enum(workspace, given):
    from zett_agent.model import ReasoningEffort

    assert build(workspace, models=[MODEL], reasoning_effort=given).reasoning_effort is ReasoningEffort.HIGH
    assert (
        build(workspace, models=[MODEL], reasoning_effort=ReasoningEffort.LOW).reasoning_effort is ReasoningEffort.LOW
    )


def test_a_choice_that_is_not_one_of_the_values_lists_them(workspace):
    with pytest.raises(ConfigurationError) as caught:
        build(workspace, models=[MODEL], shell_approval="sometimes")

    assert "review" in str(caught.value) and "allow_all" in str(caught.value) and "sometimes" in str(caught.value)


@pytest.mark.parametrize("value", [None, 3, ["high"], True])
def test_a_choice_of_the_wrong_kind_is_reported_not_passed_on(workspace, value):
    with pytest.raises(ConfigurationError, match="must be one of"):
        build(workspace, models=[MODEL], reasoning_effort=value)


# -- the workspace --------------------------------------------------------------------------------


def test_a_workspace_that_does_not_exist_is_reported(tmp_path):
    with pytest.raises(ConfigurationError, match="does not exist"):
        build(tmp_path / "nope", models=[MODEL])


def test_a_workspace_that_is_a_file_is_reported(tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("x")

    with pytest.raises(ConfigurationError, match="not a directory"):
        build(file, models=[MODEL])


def test_a_relative_and_a_tilde_workspace_resolve_to_the_directory(workspace, monkeypatch):
    monkeypatch.chdir(workspace.parent)

    assert build("project", models=[MODEL]).workspace == workspace.resolve()
    monkeypatch.setenv("HOME", str(workspace.parent))
    monkeypatch.setenv("USERPROFILE", str(workspace.parent))  # what `~` expands from on Windows
    assert build("~/project", models=[MODEL]).workspace == workspace.resolve()


def test_a_workspace_reached_through_a_symlink_is_the_real_directory(workspace, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(workspace, target_is_directory=True)

    assert build(link, models=[MODEL]).workspace == workspace.resolve()


# -- the models -----------------------------------------------------------------------------------


@pytest.mark.parametrize("models", [[], (), "gpt-x", b"x", 5, None.__class__])
def test_models_must_be_a_non_empty_list(workspace, models):
    with pytest.raises(ConfigurationError):
        build(workspace, models=models)


def test_a_model_entry_that_is_neither_a_model_nor_a_dict_is_reported_by_type(workspace):
    with pytest.raises(ConfigurationError, match="not str"):
        build(workspace, models=["gpt-x"])


@pytest.mark.parametrize(
    "entry",
    [
        {"model": "m"},
        {"token": "t"},
        {"model": "", "token": "t"},
        {"model": "m", "token": " "},
        {"model": "m", "token": "t", "nope": 1},
    ],
)
def test_an_incomplete_or_invalid_model_entry_is_reported_with_the_entry(workspace, entry):
    with pytest.raises(ConfigurationError, match="Invalid model entry"):
        build(workspace, models=[entry])


# -- the file -------------------------------------------------------------------------------------


def test_an_unreadable_config_file_is_a_configuration_error(workspace, tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[[models]\nmodel =", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid config file"):
        build(workspace, path=path)


def test_a_config_file_with_an_unknown_key_is_reported(workspace, tmp_path):
    path = tmp_path / "odd.toml"
    path.write_text('mystery = 1\n[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="mystery"):
        build(workspace, path=path)


def test_a_config_file_with_no_model_is_reported(workspace, tmp_path):
    path = tmp_path / "empty.toml"
    path.write_text("[transcript]\ntips = false\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        build(workspace, path=path)


def test_a_missing_config_file_with_no_models_is_reported_as_missing_models(workspace, tmp_path):
    with pytest.raises(ConfigurationError):
        build(workspace, path=tmp_path / "absent.toml")


def test_every_configuration_error_is_a_zettcode_error_and_a_value_error(workspace):
    with pytest.raises(ZettCodeError) as caught:
        build(workspace, models=[])

    assert isinstance(caught.value, ValueError)
