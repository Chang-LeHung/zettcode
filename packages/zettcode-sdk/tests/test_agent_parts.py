"""The plugins that compose the agent are found through the ``zettcode.agent`` entry-point group, in the order they were
listed when the runtime did the listing, and their one real service dependency is a ``deps``."""

from __future__ import annotations

import dataclasses
from importlib.metadata import entry_points
from pathlib import Path

from plugin_helpers import runtime_state  # noqa: E402  (support/ is on the path)
from zettcode._compat import tomllib
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AgentBuild, loader
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, run
from zettcode.sdk.builtins import AGENT_PLUGIN_NAMES, AGENT_PLUGINS, REQUIRED_AGENT_NAMES, require_agent_parts

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _sdk_points() -> list:
    """The entry points this distribution publishes: the group also holds the parts of the skills and the MCP client."""
    return [point for point in entry_points(group=AGENT_PART_GROUP) if point.dist and point.dist.name == "zettcode-sdk"]


def _config(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    return ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        plugins_file=tmp_path / "off.json",
        mcp_enabled=False,
        skills_enabled=False,
        **changes,  # type: ignore[arg-type]
    )


def test_the_distribution_publishes_exactly_the_plugins_the_list_names_in_that_order():
    published = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["entry-points"][AGENT_PART_GROUP]

    assert list(published) == [plugin.name for plugin in AGENT_PLUGINS]
    assert list(published.values()) == [f"zettcode.sdk.builtins:{type(plugin).__name__}" for plugin in AGENT_PLUGINS]


def test_the_installed_environment_advertises_the_same():
    found = {point.name: point.value for point in _sdk_points()}

    assert found == {plugin.name: f"zettcode.sdk.builtins:{type(plugin).__name__}" for plugin in AGENT_PLUGINS}


def test_discovery_activates_them_in_the_order_of_the_list_and_not_in_the_order_the_names_sort(tmp_path: Path):
    """Extensions that share a priority keep the order they registered in, so this order is behaviour."""
    points = sorted(_sdk_points(), key=lambda point: point.name)
    assert [point.name for point in points] != list(AGENT_PLUGIN_NAMES), "sorted by name, they are in another order"

    plugins = run(
        loader.Loader(_config(tmp_path), runtime_state(_config(tmp_path))),
        _config(tmp_path),
        builtins=(),
        entry_points=points,
    )

    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES)
    assert plugins.failed == ()


def test_a_plugin_is_activated_after_the_one_whose_service_it_reads_whatever_their_ranks_say(tmp_path: Path):
    subagents = next(plugin for plugin in AGENT_PLUGINS if plugin.name == "subagents")
    capabilities = next(plugin for plugin in AGENT_PLUGINS if plugin.name == "capabilities")
    assert subagents.deps == ("capabilities",)
    ranks = (type(subagents).rank, type(capabilities).rank)
    try:
        type(subagents).rank, type(capabilities).rank = 0, 99  # the wrong way round
        points = [
            point for point in entry_points(group=AGENT_PART_GROUP) if point.name in {"subagents", "capabilities"}
        ]
        config = _config(tmp_path)
        plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)
    finally:
        type(subagents).rank, type(capabilities).rank = ranks

    assert [plugin.name for plugin in plugins.plugins] == ["capabilities", "subagents"]
    assert plugins.failed == ()


def test_a_disable_line_does_not_reach_the_plugins_that_compose_the_agent(tmp_path: Path, caplog):
    config = _config(tmp_path, disabled_plugins=("coding", "session-log"))
    points = list(entry_points(group=AGENT_PART_GROUP))

    with caplog.at_level("WARNING", logger="zettcode.plugins"):
        plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)

    assert {"coding", "session-log"} <= {plugin.name for plugin in plugins.plugins}
    assert {"coding", "session-log"} <= set(plugins.builtins), "so the plugins page offers no switch for them"
    assert {r.plugin for r in caplog.records if r.getMessage() == "plugins.required"} == {"coding", "session-log"}


def test_plugins_switched_off_as_a_whole_still_load_them(tmp_path: Path):
    config = _config(tmp_path, plugins_enabled=False)
    points = _sdk_points()

    plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)

    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES)


