"""The harness library: a repository that meets the harness format is kept by name, updated, copied and removed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import harness_library as library
from zettcode.engine.harness_library import GitMissingError, LibraryError, Source


def _config(tmp_path: Path, *, use: str = "") -> ZettCodeConfig:
    (tmp_path / "work").mkdir(exist_ok=True)
    return ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        harness_use=use,
        mcp_enabled=False,
    )


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


def _repository(
    path: Path, *, name: str = "todos", version: str = "1.0.0", tools: str = '"list_todos"', body: str = "x = 1\n"
) -> Path:
    """Write a harness repository and commit it; ``path`` is a local git repository the tests download from."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text(body, encoding="utf-8")
    (path / "MANIFEST").write_text(
        f'name = "{name}"\nversion = "{version}"\ndescription = "Find TODOs."\ntools = [{tools}]\n', encoding="utf-8"
    )
    if not (path / ".git").exists():
        _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "change")
    return path


def _download(source: Path, tmp_path: Path, name: str = "download") -> library.Prepared:
    return library.prepare(Source(str(source)), tmp_path / name)


def test_a_source_is_owner_repo_with_an_optional_ref():
    assert library.parse_source("acme/todos") == Source("https://github.com/acme/todos.git", "")
    assert library.parse_source("acme/todos@v2") == Source("https://github.com/acme/todos.git", "v2")
    assert library.parse_source("https://github.com/acme/todos.git@main") == Source(
        "https://github.com/acme/todos.git", "main"
    )
    assert library.parse_source("https://github.com/acme/todos/") == Source("https://github.com/acme/todos.git", "")
    assert library.parse_source("acme/todos").shown() == "acme/todos"
    assert library.parse_source("acme/todos@v2").shown() == "acme/todos@v2"


@pytest.mark.parametrize("text", ["todos", "acme/", "/todos", "acme/todos@-x", "https://example.com/a/b", "a b/c"])
def test_anything_that_is_not_a_github_repository_is_refused(text: str):
    with pytest.raises(LibraryError):
        library.parse_source(text)


def test_a_repository_that_meets_the_format_is_described_before_anything_is_kept(tmp_path: Path):
    source = _repository(tmp_path / "upstream")

    prepared = _download(source, tmp_path)

    assert prepared.candidate.name == "todos" and prepared.candidate.version == "1.0.0"
    assert prepared.candidate.tools == ("list_todos",)
    assert sorted(prepared.candidate.files) == ["MANIFEST", "__init__.py"], "git's own folder is not a file of it"
    assert prepared.commit == _git(source, "rev-parse", "HEAD")
    assert library.entries(_config(tmp_path)) == [], "nothing is kept until install says so"


def test_a_repository_without_a_manifest_is_not_a_harness(tmp_path: Path):
    source = _repository(tmp_path / "upstream")
    (source / "MANIFEST").unlink()
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "drop it")

    with pytest.raises(LibraryError, match="not a harness repository"):
        _download(source, tmp_path)


def test_a_repository_without_an_init_file_is_not_a_harness(tmp_path: Path):
    source = tmp_path / "upstream"
    source.mkdir()
    (source / "README.md").write_text("hi\n", encoding="utf-8")
    (source / "MANIFEST").write_text('name = "todos"\nversion = "1"\ndescription = "d"\n', encoding="utf-8")
    _git(source, "init", "-q")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "readme")

    with pytest.raises(LibraryError, match="no __init__.py"):
        _download(source, tmp_path)


def test_a_download_is_not_limited_and_a_symbolic_link_is_kept_as_the_link_it_is(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    (source / "data").mkdir()
    for number in range(600):
        (source / "data" / f"f{number}.txt").write_text("x" * 10_000, encoding="utf-8")
    os.symlink("data/f1.txt", source / "link.txt")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "many files and a link")

    prepared = _download(source, tmp_path)
    entry = library.install(config, prepared)

    assert len(prepared.candidate.files) > 600, "the reader asked for this repository: there is no size limit"
    link = entry.path / "todos" / "link.txt"
    assert link.is_symlink() and os.readlink(link).replace("\\", "/") == "data/f1.txt"
    assert library.modified(entry) is False
    copy = library.fork(config, "todos", "copy")
    assert (copy.path / "todos" / "link.txt").is_symlink()


