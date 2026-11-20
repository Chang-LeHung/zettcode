"""``client.harnesses``: the user-level harness library as methods, with a download seen before it is kept."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import harness_library as library
from zettcode.engine.harness_library import Source
from zettcode.sdk.harness_library import HarnessLibrary


class _Client:
    """What the library asks of a client: its configuration, and whether it is open."""

    def __init__(self, config: ZettCodeConfig) -> None:
        self.config = config

    def _check_open(self) -> None:
        return None


def _git(cwd: Path, *arguments: str) -> str:
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(
        ["git", *arguments], cwd=cwd, env=environment, check=True, capture_output=True, text=True
    ).stdout.strip()


def _upstream(path: Path, *, version: str = "1.0.0", body: str = "x = 1\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text(body, encoding="utf-8")
    (path / "MANIFEST").write_text(
        f'name = "todos"\nversion = "{version}"\ndescription = "Find TODOs."\ntools = ["list_todos"]\n',
        encoding="utf-8",
    )
    if not (path / ".git").exists():
        _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "change")
    return path


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "work").mkdir()
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    upstream = _upstream(tmp_path / "upstream")
    monkeypatch.setattr(library, "parse_source", lambda text: Source(str(upstream), ""))
    return HarnessLibrary(_Client(config)), config, upstream  # type: ignore[arg-type]


async def test_a_preview_keeps_nothing_and_what_it_showed_is_what_add_keeps(setup):
    harnesses, config, upstream = setup

    preview = await harnesses.preview_add("acme/todos")

    assert preview.action == "add" and preview.name == "todos" and preview.tools == ("list_todos",)
    assert "__init__.py" in preview.files and preview.caution
    assert await harnesses.entries() == []
    kept = await harnesses.add("acme/todos", commit=preview.commit, digest=preview.digest)
    assert kept.name == "todos" and kept.commit == preview.commit and kept.state == "ok"
    assert kept.repositories[0].tools == ("list_todos",) and "__init__.py" in kept.repositories[0].files
    assert [entry.name for entry in await harnesses.entries()] == ["todos"]
    assert (await harnesses.entry("todos")).in_use is False


async def test_add_refuses_a_download_that_is_not_what_was_shown(setup):
    harnesses, _, upstream = setup
    preview = await harnesses.preview_add("acme/todos")

    with pytest.raises(ValueError, match="not what was shown"):
        await harnesses.add("acme/todos", commit=preview.commit, digest="0" * 64)

    assert await harnesses.entries() == []


async def test_a_name_that_is_taken_is_refused_at_the_preview(setup):
    harnesses, _, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)

    with pytest.raises(ValueError, match="already in the library"):
        await harnesses.preview_add("acme/todos")


async def test_an_update_shows_what_changes_and_keeps_the_branch_it_was_installed_from(setup):
    harnesses, config, upstream = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    _upstream(upstream, version="2.0.0", body="x = 2\n")

    preview = await harnesses.preview_update("todos")

    assert preview.action == "update" and not preview.up_to_date and preview.commit != first.commit
    assert any("version: 1.0.0 -> 2.0.0" in line for line in preview.changes)
    kept = await harnesses.update("todos", commit=preview.commit, digest=preview.digest)
    assert kept.commit == preview.commit and kept.repositories[0].version == "2.0.0"
    assert library.get(config, "todos").source["ref"] == "", "the pinned commit is not recorded as the reader's ref"
    assert (await harnesses.preview_update("todos")).up_to_date


async def test_an_update_of_a_changed_harness_is_refused_and_fork_keeps_the_changes(setup):
    harnesses, config, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    (config.harness_dir / "library" / "todos" / "todos" / "extra.py").write_text("y = 1\n", encoding="utf-8")

    assert (await harnesses.entry("todos")).state == "changed"
    with pytest.raises(ValueError, match="fork"):
        await harnesses.preview_update("todos")
    copy = await harnesses.fork("todos", "mine")
    assert copy.origin == "fork of todos" and "extra.py" in copy.repositories[0].files


async def test_remove_deletes_it_and_an_unknown_name_is_a_value_error(setup):
    harnesses, _, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)

    await harnesses.remove("todos")

    assert await harnesses.entries() == []
    with pytest.raises(ValueError, match="no harness called"):
        await harnesses.entry("todos")
