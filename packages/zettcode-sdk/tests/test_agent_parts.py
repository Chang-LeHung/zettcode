"""The plugins that compose the agent are found through the ``zettcode.plugin`` entry-point group, in the order they were
listed when the runtime did the listing, and their one real service dependency is a ``deps``."""

from __future__ import annotations

import dataclasses
from importlib.metadata import entry_points
from pathlib import Path

from plugin_helpers import runtime_state  # noqa: E402  (support/ is on the path)
from zettcode._compat import tomllib
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AgentBuild, loader
from zettcode.engine.plugins.loader import PLUGIN_ENTRY_POINT_GROUP, run
from zettcode.sdk.builtins import AGENT_PLUGIN_NAMES, AGENT_PLUGINS, REQUIRED_AGENT_NAMES

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _sdk_points() -> list:
    """The entry points this distribution publishes: the group also holds the parts of the skills and the MCP client."""
    return [
        point
        for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
        if point.dist and point.dist.name == "zettcode-sdk"
    ]


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
    published = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["entry-points"][
        PLUGIN_ENTRY_POINT_GROUP
    ]

    assert list(published) == [plugin.name for plugin in AGENT_PLUGINS]
    assert list(published.values()) == [f"zettcode.sdk.builtins:{plugin.__name__}" for plugin in AGENT_PLUGINS]


def test_the_installed_environment_advertises_the_same():
    found = {point.name: point.value for point in _sdk_points()}

    assert found == {plugin.name: f"zettcode.sdk.builtins:{plugin.__name__}" for plugin in AGENT_PLUGINS}


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
    ranks = (subagents.rank, capabilities.rank)
    try:
        subagents.rank, capabilities.rank = 0, 99  # the wrong way round
        points = [
            point
            for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
            if point.name in {"subagents", "capabilities"}
        ]
        config = _config(tmp_path)
        plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)
    finally:
        subagents.rank, capabilities.rank = ranks

    assert [plugin.name for plugin in plugins.plugins] == ["capabilities", "subagents"]
    assert plugins.failed == ()


def test_a_disable_line_does_not_reach_the_plugins_the_agent_requires(tmp_path: Path, caplog):
    config = _config(tmp_path, disabled_plugins=("coding", "session-log"))
    points = list(entry_points(group=PLUGIN_ENTRY_POINT_GROUP))

    with caplog.at_level("WARNING", logger="zettcode.plugins"):
        plugins = run(
            loader.Loader(config, runtime_state(config)),
            config,
            builtins=(),
            entry_points=points,
            required=REQUIRED_AGENT_NAMES,
        )

    assert {"coding", "session-log"} <= {plugin.name for plugin in plugins.plugins}
    assert {"coding", "session-log"} <= set(plugins.required), "so the plugins page offers no switch for them"
    assert {r.plugin for r in caplog.records if r.getMessage() == "plugins.required"} == {"coding", "session-log"}


def test_plugins_switched_off_as_a_whole_still_load_them(tmp_path: Path):
    config = _config(tmp_path, plugins_enabled=False)
    points = _sdk_points()

    plugins = run(
        loader.Loader(config, runtime_state(config)),
        config,
        builtins=(),
        entry_points=points,
        required=REQUIRED_AGENT_NAMES,
    )

    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES)


def test_an_installation_with_none_of_them_is_refused_and_so_is_one_where_they_cannot_start(tmp_path: Path):
    import pytest

    from zettcode.engine.plugins import load_plugins
    from zettcode.engine.plugins.loader import RequiredPluginError

    config = _config(tmp_path)
    with pytest.raises(RequiredPluginError) as raised:
        load_plugins(config, builtins=(), entry_points=[], shared=runtime_state(config), required=REQUIRED_AGENT_NAMES)
    assert set(raised.value.missing) == set(REQUIRED_AGENT_NAMES)

    # Discovery, but no state to build on: each one fails to activate, and the program says which, not "not installed".
    with pytest.raises(RequiredPluginError) as bare:
        load_plugins(config, builtins=(), shared={}, required=REQUIRED_AGENT_NAMES)
    assert bare.value.missing["coding"] != "not installed"


def test_passing_the_list_as_builtins_beside_discovery_is_not_a_set_of_duplicate_failures(tmp_path: Path):
    from zettcode.engine.plugins import load_plugins

    config = _config(tmp_path)
    points = _sdk_points()

    plugins = load_plugins(config, builtins=AGENT_PLUGINS, entry_points=points, shared=runtime_state(config))

    assert plugins.failed == ()
    assert [plugin.name for plugin in plugins.plugins] == list(AGENT_PLUGIN_NAMES)


def test_the_skills_and_the_mcp_client_are_plugins_like_any_other_and_the_agent_still_receives_their_extensions(
    tmp_path: Path,
):
    """They are discovered with the SDK's, and a disable line does reach them: nothing makes them special."""
    (tmp_path / "mcp.json").write_text('{"servers": {"docs": {"url": "http://127.0.0.1:9/a"}}}', encoding="utf-8")
    config = dataclasses.replace(
        _config(tmp_path),
        skills_enabled=True,
        mcp_enabled=True,
        mcp_config=tmp_path / "mcp.json",
    )
    points = list(entry_points(group=PLUGIN_ENTRY_POINT_GROUP))

    plugins = run(loader.Loader(config, runtime_state(config)), config, builtins=(), entry_points=points)

    names = [plugin.name for plugin in plugins.plugins]
    assert {"skills", "skill-tool", "mcp"} <= set(names)
    assert plugins.failed == ()
    built = [type(extension).__name__ for extension in plugins.agent_extensions(AgentBuild(model=object()))]  # type: ignore[arg-type]
    assert {"SkillExtension", "ReportingMcpExtension"} <= set(built)

    off = dataclasses.replace(config, disabled_plugins=("skills", "mcp"))
    left = run(loader.Loader(off, runtime_state(off)), off, builtins=(), entry_points=points)
    assert not {"skills", "mcp"} & {plugin.name for plugin in left.plugins}, "a reader may leave them out"

    # Where they stand among the activations is not the order the agent runs them in: that is each extension's
    # priority, which these two do not share with anything (the rest of the agent is at 100).
    extensions = plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
    by_name = {extension.name: extension.priority for extension in extensions}
    assert by_name["ReportingMcpExtension"] < by_name["SkillExtension"] < 100
    run_order = [e.name for e in sorted(extensions, key=lambda e: e.priority)]
    assert (
        run_order.index("ReportingMcpExtension") < run_order.index("SkillExtension") < run_order.index("CodingBundle")
    )


def test_a_disable_line_naming_a_plugin_the_program_hands_over_whole_is_logged(tmp_path: Path, caplog):
    config = _config(tmp_path, disabled_plugins=("coding",))

    with caplog.at_level("WARNING", logger="zettcode.plugins"):
        plugins = run(
            loader.Loader(config, runtime_state(config)),
            config,
            builtins=AGENT_PLUGINS,
            entry_points=[],
            required=REQUIRED_AGENT_NAMES,
        )

    assert "coding" in {plugin.name for plugin in plugins.plugins}
    assert {r.plugin for r in caplog.records if r.getMessage() == "plugins.required"} == {"coding"}
