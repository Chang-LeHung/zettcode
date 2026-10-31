"""``zettcode plugins``: what a target becomes, where a single file goes, and what a switch writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib

from zettcode import plugin_cli as cli


@pytest.fixture(autouse=True)
def _config_file(tmp_path, monkeypatch):
    """Every switch writes to a configuration file of this test, never the reader's."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    return path


def test_a_local_path_is_made_absolute(tmp_path: Path):
    project = tmp_path / "greeter"
    project.mkdir()

    assert cli.requirement_for(str(project)) == str(project.resolve())


def test_a_local_archive_is_installed_by_its_path(tmp_path: Path):
    wheel = tmp_path / "greeter-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")

    assert cli.requirement_for(str(wheel)) == str(wheel.resolve())


@pytest.mark.parametrize(
    ("target", "requirement"),
    [
        ("owner/repo", "git+https://github.com/owner/repo.git"),
        ("gh:owner/repo", "git+https://github.com/owner/repo.git"),
        ("github:owner/repo", "git+https://github.com/owner/repo.git"),
        ("owner/repo@v1.2.0", "git+https://github.com/owner/repo.git@v1.2.0"),
        ("https://github.com/owner/repo", "git+https://github.com/owner/repo.git"),
        ("https://github.com/owner/repo.git", "git+https://github.com/owner/repo.git"),
        (
            "https://github.com/owner/repo/tree/main/plugins/greeter",
            "git+https://github.com/owner/repo.git@main#subdirectory=plugins/greeter",
        ),
        ("https://github.com/owner/repo/tree/v1", "git+https://github.com/owner/repo.git@v1"),
        ("git+https://example.com/plugin.git", "git+https://example.com/plugin.git"),
    ],
)
def test_a_github_repository_becomes_a_git_url(target: str, requirement: str):
    assert cli.requirement_for(target) == requirement


@pytest.mark.parametrize("target", ["", "   ", "not a plugin", "owner/repo/extra", "https://example.com/x"])
def test_a_target_that_is_neither_a_path_nor_a_github_repository_is_refused(target: str):
    with pytest.raises(ValueError):
        cli.requirement_for(target)


def test_install_runs_the_installer_for_this_interpreter(tmp_path: Path, monkeypatch, capsys):
    project = tmp_path / "greeter"
    project.mkdir()
    runs: list[list[str]] = []
    monkeypatch.setattr(cli, "installer", lambda: cli.Installer("pip", (sys.executable, "-m", "pip")))
    monkeypatch.setattr(cli, "run", lambda command: runs.append(list(command)) or 0)

    assert cli.install(str(project)) == 0

    assert runs == [[sys.executable, "-m", "pip", "install", "--upgrade", str(project.resolve())]]
    assert "installed; start ZettCode again" in capsys.readouterr().out


def test_install_reports_a_failed_installer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "installer", lambda: cli.Installer("uv", ("uv", "pip")))
    monkeypatch.setattr(cli, "run", lambda command: 1)

    assert cli.install("owner/repo") == 1
    assert "the install failed" in capsys.readouterr().err


def test_install_says_what_to_do_when_there_is_no_installer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "installer", lambda: None)

    assert cli.install("owner/repo") == 1
    assert "neither pip nor uv" in capsys.readouterr().err


def test_install_refuses_a_target_it_does_not_understand(capsys):
    assert cli.install("https://example.com/plugin") == 1
    assert "not a local path or a GitHub repository" in capsys.readouterr().err


# -- a single Python file ----------------------------------------------------------------------------


def plugin_file(tmp_path: Path, body: str = "class Greeter(TuiPlugin):\n    name = 'greeter'\n") -> Path:
    path = tmp_path / "greeter.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_file_plugin_is_the_class_that_derives_from_a_plugin_base(tmp_path):
    assert cli.plugin_classes(plugin_file(tmp_path)) == ["Greeter"]


def test_every_plugin_class_in_a_file_is_found(tmp_path):
    path = plugin_file(
        tmp_path,
        "class Greeter(TuiPlugin):\n    pass\n\nclass Helper:\n    pass\n\nclass Later(Plugin):\n    pass\n",
    )

    assert cli.plugin_classes(path) == ["Greeter", "Later"]


def test_a_file_with_no_plugin_class_says_what_it_needs(tmp_path):
    with pytest.raises(ValueError, match="base name ends in Plugin"):
        cli.plugin_classes(plugin_file(tmp_path, "value = 1\n"))


