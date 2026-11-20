"""``zettcode harness``: add, show, list, update, fork and remove harnesses of the library (use and save are /harness)."""

from __future__ import annotations

import builtins
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zettcode import cli, harness_cli
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import harness_library as library
from zettcode.engine.harness_library import Source


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
    """A config under the test's directory, a local git repository standing in for GitHub, and a config file."""
    config = _config(tmp_path)
    monkeypatch.setattr(harness_cli, "_config", lambda: _config(tmp_path, use=_used[0]))
    _used.clear()
    _used.append("")
    upstream = _upstream(tmp_path / "upstream")
    monkeypatch.setattr(library, "parse_source", lambda text: Source(str(upstream)))
    file = tmp_path / "config.toml"
    monkeypatch.setenv("ZETTCODE_CONFIG", str(file))
    return config, upstream, file


#: What ``[harness] use`` reads as for the config the fixture hands the command.
_used: list[str] = [""]


def _run(*arguments: str) -> int:
    return harness_cli.harness_program(list(arguments))


def test_an_empty_library_says_how_to_fill_it(setup, capsys):
    assert _run("list") == 0
    assert "harness add owner/repo" in capsys.readouterr().out


def test_add_shows_what_it_is_and_keeps_it_only_after_a_yes(setup, capsys):
    config, upstream, _ = setup

    assert _run("add", "acme/todos", "-y") == 0

    out = capsys.readouterr().out
    assert "todos 1.0.0" in out and "list_todos" in out and "Find TODOs." in out
    assert "MANIFEST" in out and "__init__.py" in out, "the files are listed before anything is kept"
    assert "runs on this machine" in out, "the reader is told what loading it means"
    assert _git(upstream, "rev-parse", "HEAD") in out
    assert [entry.name for entry in library.entries(config)] == ["todos"]
    assert "/harness use todos" in out, "it says where sessions are pointed at it: inside ZettCode, not here"


def test_without_a_yes_and_without_a_terminal_nothing_is_kept_and_it_is_a_failure(setup, capsys, monkeypatch):
    config, _, _ = setup
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert _run("add", "acme/todos") == 1

    assert "pass -y" in capsys.readouterr().err
    assert library.entries(config) == []


def test_a_no_keeps_nothing_and_is_not_a_failure_and_a_yes_keeps_it(setup, capsys, monkeypatch):
    config, _, _ = setup
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "n")

    assert _run("add", "acme/todos") == 0, "the reader decided; `add && something` is theirs to read"
    assert library.entries(config) == [] and "Nothing was kept" in capsys.readouterr().out

    monkeypatch.setattr(builtins, "input", lambda _prompt="": "y")
    assert _run("add", "acme/todos", "--as", "my-todos") == 0
    assert [entry.name for entry in library.entries(config)] == ["my-todos"]


def test_adding_a_name_that_is_taken_is_refused_before_anything_is_asked(setup, capsys):
    assert _run("add", "acme/todos", "-y") == 0
    capsys.readouterr()

    assert _run("add", "acme/todos", "-y") == 1

    assert "already in the library" in capsys.readouterr().err


def test_a_download_that_is_not_a_harness_is_refused_with_the_reason(setup, capsys, tmp_path, monkeypatch):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "README.md").write_text("no\n", encoding="utf-8")
    _git(broken, "init", "-q")
    _git(broken, "add", "-A")
    _git(broken, "commit", "-q", "-m", "x")
    monkeypatch.setattr(library, "parse_source", lambda text: Source(str(broken)))

    assert _run("add", "acme/broken", "-y") == 1

    assert "not a harness repository" in capsys.readouterr().err


def test_list_and_show_say_where_a_harness_came_from_and_what_is_in_it(setup, capsys):
    _run("add", "acme/todos", "-y")
    capsys.readouterr()

    assert _run("list") == 0
    listed = capsys.readouterr().out
    assert "NAME" in listed and "todos" in listed and "list_todos" in listed and "1.0.0" in listed

    assert _run("show", "todos") == 0
    shown = capsys.readouterr().out
    assert "Find TODOs." in shown and "list_todos" in shown and "repository todos" in shown

    assert _run("list", "--json") == 0
    assert '"name": "todos"' in capsys.readouterr().out
    assert _run("show", "nope") == 1


def test_update_shows_what_changed_and_replaces_after_a_yes(setup, capsys):
    config, upstream, _ = setup
    _run("add", "acme/todos", "-y")
    capsys.readouterr()
    assert _run("update", "todos", "-y") == 0
    assert "already at" in capsys.readouterr().out

    _upstream(upstream, version="1.1.0", body="x = 2\n")
    (upstream / "extra.py").write_text("y = 1\n", encoding="utf-8")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "more")

    assert _run("update", "todos", "-y") == 0

    out = capsys.readouterr().out
    assert "version: 1.0.0 -> 1.1.0" in out and "files added: extra.py" in out and "__init__.py" in out
    assert library.get(config, "todos").commit == _git(upstream, "rev-parse", "HEAD")