def test_install_keeps_the_files_without_git_and_records_where_they_came_from(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")

    entry = library.install(config, _download(source, tmp_path))

    assert entry.name == "todos" and entry.repositories == ("todos",)
    assert (entry.path / "todos" / "__init__.py").is_file() and not (entry.path / "todos" / ".git").exists()
    assert entry.commit == _git(source, "rev-parse", "HEAD")
    assert str(source) in entry.origin
    assert library.get(config, "todos").path == entry.path
    assert [item.name for item in library.entries(config)] == ["todos"]


def test_install_under_another_name_and_never_over_an_existing_one(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    library.install(config, _download(source, tmp_path), name="mine")

    with pytest.raises(LibraryError, match="already in the library"):
        library.install(config, _download(source, tmp_path, "again"), name="mine")
    with pytest.raises(LibraryError, match="not a harness name"):
        library.install(config, _download(source, tmp_path, "third"), name="../escape")

    assert [item.name for item in library.entries(config)] == ["mine"]


def test_an_entry_is_changed_when_a_file_of_it_differs_from_what_was_installed(tmp_path: Path):
    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    assert library.modified(entry) is False

    (entry.path / "todos" / "extra.py").write_text("y = 2\n", encoding="utf-8")

    assert library.modified(entry) is True


def test_update_replaces_the_repository_with_the_newer_commit(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, version="1.1.0", body="x = 2\n")

    newer = library.refetch(entry, tmp_path / "again")
    updated = library.update(config, entry, newer)

    assert newer.commit != entry.commit and updated.commit == newer.commit
    assert (updated.path / "todos" / "__init__.py").read_text(encoding="utf-8") == "x = 2\n"
    assert library.modified(updated) is False


def test_update_refuses_to_overwrite_changes_unless_forced(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    (entry.path / "todos" / "mine.py").write_text("mine = 1\n", encoding="utf-8")
    _repository(source, version="1.1.0", body="x = 3\n")
    newer = library.refetch(entry, tmp_path / "again")

    with pytest.raises(LibraryError, match="fork"):
        library.update(config, entry, newer)
    assert (entry.path / "todos" / "mine.py").is_file(), "a refused update touched nothing"

    forced = library.update(config, entry, newer, force=True)
    assert not (forced.path / "todos" / "mine.py").exists() and forced.commit == newer.commit


def test_fork_copies_the_harness_without_an_upstream_so_the_copy_can_change(tmp_path: Path):
    config = _config(tmp_path)
    original = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))

    copy = library.fork(config, "todos", "my-todos")
    (copy.path / "todos" / "more.py").write_text("z = 1\n", encoding="utf-8")

    assert copy.origin == "fork of todos" and library.modified(copy) is None
    assert not (original.path / "todos" / "more.py").exists(), "the original is not touched by the copy's changes"
    with pytest.raises(LibraryError, match="no upstream"):
        library.refetch(copy, tmp_path / "x")
    with pytest.raises(LibraryError, match="already in the library"):
        library.fork(config, "todos", "my-todos")


def _session_harness(config: ZettCodeConfig, session: str, *, manifest: bool = True) -> Path:
    from zettcode.engine.harness_paths import session_path

    folder = session_path(config, session)
    (folder / "kit").mkdir(parents=True)
    (folder / "kit" / "__init__.py").write_text("", encoding="utf-8")
    if manifest:
        (folder / "kit" / "MANIFEST").write_text(
            'name = "kit"\nversion = "1"\ndescription = "Kit."\n', encoding="utf-8"
        )
    return folder


def test_a_harness_folder_can_be_kept_in_the_library_when_a_session_could_load_it(tmp_path: Path):
    config = _config(tmp_path)
    folder = _session_harness(config, "s1")

    entry = library.keep(config, folder, "from-s1", origin="session s1")

    assert entry.repositories == ("kit",) and entry.origin == "fork of session s1"
    with pytest.raises(LibraryError, match="no harness repository"):
        library.keep(config, tmp_path / "nobody", "empty", origin="x")
    with pytest.raises(LibraryError, match="already in the library"):
        library.keep(config, folder, "from-s1", origin="session s1")


def test_a_repository_no_session_could_load_is_not_kept_and_leaves_nothing_behind(tmp_path: Path):
    config = _config(tmp_path)
    folder = _session_harness(config, "s2", manifest=False)

    with pytest.raises(LibraryError, match="cannot be loaded"):
        library.keep(config, folder, "broken", origin="session s2")

    assert library.entries(config) == [] and not (library.library_root(config) / "broken").exists()


def test_keeping_a_folder_copies_a_link_as_a_link_and_never_the_file_it_points_at(tmp_path: Path):
    config = _config(tmp_path)
    folder = _session_harness(config, "s3")
    secret = tmp_path / "secret.txt"
    secret.write_text("token", encoding="utf-8")
    os.symlink(secret, folder / "kit" / "leak.txt")

    entry = library.keep(config, folder, "linked", origin="session s3")

    copied = entry.path / "kit" / "leak.txt"
    assert copied.is_symlink(), "the secret's contents did not reach the library"


def test_a_name_in_source_json_that_is_not_a_folder_name_is_no_record(tmp_path: Path):
    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("mine", encoding="utf-8")
    record = entry.path / "SOURCE.json"
    record.write_text(record.read_text(encoding="utf-8").replace('"todos"', '"../../outside"'), encoding="utf-8")

    damaged = library.get(config, "todos")
    newer = _download(_repository(tmp_path / "upstream", version="2.0.0", body="x = 9\n"), tmp_path, "again")

    assert library.modified(damaged) is None, "a record that is not a folder name compares with nothing"
    with pytest.raises(LibraryError, match="already holds a repository called `todos`"):
        library.update(config, damaged, newer, force=True)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine", "update deleted nothing it was pointed at"
    assert (entry.path / "todos" / "__init__.py").read_text(encoding="utf-8") == "x = 1\n", (
        "nor anything of the entry's"
    )


def test_an_update_that_fails_part_way_leaves_the_old_repository_where_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, version="1.1.0", body="x = 5\n")
    newer = library.refetch(entry, tmp_path / "again")

    def broken(_source: Path, _target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(library, "_copy_tree", broken)
    with pytest.raises(OSError, match="disk full"):
        library.update(config, entry, newer)

    assert (entry.path / "todos" / "__init__.py").read_text(encoding="utf-8") == "x = 1\n"
    assert library.modified(library.get(config, "todos")) is False, "the entry is still one that can be updated"


def test_a_file_that_cannot_be_read_counts_as_a_change_instead_of_breaking_the_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))

    def unreadable(_directory: Path) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(library, "tree_digest", unreadable)

    assert library.modified(entry) is True, "an OSError while hashing is a change, not an exception"


