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
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "config.toml"))
    return HarnessLibrary(lambda: config), config, upstream


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


async def test_what_is_kept_is_the_commit_that_was_previewed_even_when_the_branch_moves_on(setup):
    harnesses, config, upstream = setup
    preview = await harnesses.preview_add("acme/todos")
    _upstream(upstream, version="9.0.0", body="x = 9\n")

    kept = await harnesses.add("acme/todos", commit=preview.commit, digest=preview.digest)

    assert kept.commit == preview.commit and kept.repositories[0].version == "1.0.0", "the shown commit, not the branch"
    moved = await harnesses.preview_update("todos")
    with pytest.raises(ValueError, match="not what was shown"):
        await harnesses.update("todos", commit=moved.commit, digest=preview.digest)


@pytest.mark.parametrize(("commit", "digest"), [("main", "0" * 64), ("a" * 40, "nope"), ("-x", "0" * 64)])
async def test_a_commit_or_digest_that_a_preview_could_not_have_reported_is_refused_before_any_download(
    setup, monkeypatch, commit, digest
):
    harnesses, _, _ = setup
    monkeypatch.setattr(library, "prepare", lambda *a, **k: pytest.fail("a download was started"))

    with pytest.raises(ValueError, match="not a (commit|digest)"):
        await harnesses.add("acme/todos", commit=commit, digest=digest)
    with pytest.raises(ValueError, match="not a (commit|digest)"):
        await harnesses.update("todos", commit=commit, digest=digest)


async def test_in_use_follows_the_configuration_file_and_remove_refuses_the_harness_every_session_works_in(
    setup, tmp_path
):
    harnesses, config, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    assert (await harnesses.entry("todos")).in_use is False

    library.write_use("todos")

    assert (await harnesses.entry("todos")).in_use is True, "a choice made by /harness use after the start is seen"
    assert [item.in_use for item in await harnesses.entries()] == [True]
    with pytest.raises(ValueError, match="every session works in"):
        await harnesses.remove("todos")
    library.write_use("")
    await harnesses.remove("todos")


async def test_a_link_is_shown_with_where_it_points_and_the_list_carries_only_a_file_count(setup):
    harnesses, _, upstream = setup
    (upstream / "notes.txt").write_text("n", encoding="utf-8")
    (upstream / "key").symlink_to("/etc/hosts")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "link")

    preview = await harnesses.preview_add("acme/todos")
    kept = await harnesses.add("acme/todos", commit=preview.commit, digest=preview.digest)

    assert preview.links == {"key": "/etc/hosts"} and "key" in preview.files
    listed = (await harnesses.entries())[0].repositories[0]
    assert listed.files == () and listed.file_count == len(kept.repositories[0].files) > 3
    assert "key" in (await harnesses.entry("todos")).repositories[0].files


async def test_an_update_whose_entry_now_comes_from_somewhere_else_is_refused(setup, tmp_path):
    harnesses, config, upstream = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    entry = library.get(config, "todos")
    prepared = library.refetch(entry, tmp_path / "scratch")
    elsewhere = library.replace(prepared, source=library.Source("https://github.com/other/thing.git", ""))

    with pytest.raises(library.LibraryError, match="somewhere else"):
        library.update(config, entry, elsewhere)


async def test_in_use_is_read_from_the_file_the_configuration_came_from(setup, tmp_path):
    harnesses, config, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    default_file = tmp_path / "config.toml"  # the one ZETTCODE_CONFIG names: the fixture points it here
    own = tmp_path / "own.toml"
    default_file.write_text('[harness]\nuse = "other"\n', encoding="utf-8")
    own.write_text('[harness]\nuse = "todos"\n', encoding="utf-8")
    given = HarnessLibrary(lambda: config, settings_file=lambda: own)

    assert (await given.entry("todos")).in_use is True and [e.in_use for e in await given.entries()] == [True]
    with pytest.raises(ValueError, match="every session works in"):
        await given.remove("todos")
    default_file.write_text('[harness]\nuse = "todos"\n', encoding="utf-8")
    own.write_text('[harness]\nuse = ""\n', encoding="utf-8")
    assert (await given.entry("todos")).in_use is False, "the default file does not decide for a process with its own"
    await given.remove("todos")


async def test_a_second_download_while_one_runs_is_refused_and_the_guard_runs_before_the_files_change(
    setup, monkeypatch
):
    import threading

    harnesses, config, upstream = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)
    _upstream(upstream, version="2.0.0", body="x = 2\n")
    preview = await harnesses.preview_update("todos")

    refused: list[str] = []

    def guard() -> None:
        refused.append("asked")
        raise ValueError("a run started")

    with pytest.raises(ValueError, match="a run started"):
        await harnesses.update("todos", commit=preview.commit, digest=preview.digest, guard=guard)
    assert refused == ["asked"] and (await harnesses.entry("todos")).repositories[0].version == "1.0.0"
    assert not list((config.harness_dir / "library").glob(".update-*")), "the staged copy is removed"

    started, release = threading.Event(), threading.Event()
    real = library.prepare

    def slow(source, workdir):
        started.set()
        release.wait(10)
        return real(source, workdir)

    monkeypatch.setattr(library, "prepare", slow)
    import asyncio

    running = asyncio.create_task(harnesses.preview_add("acme/other", name="other"))
    while not started.is_set():
        await asyncio.sleep(0.01)
    with pytest.raises(ValueError, match="already running"):
        await harnesses.preview_update("todos")
    assert (await harnesses.entries())[0].name == "todos", "reading the list is not a download and is not refused"
    release.set()
    await running


async def test_the_list_is_cheap_and_the_one_harness_has_its_state(setup):
    harnesses, _, _ = setup
    first = await harnesses.preview_add("acme/todos")
    await harnesses.add("acme/todos", commit=first.commit, digest=first.digest)

    assert [item.state for item in await harnesses.entries()] == [""]
    assert (await harnesses.entry("todos")).state in library.UPDATE_STATES
