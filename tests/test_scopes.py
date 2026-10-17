"""Skills and MCP servers from the workspace, from the user's own directory, or from both.

The default is both, merged: the user's own files and the project's are used together, the project's winning
a name inside that project. ``scope = "global"`` ignores what a checkout carries, for a reader who does not
want a repository's skills read or its MCP servers started.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.extensions.mcp import McpExtension
from zett_agent.extensions.skill import SkillExtension

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.extensions.mcp import build_scoped_mcp_extension
from zettcode.config import ModelConfig, ZettCodeConfig, load_config


def _config(tmp_path: Path, home: Path, **changes) -> ZettCodeConfig:
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    return ZettCodeConfig(
        workspace=workspace,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        agents_md_enabled=False,
        mcp_config=home / "mcp.json",
        **changes,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """The user's own directory, in place of ``~/.zettcode``."""
    directory = tmp_path / "home"
    directory.mkdir()
    monkeypatch.setattr("zettcode.config.DEFAULT_SKILL_ROOT", str(directory / "skills"))
    return directory


def _skill(root: Path, name: str, description: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nbody\n", encoding="utf-8"
    )


def _servers(path: Path, **servers: str) -> None:
    body = ", ".join(f'"{name}": {{"type": "streamable-http", "url": "{url}"}}' for name, url in servers.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"servers": {' + body + "}}", encoding="utf-8")


# -- the settings ------------------------------------------------------------------------------------------


def test_the_default_scope_is_both_the_users_files_and_the_projects(tmp_path: Path, home: Path):
    config = _config(tmp_path, home)
    project = config.workspace

    assert (config.skills_scope, config.mcp_scope) == ("both", "both")
    assert config.skill_search_roots() == ((project / ".zettcode" / "skills").resolve(), (home / "skills").resolve())
    assert config.mcp_files() == ((project / ".zettcode" / "mcp.json").resolve(), (home / "mcp.json").resolve())


def test_global_scope_reads_only_the_users_own_files(tmp_path: Path, home: Path):
    config = _config(tmp_path, home, skills_scope="global", mcp_scope="global")

    assert config.skill_search_roots() == ((home / "skills").resolve(),)
    assert config.mcp_files() == ((home / "mcp.json").resolve(),)


def test_workspace_scope_reads_only_the_projects_files(tmp_path: Path, home: Path):
    config = _config(tmp_path, home, skills_scope="workspace", mcp_scope="workspace")
    project = config.workspace

    assert config.skill_search_roots() == ((project / ".zettcode" / "skills").resolve(),)
    assert config.mcp_files() == ((project / ".zettcode" / "mcp.json").resolve(),)


def test_both_puts_the_project_first_so_its_version_wins(tmp_path: Path, home: Path):
    config = _config(tmp_path, home, skills_scope="both", mcp_scope="both")
    project = config.workspace

    assert config.skill_search_roots() == (
        (project / ".zettcode" / "skills").resolve(),
        (home / "skills").resolve(),
    )
    assert config.mcp_files() == ((project / ".zettcode" / "mcp.json").resolve(), (home / "mcp.json").resolve())


def test_configured_roots_still_come_before_either_scope(tmp_path: Path, home: Path):
    team = tmp_path / "team"
    config = _config(tmp_path, home, skills_scope="both", skill_roots=(team,))

    assert config.skill_search_roots()[0] == team.resolve()


def test_a_root_that_names_a_directory_a_scope_also_names_is_scanned_once(tmp_path: Path, home: Path):
    config = _config(tmp_path, home, skills_scope="both", skill_roots=(Path(".zettcode/skills"),))

    roots = config.skill_search_roots()
    assert len(roots) == len(set(roots)) == 2


def test_an_unknown_scope_is_refused():
    with pytest.raises(ValueError, match="skills_scope"):
        ZettCodeConfig(workspace=Path.cwd(), models=(ModelConfig(model="m", token="t"),), skills_scope="everywhere")
    with pytest.raises(ValueError, match="mcp_scope"):
        ZettCodeConfig(workspace=Path.cwd(), models=(ModelConfig(model="m", token="t"),), mcp_scope="")


def test_the_file_sets_each_scope(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[skills]\nscope = "Global"\n\n[mcp]\nscope = "workspace"\n',
        encoding="utf-8",
    )

    config = load_config(tmp_path, path=path)

    assert (config.skills_scope, config.mcp_scope) == ("global", "workspace")


def test_without_a_scope_the_file_reads_both(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")

    config = load_config(tmp_path, path=path)

    assert (config.skills_scope, config.mcp_scope) == ("both", "both")


@pytest.mark.parametrize("table", ["skills", "mcp"])
def test_a_scope_the_file_cannot_mean_is_refused_and_named(tmp_path: Path, table):
    path = tmp_path / "config.toml"
    path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n\n[{table}]\nscope = "project"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{table}\.scope.*global.*workspace") as error:
        load_config(tmp_path, path=path)

    assert "project" in str(error.value)


# -- skills ------------------------------------------------------------------------------------------------


def _skills(config: ZettCodeConfig) -> dict[str, str]:
    extension = next(item for item in runtime_module.integration_extensions(config) if isinstance(item, SkillExtension))
    return {skill.name: skill.description for skill in extension.skills}


def test_a_project_skill_is_read_by_default_beside_the_users_own(tmp_path: Path, home: Path):
    project = tmp_path / "project"
    _skill(project / ".zettcode" / "skills", "local", "from the checkout")
    _skill(home / "skills", "mine", "from the user")

    assert _skills(_config(tmp_path, home)) == {"local": "from the checkout", "mine": "from the user"}


def test_global_scope_ignores_the_skills_a_checkout_carries(tmp_path: Path, home: Path):
    _skill(tmp_path / "project" / ".zettcode" / "skills", "local", "from the checkout")
    _skill(home / "skills", "mine", "from the user")

    assert _skills(_config(tmp_path, home, skills_scope="global")) == {"mine": "from the user"}


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("global", {"mine": "from the user", "shared": "the user's"}),
        ("workspace", {"local": "from the checkout", "shared": "the project's"}),
        (
            "both",
            {"mine": "from the user", "local": "from the checkout", "shared": "the project's"},
        ),
    ],
)
def test_each_scope_finds_its_own_skills_and_a_project_wins_a_clash(tmp_path: Path, home: Path, scope, expected):
    project = tmp_path / "project"
    _skill(project / ".zettcode" / "skills", "local", "from the checkout")
    _skill(project / ".zettcode" / "skills", "shared", "the project's")
    _skill(home / "skills", "mine", "from the user")
    _skill(home / "skills", "shared", "the user's")

    assert _skills(_config(tmp_path, home, skills_scope=scope)) == expected


def test_the_mention_list_sees_the_same_skills_as_the_model(tmp_path: Path, home: Path):
    """`@` completion builds its list from the same roots the extension scans."""
    from zettcode.app.agent.dialogue.mentions import SkillMentions

    _skill(tmp_path / "project" / ".zettcode" / "skills", "local", "from the checkout")
    config = _config(tmp_path, home, skills_scope="workspace")

    names = {item.name for item in SkillMentions(config).candidates("")}

    assert names == {"local"}


# -- MCP ---------------------------------------------------------------------------------------------------


def _names(extension: McpExtension) -> dict[str, str]:
    return {server.name: server.url for server in extension.servers}


def test_nothing_configured_adds_no_mcp_extension_at_all(tmp_path: Path, home: Path):
    assert build_scoped_mcp_extension([home / "mcp.json", tmp_path / "project" / ".zettcode" / "mcp.json"]) is None


def test_one_file_is_the_framework_extension_and_keeps_watching_it(tmp_path: Path, home: Path):
    _servers(home / "mcp.json", docs="http://127.0.0.1:9/a")

    extension = build_scoped_mcp_extension([home / "mcp.json", tmp_path / "nowhere.json"])

    assert _names(extension) == {"docs": "http://127.0.0.1:9/a"}
    assert extension.config_path == (home / "mcp.json").resolve(), "so an edit to it is still picked up"


def test_two_files_are_merged_and_the_first_wins_a_name(tmp_path: Path, home: Path):
    project = tmp_path / "project" / ".zettcode" / "mcp.json"
    _servers(project, docs="http://127.0.0.1:9/project", extra="http://127.0.0.1:9/extra")
    _servers(home / "mcp.json", docs="http://127.0.0.1:9/user", mine="http://127.0.0.1:9/mine")

    extension = build_scoped_mcp_extension([project, home / "mcp.json"])

    assert _names(extension) == {
        "docs": "http://127.0.0.1:9/project",
        "extra": "http://127.0.0.1:9/extra",
        "mine": "http://127.0.0.1:9/mine",
    }


def test_a_file_that_cannot_be_read_costs_only_its_own_servers_and_says_why(tmp_path: Path, home: Path):
    project = tmp_path / "project" / ".zettcode" / "mcp.json"
    project.parent.mkdir(parents=True)
    project.write_text("{ not json", encoding="utf-8")
    _servers(home / "mcp.json", mine="http://127.0.0.1:9/mine")

    extension = build_scoped_mcp_extension([project, home / "mcp.json"])

    assert _names(extension) == {"mine": "http://127.0.0.1:9/mine"}
    assert len(extension.startup_issues) == 1
    assert ".zettcode/mcp.json" in extension.startup_issues[0] and "cannot be read" in extension.startup_issues[0]


def test_an_entry_that_cannot_be_used_is_named_with_the_file_it_is_in(tmp_path: Path, home: Path):
    project = tmp_path / "project" / ".zettcode" / "mcp.json"
    project.parent.mkdir(parents=True)
    project.write_text('{"servers": {"typo": {"type": "carrier-pigeon"}}}', encoding="utf-8")
    _servers(home / "mcp.json", mine="http://127.0.0.1:9/mine")

    extension = build_scoped_mcp_extension([project, home / "mcp.json"])

    assert _names(extension) == {"mine": "http://127.0.0.1:9/mine"}
    assert any("'typo'" in line and ".zettcode/mcp.json" in line for line in extension.startup_issues)


def test_the_runtime_reads_the_files_its_scope_names(tmp_path: Path, home: Path):
    project = tmp_path / "project" / ".zettcode" / "mcp.json"
    _servers(project, local="http://127.0.0.1:9/local")
    _servers(home / "mcp.json", mine="http://127.0.0.1:9/mine")

    def servers(scope: str) -> set[str]:
        config = _config(tmp_path, home, mcp_scope=scope)
        found = [e for e in runtime_module.integration_extensions(config) if isinstance(e, McpExtension)]
        return {server.name for extension in found for server in extension.servers}

    assert servers("global") == {"mine"}
    assert servers("workspace") == {"local"}
    assert servers("both") == {"local", "mine"}


def test_global_scope_does_not_start_the_servers_a_checkout_carries(tmp_path: Path, home: Path):
    """The way out for a reader who does not want a repository's servers run."""
    _servers(tmp_path / "project" / ".zettcode" / "mcp.json", local="http://127.0.0.1:9/local")

    config = _config(tmp_path, home, mcp_scope="global")

    assert not [e for e in runtime_module.integration_extensions(config) if isinstance(e, McpExtension)]


def test_by_default_a_checkouts_servers_are_read_too(tmp_path: Path, home: Path):
    _servers(tmp_path / "project" / ".zettcode" / "mcp.json", local="http://127.0.0.1:9/local")
    _servers(home / "mcp.json", mine="http://127.0.0.1:9/mine")

    found = [e for e in runtime_module.integration_extensions(_config(tmp_path, home)) if isinstance(e, McpExtension)]

    assert {server.name for extension in found for server in extension.servers} == {"local", "mine"}