def test_a_link_whose_target_is_gone_is_a_change(tmp_path: Path):
    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    os.symlink(tmp_path / "gone", entry.path / "todos" / "dangling.py")

    assert library.modified(entry) is True


def test_an_update_stages_outside_the_entry_and_leaves_nothing_behind(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, version="1.1.0", body="x = 7\n")

    updated = library.update(config, entry, library.refetch(entry, tmp_path / "again"))

    assert sorted(item.name for item in updated.path.iterdir()) == ["SOURCE.json", "todos"], "no staging in the entry"
    assert [item.name for item in library.library_root(config).iterdir() if item.name.startswith(".update-")] == []
    assert library.get(config, "todos").commit == updated.commit


def test_an_update_whose_record_cannot_be_written_puts_the_old_repository_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, version="1.1.0", body="x = 8\n")
    newer = library.refetch(entry, tmp_path / "again")

    def refuse(_path: Path, _record: dict[str, object]) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(library, "_write_source", refuse)
    with pytest.raises(OSError, match="read-only"):
        library.update(config, entry, newer)

    assert (entry.path / "todos" / "__init__.py").read_text(encoding="utf-8") == "x = 1\n"
    assert library.modified(library.get(config, "todos")) is False, "digest and files still agree: updatable"


def test_a_renamed_repository_is_removed_only_after_the_new_one_is_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, name="renamed", version="2.0.0")
    newer = library.refetch(entry, tmp_path / "again")
    monkeypatch.setattr(library, "_write_source", lambda *_a: (_ for _ in ()).throw(OSError("read-only")))

    with pytest.raises(OSError):
        library.update(config, entry, newer, force=True)

    assert (entry.path / "todos").is_dir() and not (entry.path / "renamed").exists()