def test_update_refuses_changes_made_since_the_install_and_points_at_fork(setup, capsys):
    config, upstream, _ = setup
    _run("add", "acme/todos", "-y")
    (config.harness_dir / "library" / "todos" / "todos" / "mine.py").write_text("m = 1\n", encoding="utf-8")
    _upstream(upstream, version="1.1.0", body="x = 9\n")
    capsys.readouterr()

    assert _run("update", "todos", "-y") == 1

    err = capsys.readouterr().err
    assert "fork todos" in err and "--force" in err
    assert (config.harness_dir / "library" / "todos" / "todos" / "mine.py").is_file()
    assert _run("list") == 0 and "changed" in capsys.readouterr().out


def test_fork_and_remove(setup, capsys):
    config, _, _ = setup
    _run("add", "acme/todos", "-y")

    assert _run("fork", "todos", "mine") == 0
    assert library.get(config, "mine").origin == "fork of todos"
    assert _run("fork", "todos", "mine") == 1, "the name is taken"

    assert _run("remove", "mine", "-y") == 0
    assert [entry.name for entry in library.entries(config)] == ["todos"]
    capsys.readouterr()


def test_what_works_on_a_session_is_not_a_word_of_the_shell_command(setup):
    for word in ("save", "use"):
        with pytest.raises(SystemExit) as stopped:
            _run(word, "x")
        assert stopped.value.code == 2, f"`{word}` belongs to /harness inside ZettCode"


def test_a_harness_every_session_uses_cannot_be_removed_and_the_list_says_which_is_in_use(setup, capsys):
    _run("add", "acme/todos", "-y")
    _used[0] = "todos"
    capsys.readouterr()

    assert _run("remove", "todos", "-y") == 1

    assert "/harness use --none" in capsys.readouterr().err
    assert _run("list") == 0 and "in use" in capsys.readouterr().out


def test_without_git_the_command_says_to_install_it(setup, capsys, monkeypatch):
    monkeypatch.setattr(library.shutil, "which", lambda _name: None)

    assert _run("add", "acme/todos", "-y") == 1

    assert "install git first" in capsys.readouterr().err


def test_the_program_dispatches_the_word_harness_and_lists_it_in_help(monkeypatch, capsys):
    seen: list[list[str]] = []
    monkeypatch.setattr(harness_cli, "harness_program", lambda argv=None: seen.append(list(argv or [])) or 0)
    monkeypatch.setattr(sys, "argv", ["zettcode", "harness", "list"])
    from zettcode.broker import reload

    monkeypatch.setattr(reload, "check_in_background", lambda *a, **k: None)

    with pytest.raises(SystemExit) as stopped:
        cli.main()

    assert stopped.value.code == 0 and seen == [["list"]]
    assert "harness" in cli._build_parser().format_help()


def test_update_refuses_an_entry_whose_record_lost_its_digest_before_downloading_anything(setup, capsys):
    import json

    config, _, _ = setup
    _run("add", "acme/todos", "-y")
    record = config.harness_dir / "library" / "todos" / "SOURCE.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["digest"]
    record.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()

    assert _run("update", "todos", "-y") == 1

    captured = capsys.readouterr()
    assert "Downloading" not in captured.out, "nothing is fetched for an update that cannot go ahead"
    assert "SOURCE.json no longer says" in captured.err
    assert _run("list") == 0 and "record damaged" in capsys.readouterr().out


def test_list_says_a_repository_is_missing_and_the_refusal_names_where_the_old_tree_is(setup, capsys):
    import shutil

    config, _, _ = setup
    _run("add", "acme/todos", "-y")
    root = config.harness_dir / "library"
    (root / ".update-x").mkdir()
    shutil.move(str(root / "todos" / "todos"), str(root / ".update-x" / "previous"))
    capsys.readouterr()

    assert _run("list") == 0 and "repository missing" in capsys.readouterr().out
    assert _run("update", "todos", "-y") == 1
    assert ".update-x" in capsys.readouterr().err


def test_list_json_carries_the_state_an_update_would_find(setup, capsys):
    import json

    _run("add", "acme/todos", "-y")
    capsys.readouterr()

    assert _run("list", "--json") == 0

    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["state"] == "ok" and entry["modified"] is False


def test_a_use_that_names_nothing_is_reported_even_when_the_library_is_empty(setup, capsys):
    _used[0] = "gone"

    assert _run("list") == 0

    out = capsys.readouterr().out
    assert "library is empty" in out and "'gone'" in out


def test_an_option_before_the_word_does_not_start_a_session(setup, monkeypatch, tmp_path, capsys):
    from zettcode import cli
    from zettcode.broker import reload

    monkeypatch.setattr(reload, "check_in_background", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["zettcode", "-w", str(tmp_path), "harness"])
    monkeypatch.setattr(cli, "launch", lambda options: pytest.fail("a session was started"))

    with pytest.raises(SystemExit) as stop:
        cli.main()

    assert stop.value.code == 2  # the library's own parser asked for an action
