"""The suite never reaches the developer's real home directory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from zettcode import paths
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.storage import SessionStore


def _inside_the_temp_home(path: Path) -> bool:
    return Path(tempfile.gettempdir()).resolve() in path.resolve().parents


def test_the_home_directory_is_a_temporary_one():
    """`conftest` sets it before any module computes a default from it."""
    assert _inside_the_temp_home(Path.home())
    assert Path.home().name.startswith("zettcode-test-home-")


def test_every_default_path_the_program_has_lives_in_it():
    """Each is `Path.home() / ".zettcode" / ...` computed on import, so one moved HOME moves all."""
    for path in (
        paths.CONFIG_FILE,
        paths.DEFAULT_STORE,
        paths.DEFAULT_MCP_CONFIG,
        paths.DEFAULT_UPDATE_FILE,
        paths.DEFAULT_TOKENIZER_CACHE,
        paths.DEFAULT_LOG,
    ):
        assert _inside_the_temp_home(path), f"{path} would write into a real home"


def test_a_config_that_names_no_store_uses_the_temporary_one(tmp_path: Path):
    """The leak: `resolve_config(["-w", tmp_path])` builds a config without a store."""
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),))

    assert _inside_the_temp_home(config.store)
    assert _inside_the_temp_home(SessionStore(config.store, tmp_path).root)


def test_the_store_default_of_the_session_store_itself_is_covered_too(tmp_path: Path):
    assert _inside_the_temp_home(SessionStore(workspace=tmp_path).root)


def test_the_windows_spelling_of_home_is_set_as_well():
    assert os.environ["USERPROFILE"] == os.environ["HOME"]