def test_two_updates_of_one_entry_do_not_run_at_once(tmp_path: Path):
    from zettcode.filelock import SingletonLock

    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    _repository(source, version="1.1.0", body="x = 4\n")
    newer = library.refetch(entry, tmp_path / "again")
    holder = SingletonLock(library.library_root(config) / ".todos.lock")
    assert holder.acquire()
    try:
        with pytest.raises(LibraryError, match="being updated by another process"):
            library.update(config, entry, newer)
    finally:
        holder.release()


def test_git_gets_neither_the_repository_nor_the_configuration_variables_a_caller_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen: dict[str, object] = {}

    def fake_run(arguments, **keywords):
        seen["arguments"] = arguments
        seen["env"] = keywords["env"]
        return subprocess.CompletedProcess(arguments, 0, stdout="ok\n", stderr="")

    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.sshCommand")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "evil")
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/tmp/evil.gitconfig")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/tmp/evil.gitconfig")
    monkeypatch.setattr(library.subprocess, "run", fake_run)
    monkeypatch.setattr(library.shutil, "which", lambda _name: "/usr/bin/git")

    library._git(["status"], tmp_path)

    names = set(seen["env"])  # type: ignore[arg-type]
    assert not names & {
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_DIR",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
    }
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"  # type: ignore[index]
    arguments = " ".join(seen["arguments"])  # type: ignore[arg-type]
    for closed in ("core.hooksPath=", "core.fsmonitor=", "filter.lfs.smudge=", "filter.lfs.required=false"):
        assert closed in arguments, f"{closed} is not closed for a download"


def test_git_is_run_without_the_environment_that_points_it_at_another_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = _repository(tmp_path / "upstream")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _git(elsewhere, "init", "-q")
    expected = _git(source, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))

    prepared = _download(source, tmp_path)

    assert prepared.commit == expected
    assert not list(elsewhere.glob("MANIFEST")), "the download did not land in the repository the hook named"


def test_remove_deletes_the_entry_but_not_the_one_every_session_works_in(tmp_path: Path):
    config = _config(tmp_path, use="todos")
    library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))

    with pytest.raises(LibraryError, match="use --none"):
        library.remove(config, "todos")

    library.remove(_config(tmp_path), "todos")
    assert library.entries(config) == []
    with pytest.raises(LibraryError, match="no harness called"):
        library.get(config, "todos")


def test_without_git_the_reader_is_told_to_install_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(library.shutil, "which", lambda _name: None)

    with pytest.raises(GitMissingError, match="install git first"):
        _download(tmp_path / "anything", tmp_path)


def test_an_entry_with_an_upstream_but_no_digest_is_refused_not_overwritten(tmp_path: Path):
    import json

    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    record = entry.path / "SOURCE.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["digest"]
    record.write_text(json.dumps(data), encoding="utf-8")
    (entry.path / "todos" / "mine.py").write_text("work = 1\n", encoding="utf-8")
    _repository(source, version="1.1.0", body="x = 6\n")
    damaged = library.get(config, "todos")

    with pytest.raises(LibraryError, match="SOURCE.json no longer says"):
        library.update(config, damaged, library.refetch(damaged, tmp_path / "again"))
    assert (entry.path / "todos" / "mine.py").is_file(), "nobody could say it was unchanged, so nothing was replaced"


def test_a_fork_is_not_a_damaged_record(tmp_path: Path):
    config = _config(tmp_path)
    library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    copy = library.fork(config, "todos", "mine")

    assert library.modified(copy) is None and not library._record_damaged(copy)