def test_an_installation_with_none_of_them_is_refused_and_one_that_failed_to_activate_is_not(tmp_path: Path):
    import pytest

    from zettcode.engine.plugins import load_plugins
    from zettcode.engine.plugins.loader import RequiredPluginError

    config = _config(tmp_path)
    nothing = load_plugins(config, builtins=(), entry_points=[], shared=runtime_state(config))
    with pytest.raises(RequiredPluginError) as raised:
        require_agent_parts(nothing)
    assert set(raised.value.missing) == set(REQUIRED_AGENT_NAMES) >= {"skills", "skill-tool", "mcp"}

    bare = load_plugins(config, builtins=(), shared={})  # discovery, but no state to build on: each one fails
    assert {origin for origin, _why in bare.failed} >= {"coding", "session-log"}
    assert require_agent_parts(bare) is bare, "a failure to activate is recorded, as it always was"


class _Foreign:
    """An entry point of another distribution that declares the program's group."""

    class dist:  # noqa: N801 - the slice of importlib.metadata.Distribution the loader reads
        name = "acme-tools"

    group = AGENT_PART_GROUP

    def __init__(self, name: str) -> None:
        self.name = name
        self.value = "acme:Plugin"

    def load(self):
        from zettcode.engine.plugins import Plugin

        class Stranger(Plugin):
            pass

        Stranger.name = self.name
        return Stranger


def test_a_foreign_distribution_cannot_join_the_program_by_declaring_its_group(tmp_path: Path):
    from zettcode.engine.plugins import catalog, load_plugins

    config = _config(tmp_path, disabled_plugins=("aaa",))
    points = [_Foreign("aaa"), *_sdk_points()]

    plugins = load_plugins(config, builtins=(), entry_points=points, shared=runtime_state(config))

    assert "aaa" not in plugins.builtins and "aaa" not in [plugin.name for plugin in plugins.plugins], (
        "an ordinary plugin"
    )
    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES), "and it did not jump the queue"
    off = _config(tmp_path)
    shown = [
        row.origin
        for row in catalog(
            off, load_plugins(off, builtins=(), entry_points=points, shared=runtime_state(off)), entry_points=points
        )
    ]
    assert "aaa" in shown, "it has a row, so a switch"


def test_a_stranger_that_names_itself_like_one_of_them_does_not_stand_in_for_the_missing_ones(tmp_path: Path):
    import pytest

    from zettcode.engine.plugins import load_plugins
    from zettcode.engine.plugins.loader import RequiredPluginError

    config = _config(tmp_path)
    plugins = load_plugins(config, builtins=(), entry_points=[_Foreign("mcp")], shared=runtime_state(config))

    with pytest.raises(RequiredPluginError):
        require_agent_parts(plugins)


def test_passing_the_list_as_builtins_beside_discovery_is_not_a_set_of_duplicate_failures(tmp_path: Path):
    from zettcode.engine.plugins import load_plugins

    config = _config(tmp_path)
    points = _sdk_points()

    plugins = load_plugins(config, builtins=AGENT_PLUGINS, entry_points=points, shared=runtime_state(config))

    assert plugins.failed == ()
    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES)


def test_the_skills_and_the_mcp_client_are_parts_of_the_agent_published_by_distributions_of_their_own(tmp_path: Path):
    """They are discovered with the SDK's, count as the program's own, and the agent still receives their extensions."""
    (tmp_path / "mcp.json").write_text('{"servers": {"docs": {"url": "http://127.0.0.1:9/a"}}}', encoding="utf-8")
    config = dataclasses.replace(
        _config(tmp_path, disabled_plugins=("skills", "mcp")),
        skills_enabled=True,
        mcp_enabled=True,
        mcp_config=tmp_path / "mcp.json",
    )
    points = list(entry_points(group=AGENT_PART_GROUP))

    plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)

    names = [plugin.name for plugin in plugins.plugins]
    assert {"skills", "skill-tool", "mcp"} <= set(names)
    assert {"skills", "skill-tool", "mcp"} <= set(plugins.builtins), "a disable line does not reach them"
    assert plugins.failed == ()
    built = [type(extension).__name__ for extension in plugins.agent_extensions(AgentBuild(model=object()))]  # type: ignore[arg-type]
    assert {"SkillExtension", "ReportingMcpExtension"} <= set(built)

    # Where they stand among the activations is not the order the agent runs them in: that is each extension's
    # priority, which these two do not share with anything (the rest of the agent is at 100).
    extensions = plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
    by_name = {extension.name: extension.priority for extension in extensions}
    assert by_name["ReportingMcpExtension"] < by_name["SkillExtension"] < 100
    assert [e.name for e in extensions][:2] == ["ReportingMcpExtension", "SkillExtension"]