def test_a_file_that_is_not_python_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not valid Python"):
        cli.plugin_classes(plugin_file(tmp_path, "class (\n"))


@pytest.mark.parametrize(
    ("stem", "module"),
    [
        ("greeter", "greeter"),
        ("my-plugin", "my_plugin"),
        ("1x", "plugin_1x"),
        ("_greeter", "greeter"),
        ("__", "plugin"),
    ],
)
def test_a_file_stem_becomes_a_module_name(stem, module):
    assert cli.module_name(stem) == module


def test_installing_a_file_copies_it_into_the_plugins_folder(tmp_path, monkeypatch, capsys):
    source = plugin_file(tmp_path)
    folder = tmp_path / "plugins"
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)

    assert cli.install(str(source)) == 0

    assert (folder / "greeter.py").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert "start ZettCode again to load greeter" in capsys.readouterr().out


def test_installing_a_file_that_is_not_a_plugin_writes_nothing(tmp_path, monkeypatch, capsys):
    source = plugin_file(tmp_path, "value = 1\n")
    folder = tmp_path / "plugins"
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)

    assert cli.install(str(source)) == 1
    assert not folder.exists()
    assert "base name ends in Plugin" in capsys.readouterr().err


def test_uninstall_removes_a_file_plugin_first(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "greeter.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "distribution_for", lambda name: pytest.fail("a file is not a distribution"))

    assert cli.uninstall("greeter") == 0
    assert not (folder / "greeter.py").exists()
    assert "removed" in capsys.readouterr().out


def test_uninstall_runs_the_installer_for_the_distribution_behind_the_name(monkeypatch, capsys):
    runs: list[list[str]] = []
    monkeypatch.setattr(cli, "plugins_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(cli, "distribution_for", lambda name: "my-plugin")
    monkeypatch.setattr(cli, "installer", lambda: cli.Installer("pip", (sys.executable, "-m", "pip")))
    monkeypatch.setattr(cli, "run", lambda command: runs.append(list(command)) or 0)

    assert cli.uninstall("greeter") == 0

    assert runs == [[sys.executable, "-m", "pip", "uninstall", "-y", "my-plugin"]]
    assert "uninstalled; start ZettCode again" in capsys.readouterr().out


def test_uninstall_with_uv_has_no_yes_flag(monkeypatch):
    runs: list[list[str]] = []
    monkeypatch.setattr(cli, "plugins_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(cli, "distribution_for", lambda name: "my-plugin")
    monkeypatch.setattr(cli, "installer", lambda: cli.Installer("uv", ("uv", "pip")))
    monkeypatch.setattr(cli, "run", lambda command: runs.append(list(command)) or 0)

    assert cli.uninstall("greeter") == 0

    assert runs == [["uv", "pip", "uninstall", "--python", sys.executable, "my-plugin"]]


def test_a_missing_file_is_not_read_as_a_github_repository():
    with pytest.raises(ValueError, match="no such file"):
        cli.requirement_for("./greeter.py")
    with pytest.raises(ValueError, match="no such file"):
        cli.requirement_for("foo/plugin.py")
    with pytest.raises(ValueError, match="no such file"):
        cli.requirement_for("~/.zettcode/plugins/missing")


def test_list_says_so_when_the_configuration_cannot_be_read(monkeypatch, capsys):
    monkeypatch.setattr(cli, "plugin_state", lambda: (_ for _ in ()).throw(ValueError("bad [plugins]")))

    assert cli.list_plugins() == 1
    assert "could not be listed" in capsys.readouterr().err


def test_uninstall_of_something_not_installed_says_where_to_look(monkeypatch, capsys):
    monkeypatch.setattr(cli, "plugins_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(cli, "distribution_for", lambda name: None)
    monkeypatch.setattr(cli, "run", lambda command: pytest.fail("nothing may be run"))

    assert cli.uninstall("greeter") == 1
    assert "/plugins lists" in capsys.readouterr().err


# -- switches ----------------------------------------------------------------------------------------


def fake_config(tmp_path: Path, **changes: object) -> SimpleNamespace:
    values = {
        "plugins_file": tmp_path / "plugins.json",
        "plugins_enabled": True,
        "disabled_plugins": (),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def folder_with_greeter(tmp_path: Path) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "greeter.py").write_text("class Greeter(TuiPlugin):\n    pass\n", encoding="utf-8")
    return folder


def test_disable_writes_the_switch_file_for_an_installed_file_plugin(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("greeter", enabled=False) == 0

    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["plugins"]["disable"] == ["greeter"]
    assert "disabled greeter" in capsys.readouterr().out


def test_enable_removes_the_name_from_the_configuration_file(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    config_file = tmp_path / "config.toml"
    config_file.write_text('[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("greeter", enabled=True) == 0

    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["plugins"]["disable"] == []
    assert "enabled greeter" in capsys.readouterr().out


def test_a_switch_for_something_that_is_not_installed_says_what_exists(tmp_path, monkeypatch, capsys):
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: tmp_path / "plugins")
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("nobody", enabled=False) == 1
    assert "no installed plugin or plugin file" in capsys.readouterr().err


def test_a_name_the_configuration_holds_is_switched_off_in_the_file(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    config_file = tmp_path / "config.toml"
    config_file.write_text('[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("greeter", enabled=True) == 0

    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["plugins"]["disable"] == []
    assert "enabled greeter" in capsys.readouterr().out


def test_a_switch_is_refused_while_every_installed_plugin_is_off(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path, plugins_enabled=False)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("greeter", enabled=False) == 1
    assert "[plugins] enabled = false" in capsys.readouterr().err


def test_a_hyphenated_file_is_switched_by_the_name_it_was_installed_under(tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "my_plugin.py").write_text("class Greeter(TuiPlugin):\n    pass\n", encoding="utf-8")
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.switch("my-plugin", enabled=False) == 0

    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["plugins"]["disable"] == ["my_plugin"]


def test_a_distribution_name_resolves_to_the_one_plugin_it_carries(tmp_path, monkeypatch):
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: tmp_path / "plugins")
    monkeypatch.setattr(cli, "_entry_names_for_distribution", lambda name: ["monitor"])

    assert cli._resolve_switch_name(config, "zettcode-monitor") == "monitor"

    monkeypatch.setattr(cli, "_entry_names_for_distribution", lambda name: ["one", "two"])
    with pytest.raises(ValueError, match="several plugins"):
        cli._resolve_switch_name(config, "zettcode-monitor")


def test_uninstall_removes_the_name_from_the_switch_file(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    config_file = tmp_path / "config.toml"
    config_file.write_text('[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.uninstall("greeter") == 0

    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["plugins"]["disable"] == []
    assert "switch was removed" in capsys.readouterr().out


def test_an_unknown_key_in_the_plugins_table_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[plugins]\ndissable = ["x"]\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))

    with pytest.raises(ValueError, match="unknown keys"):
        cli.plugin_state()


def test_a_distribution_name_is_found_by_the_metadata_it_is_installed_with():
    assert cli.distribution_for("zettcode") == "zettcode"


def test_pip_is_preferred_and_uv_is_used_when_this_environment_has_none(monkeypatch):
    monkeypatch.setattr(cli, "_pip_works", lambda: True)
    assert cli.installer() == cli.Installer("pip", (sys.executable, "-m", "pip"))

    monkeypatch.setattr(cli, "_pip_works", lambda: False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/uv")
    assert cli.installer() == cli.Installer("uv", ("/usr/local/bin/uv", "pip"))

    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.installer() is None


def test_list_names_every_plugin_and_where_it_is(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.list_plugins() == 0

    said = capsys.readouterr().out
    assert "KIND" in said and "LOCATION" in said and "SWITCH" in said
    assert "compiled in" in said, "the plugins compiled into the program are listed"
    assert "greeter" in said and str(folder / "greeter.py") in said


def test_list_marks_a_switched_off_file_as_off(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    config.plugins_file.write_text('{"disabled": ["greeter"]}', encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.list_plugins() == 0

    said = capsys.readouterr().out
    row = next(line for line in said.splitlines() if "greeter" in line)
    assert " no " in f" {row} " and "[plugins] disable" in row


def test_list_as_json_names_the_location_and_the_switch(tmp_path, monkeypatch, capsys):
    folder = folder_with_greeter(tmp_path)
    config = fake_config(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: config)

    assert cli.list_plugins(as_json=True) == 0

    rows = json.loads(capsys.readouterr().out)
    file_row = next(row for row in rows if row["kind"] == "file")
    assert file_row == {
        "kind": "file",
        "name": "greeter",
        "origin": "greeter",
        "location": str(folder / "greeter.py"),
        "switch": "config ([plugins] disable)",
        "enabled": True,
    }


def test_list_is_one_of_the_actions(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(cli, "list_plugins", lambda *, as_json=False: calls.append(as_json) or 0)

    assert cli.plugins_program(["list"]) == 0
    assert cli.plugins_program(["list", "--json"]) == 0
    assert calls == [False, True]


def test_the_four_actions_are_dispatch(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "install", lambda target, *, force=False: calls.append(("install", target)) or 0)
    monkeypatch.setattr(cli, "uninstall", lambda name: calls.append(("uninstall", name)) or 0)
    monkeypatch.setattr(
        cli, "switch", lambda name, *, enabled: calls.append(("enable" if enabled else "disable", name)) or 0
    )

    assert cli.plugins_program(["install", "owner/repo"]) == 0
    assert cli.plugins_program(["uninstall", "greeter"]) == 0
    assert cli.plugins_program(["enable", "greeter"]) == 0
    assert cli.plugins_program(["disable", "greeter"]) == 0
    assert calls == [
        ("install", "owner/repo"),
        ("uninstall", "greeter"),
        ("enable", "greeter"),
        ("disable", "greeter"),
    ]


def test_an_action_is_required(capsys):
    with pytest.raises(SystemExit):
        cli.plugins_program([])


def test_a_name_that_is_a_path_is_refused(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "plugins"
    folder.mkdir()
    outside = folder.parent / "greeter.py"
    outside.write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: fake_config(tmp_path))

    assert cli.uninstall("../greeter") == 1
    assert outside.exists()
    assert "not a plugin name" in capsys.readouterr().err

    assert cli.switch("../greeter", enabled=False) == 1
    assert "not a plugin name" in capsys.readouterr().err


def test_installing_over_a_different_file_needs_force(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "plugins"
    folder.mkdir()
    target = folder / "greeter.py"
    target.write_text("old = True\n", encoding="utf-8")
    source = tmp_path / "source" / "greeter.py"
    source.parent.mkdir()
    source.write_text("class Greeter(TuiPlugin):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)

    assert cli.install(str(source)) == 1
    assert target.read_text(encoding="utf-8") == "old = True\n"
    assert "different content" in capsys.readouterr().err

    assert cli.install(str(source), force=True) == 0
    assert "class Greeter" in target.read_text(encoding="utf-8")


def test_a_renamed_file_says_what_it_was_installed_as(tmp_path, monkeypatch, capsys):
    source = tmp_path / "_greeter.py"
    source.write_text("class Greeter(TuiPlugin):\n    pass\n", encoding="utf-8")
    folder = tmp_path / "plugins"
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)

    assert cli.install(str(source)) == 0
    assert (folder / "greeter.py").is_file()
    said = capsys.readouterr().out
    assert "_greeter.py as" in said and "greeter.py" in said


def test_a_leading_dot_slash_is_stripped_from_a_name(tmp_path, monkeypatch):
    folder = folder_with_greeter(tmp_path)
    monkeypatch.setattr(cli, "plugins_dir", lambda: folder)
    monkeypatch.setattr(cli, "plugin_state", lambda: fake_config(tmp_path))

    assert cli.uninstall("./greeter") == 0
    assert not (folder / "greeter.py").exists()


def test_force_on_a_project_is_a_note_not_a_pip_flag(tmp_path, monkeypatch, capsys):
    project = tmp_path / "greeter"
    project.mkdir()
    runs: list[list[str]] = []
    monkeypatch.setattr(cli, "installer", lambda: cli.Installer("pip", (sys.executable, "-m", "pip")))
    monkeypatch.setattr(cli, "run", lambda command: runs.append(list(command)) or 0)

    assert cli.install(str(project), force=True) == 0

    assert "--force" in capsys.readouterr().err
    assert runs == [[sys.executable, "-m", "pip", "install", "--upgrade", str(project.resolve())]]


def test_a_plugins_folder_under_a_file_is_a_write_error_not_a_traceback(tmp_path, monkeypatch, capsys):
    source = tmp_path / "greeter.py"
    source.write_text("class Greeter(TuiPlugin):\n    pass\n", encoding="utf-8")
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(cli, "plugins_dir", lambda: blocked)

    assert cli.install(str(source)) == 1
    assert "could not be written" in capsys.readouterr().err