def test_an_update_never_moves_aside_a_repository_the_entry_did_not_install(tmp_path: Path):
    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    own = entry.path / "renamed"
    own.mkdir()
    (own / "__init__.py").write_text("work = 1\n", encoding="utf-8")
    _repository(source, name="renamed", version="2.0.0")
    newer = library.refetch(entry, tmp_path / "again")

    with pytest.raises(LibraryError, match="already holds a repository called `renamed`"):
        library.update(config, entry, newer, force=True)

    assert (own / "__init__.py").read_text(encoding="utf-8") == "work = 1\n"
    assert [item.name for item in library.library_root(config).iterdir() if item.name.startswith(".update-")] == []


def test_a_harness_cannot_be_removed_while_it_is_being_updated(tmp_path: Path):
    from zettcode.filelock import SingletonLock

    config = _config(tmp_path)
    library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    holder = SingletonLock(library.library_root(config) / ".todos.lock")
    assert holder.acquire()
    try:
        with pytest.raises(LibraryError, match="being updated by another process"):
            library.remove(config, "todos")
    finally:
        holder.release()

    library.remove(config, "todos")
    assert library.entries(config) == []


def test_fingerprints_never_read_through_a_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "real.py").write_text("x = 1\n", encoding="utf-8")
    os.symlink("/dev/zero", tree / "zero")
    real_read = Path.read_bytes

    def guarded(self: Path) -> bytes:
        if self.name == "zero":
            raise AssertionError("a link was read through")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)

    found = library.tree_fingerprints(tree)

    assert found["zero"] == "link:/dev/zero" and found["real.py"].startswith("file:")
    assert library.tree_digest(tree), "the digest of a tree with a link is computed without reading it either"


