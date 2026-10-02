"""The command line only picks the workspace; settings come from the config file."""

from pathlib import Path

import pytest

from zettcode.cli import resolve_config, workspace_from_args


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ZETTCODE_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def test_workspace_defaults_to_the_current_directory(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    assert workspace_from_args([]) == Path.cwd()


def test_workspace_comes_from_the_positional(tmp_path: Path):
    assert workspace_from_args([str(tmp_path)]) == tmp_path


def test_resolve_config_reads_the_config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "my-model"\ntoken = "secret"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    config = resolve_config([str(tmp_path)])

    assert config.models[0].model == "my-model"
    assert config.workspace == tmp_path.resolve()


def test_resolve_config_reports_a_bad_config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("nope = 1\n", encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    with pytest.raises(SystemExit) as exit_info:
        resolve_config([str(tmp_path)])

    assert "Unknown config keys" in str(exit_info.value.code)
