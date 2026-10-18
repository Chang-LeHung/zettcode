"""Plugins that hand the agent a whole extension, and the services one plugin offers the application.

``register_extension`` is how an agent-side feature joins the run without a hand-written line in the
runtime, and ``provide`` is how the application reaches an object such a plugin owns. The built-in plugins
that use them (the todo tool, the ``ask_user`` tool, the project instructions) are pinned here too.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from zett_agent.extensions.agents_md import AgentsMdExtension
from zett_agent.extensions.ask_user import AskUserExtension
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.todo import TodoWriteExtension

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins import BUILTIN_PLUGINS, Plugin, PluginContainer, Plugins, load_plugins


class FakeEntryPoint:
    """The slice of ``importlib.metadata.EntryPoint`` the loader touches."""

    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self._target = target

    def load(self) -> object:
        return self._target


class Named(AgentExtension):
    """An extension that does nothing and is told its name."""

    def __init__(self, name: str, priority: int = 100) -> None:
        self.name = name
        self.priority = priority


def make_config(tmp_path: Path, **overrides: object) -> ZettCodeConfig:
    """Return a minimal validated config for a workspace, optionally changed for one test."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="gpt", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
    )
    return replace(config, **overrides) if overrides else config


def offering(plugin_name: str, *names: str, service: str | None = None) -> type[Plugin]:
    """Return a plugin class that registers one extension per name, and maybe a service."""

    class Offering(Plugin):
        name = plugin_name

        def activate(self, container: PluginContainer) -> None:
            for name in names:
                container.register_extension(Named(name))
            if service is not None:
                container.provide(service, object())

    return Offering


def load(tmp_path: Path, *plugins: type[Plugin], **overrides: object) -> Plugins:
    """Load these plugin classes alone, without the built-in ones."""
    points = [FakeEntryPoint(plugin.name, plugin) for plugin in plugins]
    return load_plugins(make_config(tmp_path, **overrides), builtins=(), entry_points=points)


def test_a_plugin_hands_the_agent_its_own_extension_in_registration_order(tmp_path):
    plugins = load(tmp_path, offering("first", "a", "b"), offering("second", "c"))

    assert [extension.name for extension in plugins.contributed] == ["a", "b", "c"]
    assert plugins.failures == ()


def test_registering_one_extension_name_twice_fails_the_plugin(tmp_path):
    plugins = load(tmp_path, offering("twice", "dup", "dup"))

    assert plugins.contributed == () and any("Extension already registered: dup" in f for f in plugins.failures)


def test_an_extension_must_have_a_name(tmp_path):
    plugins = load(tmp_path, offering("nameless", "  "))

    assert plugins.contributed == () and any("non-empty name" in f for f in plugins.failures)


def test_two_plugins_cannot_share_an_extension_name_and_the_host_name_is_taken(tmp_path):
    plugins = load(tmp_path, offering("one", "shared"), offering("two", "shared"), offering("three", "plugins"))

    assert [extension.name for extension in plugins.contributed] == ["shared"]
    assert any("two: extension shared is already registered" in f for f in plugins.failures)
    assert any("three: extension plugins is already registered" in f for f in plugins.failures)


def test_a_plugin_that_fails_after_registering_leaves_nothing_behind(tmp_path):
    class Late(Plugin):
        name = "late"

        def activate(self, container: PluginContainer) -> None:
            container.register_extension(Named("late-ext"))
            container.provide("late-service", object())
            raise RuntimeError("boom")

    plugins = load(tmp_path, Late)

    assert plugins.contributed == () and plugins.services == {}
    assert any("boom" in f for f in plugins.failures)