def test_source_json_is_replaced_whole_never_half_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    before = (entry.path / "SOURCE.json").read_text(encoding="utf-8")
    import zettcode.config_edit as edit

    def failing(_path: Path, _text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(edit, "write_text_atomically", failing)
    with pytest.raises(OSError, match="disk full"):
        library._write_source(entry.path, {"url": "x"})

    assert (entry.path / "SOURCE.json").read_text(encoding="utf-8") == before, "the old record is untouched"


def test_an_entry_is_ok_changed_missing_or_damaged_and_an_update_says_which(tmp_path: Path):
    import json
    import shutil

    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    assert library.update_state(entry) == "ok" and library.update_refusal(config, entry, force=False) is None

    (entry.path / "todos" / "extra.py").write_text("y = 1\n", encoding="utf-8")
    assert library.update_state(entry) == "changed"
    changed_message = library.update_refusal(config, entry, force=False) or ""
    assert "fork todos" in changed_message
    # The VS Code panel offers "Update anyway" by looking for this exact phrase (clients/vscode/src/harnesses.ts).
    assert "`update --force`" in changed_message
    assert library.update_refusal(config, entry, force=True) is None, "--force is the reader's decision"

    (entry.path / "todos" / "extra.py").unlink()
    leftover = library.library_root(config) / ".update-abc" / "previous"
    shutil.move(str(entry.path / "todos"), str(leftover))
    missing = library.update_state(entry)
    message = library.update_refusal(config, entry, force=False) or ""
    assert missing == "missing", "a repository that is gone is not 'changed'"
    assert "lost its repository" in message and ".update-abc" in message, "it names where the old tree is"
    assert "fork" not in message.split("`update --force`")[0], "it does not advise a fork of nothing"

    shutil.move(str(leftover), str(entry.path / "todos"))
    record = entry.path / "SOURCE.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["digest"]
    record.write_text(json.dumps(data), encoding="utf-8")
    assert library.update_state(library.get(config, "todos")) == "damaged"


def test_force_does_not_replace_a_same_named_repository_the_entry_did_not_install_either(tmp_path: Path):
    import json

    config = _config(tmp_path)
    source = _repository(tmp_path / "upstream")
    entry = library.install(config, _download(source, tmp_path))
    record = entry.path / "SOURCE.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["repository"]
    del data["digest"]
    record.write_text(json.dumps(data), encoding="utf-8")
    _repository(source, version="1.1.0", body="x = 2\n")
    damaged = library.get(config, "todos")

    with pytest.raises(LibraryError, match="already holds a repository called `todos`"):
        library.update(config, damaged, library.refetch(damaged, tmp_path / "again"), force=True)

    assert (entry.path / "todos" / "__init__.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_leftover_staging_folder_is_swept_once_nothing_needs_it_and_kept_while_it_holds_the_only_copy(tmp_path: Path):
    import shutil

    config = _config(tmp_path)
    entry = library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    root = library.library_root(config)
    harmless = root / ".update-harmless"
    (harmless / "todos").mkdir(parents=True)
    assert library.sweep_leftovers(config) == 1 and not harmless.exists()

    sole = root / ".update-sole" / "previous"
    shutil.move(str(entry.path / "todos"), str(sole))
    assert library.update_state(library.get(config, "todos")) == "missing"
    assert library.sweep_leftovers(config) == 0 and sole.is_dir(), "the only copy of the old tree is never swept"

    shutil.move(str(sole), str(entry.path / "todos"))
    assert library.sweep_leftovers(config) == 1 and not sole.parent.exists()


def test_a_staging_folder_is_not_swept_while_an_update_holds_a_lock(tmp_path: Path):
    from zettcode.filelock import SingletonLock

    config = _config(tmp_path)
    library.install(config, _download(_repository(tmp_path / "upstream"), tmp_path))
    root = library.library_root(config)
    staging = root / ".update-live"
    (staging / "todos").mkdir(parents=True)
    holder = SingletonLock(root / ".todos.lock")
    assert holder.acquire()
    try:
        assert library.sweep_leftovers(config) == 0 and staging.is_dir(), "an update in progress keeps its folder"
    finally:
        holder.release()
    assert library.sweep_leftovers(config) == 1


def test_changes_name_the_version_the_tools_and_the_files_and_cut_a_long_list(tmp_path: Path):
    old = _repository(tmp_path / "before" / "todos", version="1.0.0", tools='"a"')
    new = _repository(tmp_path / "new", version="2.0.0", tools='"b"')
    for index in range(5):
        (new / f"f{index}.py").write_text("y\n", encoding="utf-8")
    _git(new, "add", "-A")
    _git(new, "commit", "-q", "-m", "more")
    prepared = _download(new, tmp_path)

    lines = library.changes(old, prepared, limit=2)

    assert "version: 1.0.0 -> 2.0.0" in lines and "tools removed: a" in lines and "tools added: b" in lines
    assert any(line.startswith("files added: ") and line.endswith(" ...") for line in lines)


def test_a_link_that_now_points_elsewhere_is_a_changed_file(tmp_path: Path):
    old = _repository(tmp_path / "old")
    (old / "k").symlink_to("one")
    new = _repository(tmp_path / "new")
    (new / "k").symlink_to("two")
    _git(new, "add", "-A")
    _git(new, "commit", "-q", "-m", "link")

    lines = library.changes(old, _download(new, tmp_path))

    assert any(line.startswith("files changed:") and "k" in line for line in lines)


def test_describe_reports_an_unreadable_manifest_and_never_a_repository_that_is_a_link(tmp_path: Path):
    config = _config(tmp_path)
    library.install(config, _download(_repository(tmp_path / "up"), tmp_path))
    entry = library.get(config, "todos")
    (entry.path / "todos" / "MANIFEST").write_text("not = [valid", encoding="utf-8")
    (entry.path / "alias").symlink_to(entry.path / "todos", target_is_directory=True)

    info = library.describe(config, library.get(config, "todos"))

    assert [item.name for item in info.repositories] == ["todos"], "a linked folder is not a repository"
    assert info.repositories[0].error and info.repositories[0].file_count == len(info.repositories[0].files)
    light = library.describe(config, entry, detail=False)
    assert light.repositories[0].files == () and light.state == "", "the cheap form reads no bytes and names no files"
    assert light.repositories[0].file_count == info.repositories[0].file_count


def test_a_commit_and_a_digest_are_what_a_preview_reports_and_nothing_else():
    assert library.valid_commit("a" * 40) == "a" * 40 and library.valid_digest("0" * 64) == "0" * 64
    for bad in ("", "main", "A" * 40, "a" * 39, "-" + "a" * 39):
        with pytest.raises(LibraryError, match="not a commit"):
            library.valid_commit(bad)
    with pytest.raises(LibraryError, match="not a digest"):
        library.valid_digest("a" * 40)