def test_a_service_is_found_by_name_and_checked_for_its_type(tmp_path):
    class Keeper(Plugin):
        name = "keeper"

        def activate(self, container: PluginContainer) -> None:
            container.provide("numbers", [1, 2])

    plugins = load(tmp_path, Keeper)

    assert plugins.service("numbers", list) == [1, 2]
    assert plugins.find("numbers", list) == [1, 2]
    assert plugins.find("missing", list) is None
    with pytest.raises(TypeError, match="'numbers' is a list, not a dict"):
        plugins.find("numbers", dict)
    with pytest.raises(TypeError, match="'numbers' is a list, not a dict"):
        plugins.service("numbers", dict)
    with pytest.raises(LookupError, match="'missing'"):
        plugins.service("missing", list)


def test_a_service_name_is_provided_once(tmp_path):
    class Twice(Plugin):
        name = "twice"

        def activate(self, container: PluginContainer) -> None:
            container.provide("x", 1)
            container.provide("x", 2)

    plugins = load(tmp_path, Twice, offering("one", service="shared"), offering("two", service="shared"))

    assert set(plugins.services) == {"shared"}
    assert any("Service already provided: x" in f for f in plugins.failures)
    assert any("two: service shared is already provided" in f for f in plugins.failures)


def test_a_service_name_cannot_be_blank(tmp_path):
    plugins = load(tmp_path, offering("blank", service=" "))

    assert plugins.services == {} and any("Service name cannot be empty" in f for f in plugins.failures)


# -- the built-in plugins that carry agent extensions ---------------------------------------------


def test_the_built_in_agent_plugins_load_without_failures(tmp_path):
    plugins = load_plugins(make_config(tmp_path), entry_points=[])

    assert plugins.failures == ()
    assert {type(plugin).__name__ for plugin in plugins.plugins} >= {"AskUser", "ProjectInstructions", "TodoPlan"}


def test_the_default_config_contributes_the_ask_tool_and_the_instructions_but_not_the_todo_tool(tmp_path):
    kinds = {type(extension) for extension in load_plugins(make_config(tmp_path), entry_points=[]).contributed}

    assert kinds == {AskUserExtension, AgentsMdExtension}


def test_the_todo_tool_is_contributed_only_when_it_is_switched_on_yet_the_plan_is_always_reachable(tmp_path):
    off = load_plugins(make_config(tmp_path), entry_points=[])
    on = load_plugins(make_config(tmp_path, todowrite_enabled=True), entry_points=[])

    todos = on.service("todos", TodoWriteExtension)
    assert todos in on.contributed
    assert off.service("todos", TodoWriteExtension) not in off.contributed


def test_the_built_in_agent_plugins_have_distinct_names():
    names = [plugin.name for plugin in BUILTIN_PLUGINS]

    assert len(names) == len(set(names))


def test_a_bundle_without_the_todo_plugin_shows_no_plan_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeRuntime.preview(make_config(tmp_path))
    runtime.plugins = Plugins()

    assert runtime.todos is None
    assert ZettCodeAgent(runtime).tasks() == ()


async def test_the_runtime_gives_the_agent_what_the_plugins_contributed_before_compaction(tmp_path, monkeypatch):
    given: list[list[AgentExtension]] = []

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.closed = False

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        given.append(list(kwargs["extensions"]))
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)

    config = make_config(tmp_path, todowrite_enabled=True)
    runtime = runtime_module.ZettCodeRuntime.preview(config)
    runtime.plugins = load_plugins(config, entry_points=[FakeEntryPoint("extra", offering("extra", "extra-ext"))])
    await runtime.start()

    (extensions,) = given
    names = [extension.name for extension in extensions]
    contributed = [extension.name for extension in runtime.plugins.contributed]
    assert "extra-ext" in contributed
    # Every contributed extension is handed over, in order, ahead of the compaction and the host.
    positions = [names.index(name) for name in contributed]
    assert positions == sorted(positions)
    assert max(positions) < extensions.index(runtime.compaction) < extensions.index(runtime.plugins.host)
    # The plan the shell reads is the extension the agent runs.
    assert runtime.todos in extensions
    await runtime.aclose()
