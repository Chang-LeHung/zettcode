"""Plugins that hand the agent extensions, the state they build on, and the services they offer back.

``register_extension`` and ``register_extension_factory`` are how an agent-side feature joins the run without
a hand-written line in the runtime; ``provide`` and ``Plugins.service`` are how the application reaches an
object such a plugin owns, and ``shared`` is how the runtime hands the plugins the state they build on. The
built-in plugins that use them (everything the runtime used to list by hand) are pinned here too.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.extensions.agents_md import AgentsMdExtension
from zett_agent.extensions.ask_user import AskUserExtension
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.skill import SkillExtension
from zett_agent.extensions.todo import TodoWriteExtension
from zett_agent.messages import AssistantMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from plugin_helpers import agent_extensions, agent_plugins, runtime_inputs
from zettcode.app.agent.agent import TerminalAgent
from zettcode.app.plugins import BUILTIN_PLUGINS
from zettcode.ask_user import AskUser
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.plugins import (
    AgentBuild,
    Plugin,
    PluginContext,
    Plugins,
    load_plugins,
)
from zettcode.engine.plugins import services as names
from zettcode.instructions import ProjectInstructions
from zettcode.sdk.builtins import AGENT_PLUGINS, load_agent_plugins
from zettcode.sdk.messenger import Messenger
from zettcode.todos import TodoPlan


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


def offering(plugin_name: str, *ext_names: str, service: str | None = None) -> type[Plugin]:
    """Return a plugin class that registers one extension per name, and maybe a service."""

    class Offering(Plugin):
        name = plugin_name

        def activate(self, ctx: PluginContext) -> None:
            for name in ext_names:
                ctx.agent.register_extension(Named(name))
            if service is not None:
                ctx.agent.provide(service, object())

    return Offering


def load(tmp_path: Path, *plugins: type[Plugin], shared: dict[str, object] | None = None, **overrides: object):
    """Load these plugin classes alone, without the built-in ones."""
    points = [FakeEntryPoint(plugin.name, plugin) for plugin in plugins]
    return load_plugins(make_config(tmp_path, **overrides), builtins=(), entry_points=points, shared=shared)


def built_names(plugins: Plugins) -> list[str]:
    """Return the names of the extensions the plugins hand the agent, factories built."""
    return [extension.name for extension in plugins.agent_extensions(AgentBuild(model=object()))]  # type: ignore[arg-type]


# -- an extension handed over whole ---------------------------------------------------------------


def test_a_plugin_hands_the_agent_its_own_extension_in_registration_order(tmp_path):
    plugins = load(tmp_path, offering("first", "a", "b"), offering("second", "c"))

    assert built_names(plugins) == ["a", "b", "c"]
    assert plugins.failures == ()


def test_registering_one_extension_name_twice_fails_the_plugin(tmp_path):
    plugins = load(tmp_path, offering("twice", "dup", "dup"))

    assert plugins.contributed == () and any("Extension already registered: dup" in f for f in plugins.failures)


def test_an_extension_must_have_a_name(tmp_path):
    plugins = load(tmp_path, offering("nameless", "  "))

    assert plugins.contributed == () and any("non-empty name" in f for f in plugins.failures)


def test_two_plugins_cannot_share_an_extension_name_and_the_host_name_is_taken(tmp_path):
    plugins = load(tmp_path, offering("one", "shared"), offering("two", "shared"), offering("three", "plugins"))

    assert built_names(plugins) == ["shared"]
    assert any("two: extension shared is already registered" in f for f in plugins.failures)
    assert any("three: extension plugins is already registered" in f for f in plugins.failures)


def test_a_plugin_that_fails_after_registering_leaves_nothing_behind(tmp_path):
    class Late(Plugin):
        name = "late"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_extension(Named("late-ext"))
            ctx.agent.provide("late-service", object())
            raise RuntimeError("boom")

    plugins = load(tmp_path, Late)

    assert plugins.contributed == () and set(plugins.services) == set()
    assert any("boom" in f for f in plugins.failures)


# -- an extension built when the agent is ---------------------------------------------------------


def factory_plugin(plugin_name: str, ext_name: str, built: list[object], *, make: bool = True) -> type[Plugin]:
    """Return a plugin whose extension is a factory that records what it was called with."""

    class Lazy(Plugin):
        name = plugin_name

        def activate(self, ctx: PluginContext) -> None:
            def build(agent: AgentBuild) -> AgentExtension | None:
                built.append(agent)
                return Named(ext_name) if make else None

            ctx.agent.register_extension_factory(ext_name, build)

    return Lazy


def test_a_factory_is_not_called_until_the_agent_is_built(tmp_path):
    built: list[object] = []
    plugins = load(tmp_path, factory_plugin("lazy", "lazy-ext", built))

    assert built == [] and plugins.agent_extensions() == ()
    model = object()
    (extension,) = plugins.agent_extensions(AgentBuild(model=model))  # type: ignore[arg-type]

    assert extension.name == "lazy-ext" and [agent.model for agent in built] == [model]  # type: ignore[attr-defined]


def test_whole_extensions_and_factories_keep_the_order_they_were_registered_in(tmp_path):
    class Mixed(Plugin):
        name = "mixed"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_extension(Named("a"))
            ctx.agent.register_extension_factory("b", lambda agent: Named("b"))
            ctx.agent.register_extension(Named("c"))

    assert built_names(load(tmp_path, Mixed, offering("after", "d"))) == ["a", "b", "c", "d"]


def test_a_factory_may_have_nothing_to_add(tmp_path):
    plugins = load(tmp_path, factory_plugin("none", "absent", [], make=False), offering("some", "present"))

    assert built_names(plugins) == ["present"]


def test_a_factory_that_builds_another_name_than_it_announced_fails_the_build(tmp_path):
    class Liar(Plugin):
        name = "liar"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_extension_factory("claimed", lambda agent: Named("other"))

    with pytest.raises(ValueError, match="registered as 'claimed' was built as 'other'"):
        built_names(load(tmp_path, Liar))


def test_a_factory_name_is_checked_against_the_others_when_the_plugins_load(tmp_path):
    plugins = load(tmp_path, offering("whole", "x"), factory_plugin("lazy", "x", []))

    assert [contribution.name for contribution in plugins.contributed] == ["x"]
    assert any("lazy: extension x is already registered" in f for f in plugins.failures)


# -- state handed over by the runtime, and services provided back ---------------------------------


def test_a_plugin_reads_what_the_runtime_handed_over(tmp_path):
    seen: list[object] = []

    class Reader(Plugin):
        name = "reader"

        def activate(self, ctx: PluginContext) -> None:
            seen.append(ctx.service("policy", str))
            seen.append(ctx.agent.find("absent", str))

    plugins = load(tmp_path, Reader, shared={"policy": "ask"})

    assert seen == ["ask", None] and plugins.failures == ()
    assert plugins.service("policy", str) == "ask"


def test_a_plugin_that_needs_state_nobody_handed_over_is_reported_by_name(tmp_path):
    class Needy(Plugin):
        name = "needy"

        def activate(self, ctx: PluginContext) -> None:
            ctx.service("persistence", object)

    plugins = load(tmp_path, Needy)

    assert any("needy: " in f and "'persistence'" in f for f in plugins.failures)


def test_a_plugin_reads_what_an_earlier_one_provided_and_not_what_a_later_one_will(tmp_path):
    class Early(Plugin):
        name = "early"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.provide("made", [1])

    class Late(Plugin):
        name = "late"

        def activate(self, ctx: PluginContext) -> None:
            assert ctx.service("made", list) == [1]

    class Backwards(Plugin):
        name = "backwards"

        def activate(self, ctx: PluginContext) -> None:
            ctx.service("made-later", list)

    class Last(Plugin):
        name = "last"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.provide("made-later", [2])

    plugins = load(tmp_path, Early, Late, Backwards, Last)

    assert [f.split(":")[0] for f in plugins.failures] == ["backwards"]


def test_a_service_is_found_by_name_and_checked_for_its_type(tmp_path):
    class Keeper(Plugin):
        name = "keeper"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.provide("numbers", [1, 2])

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

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.provide("x", 1)
            ctx.agent.provide("x", 2)

    plugins = load(tmp_path, Twice, offering("one", service="shared"), offering("two", service="shared"))

    assert set(plugins.services) == {"shared"}
    assert any("Service already provided: x" in f for f in plugins.failures)
    assert any("two: service shared is already provided" in f for f in plugins.failures)


def test_a_plugin_cannot_provide_a_name_the_runtime_handed_over(tmp_path):
    plugins = load(tmp_path, offering("grab", service="policy"), shared={"policy": "ask"})

    assert plugins.service("policy", str) == "ask"
    assert any("grab: service policy is already provided" in f for f in plugins.failures)


def test_a_service_name_cannot_be_blank(tmp_path):
    plugins = load(tmp_path, offering("blank", service=" "))

    assert set(plugins.services) == set() and any("Service name cannot be empty" in f for f in plugins.failures)


# -- the built-in plugins that carry the agent's own extensions -----------------------------------


def test_the_agent_plugins_load_without_failures_and_have_distinct_names(tmp_path):
    plugins = agent_plugins(make_config(tmp_path))

    assert plugins.failures == ()
    listed = [plugin.name for plugin in (*BUILTIN_PLUGINS, *AGENT_PLUGINS)]
    assert len(listed) == len(set(listed))


def test_a_long_result_is_shortened_before_the_store_sees_it(tmp_path):
    """The store is an extension as well: a result it takes first is the megabyte this one exists to keep out."""
    names = [extension.name for extension in agent_extensions(make_config(tmp_path))]

    assert names.index("LongOutputExtension") < names.index("SessionStore")


def test_a_run_with_the_optional_tools_off_hands_the_agent_the_extensions_in_registration_order(tmp_path):
    extensions = agent_extensions(make_config(tmp_path, skills_enabled=False, subagent_enabled=False))

    # `AskUserExtension` is first and `AgentsMdExtension` stands where the `project-instructions` part sorts: the
    # parts that came out of the SDK's list (`ask-user`, `project-instructions`, `todos`, and now `long-output`,
    # `tool-guidelines` and `tool-output`) have no rank of their own, so they are activated at rank 0, ahead of the
    # SDK's `capabilities`, and register their extensions there. What the agent runs in which order is each
    # extension's priority (see the run-order list below), not this list.
    assert [extension.name for extension in extensions] == [
        "AskUserExtension",
        "CodingBundle",
        "SwitchedHarness",
        "LongOutputExtension",
        "AgentsMdExtension",
        "ToolGuidelinesExtension",
        "ToolOutputExtension",
        "ModelCapabilities",
        "ShellDenyExtension",
        "ShellApprovalExtension",
        "SessionStore",
        "UsageExtension",
        "ContextExtension",
        "SideQuestions",
        "OnDemandCompaction",
    ]
    # The order the agent keeps them in: a stable sort by priority. Compared with the list the SDK alone gave, the
    # rank-0 parts moved — `AskUserExtension` first, and `LongOutputExtension`, `ToolGuidelinesExtension` and
    # `ToolOutputExtension` now register ahead of the SDK's own band instead of inside it. They share the 100 with
    # `ShellApprovalExtension`, the store and the counters, so among those their new registration order is the order
    # the agent runs them in: `LongOutputExtension` before the store (as before, and required), the guidance and the
    # shell's kept output before the approval. Nothing they compete with moved: `AgentsMdExtension` is still first on
    # its 10, the permissions still run at 50, and the capabilities and side questions at 110 and 120.
    assert [extension.name for extension in sorted(extensions, key=lambda extension: extension.priority)] == [
        "AgentsMdExtension",
        "ShellDenyExtension",
        "AskUserExtension",
        "CodingBundle",
        "LongOutputExtension",
        "ToolGuidelinesExtension",
        "ToolOutputExtension",
        "ShellApprovalExtension",
        "SessionStore",
        "UsageExtension",
        "ContextExtension",
        "OnDemandCompaction",
        "ModelCapabilities",
        "SideQuestions",
        "SwitchedHarness",
    ]


def test_a_coding_child_is_given_these_of_the_extensions_the_parent_runs_and_not_those(tmp_path):
    """The parent's real list, with every switch on: a child is the parent without the complicated parts."""
    from zettcode.sdk.builtins import _shared_with_children

    messenger = object.__new__(Messenger)
    config = make_config(tmp_path, todowrite_enabled=True, subagent_enabled=True, skills_enabled=True)
    parent = agent_extensions(config, **{names.MESSENGER: messenger})

    shared = [e.name for e in parent if _shared_with_children(messaging=False)(e)]
    with_messaging = [e.name for e in parent if _shared_with_children(messaging=True)(e)]

    # The skills are a part of their own, activated ahead of the SDK's; where they stand at run time is their priority.
    # The per-tool guidance is read fresh by every child and so is not shared; the two extensions that keep output in
    # the session's folder are, and the shell's kept-output one is now handed over with the rank-0 parts.
    assert shared == [
        "CodingBundle",
        "LongOutputExtension",
        "SkillExtension",
        "ToolOutputExtension",
        "ShellDenyExtension",
        "ShellApprovalExtension",
        "OnDemandCompaction",
    ]
    assert "ParentModelSubAgents" not in shared and "SwitchedHarness" not in shared, "no task, no harness"
    assert "AskUserExtension" not in shared, "a child works through its task; it does not ask the person"
    assert "TodoWriteExtension" not in shared, "its plan would be drawn for nobody"
    assert with_messaging == [*shared[:4], "SessionMessagingExtension", *shared[4:]]


def test_every_switch_adds_its_extension_at_its_place(tmp_path):
    messenger = object.__new__(Messenger)
    config = make_config(tmp_path, todowrite_enabled=True, subagent_enabled=True, skills_enabled=True)
    names_ = [extension.name for extension in agent_extensions(config, **{names.MESSENGER: messenger})]

    assert names_ == [
        # The parts of other distributions that used to be listed here (`ask-user`, `project-instructions`, `todos`)
        # and the three that left the SDK's list for their own (`long-output`, `tool-guidelines`, `tool-output`) are
        # activated at rank 0, sorted by name, so their extensions register ahead of the SDK's `capabilities`.
        "AskUserExtension",
        "CodingBundle",
        "SwitchedHarness",
        "LongOutputExtension",
        "AgentsMdExtension",
        "SkillExtension",
        "TodoWriteExtension",
        "ToolGuidelinesExtension",
        "ToolOutputExtension",
        "ModelCapabilities",
        "ParentModelSubAgents",
        "SessionMessagingExtension",
        "ShellDenyExtension",
        "ShellApprovalExtension",
        "SessionStore",
        "UsageExtension",
        "ContextExtension",
        "SideQuestions",
        "OnDemandCompaction",
    ]


def test_the_order_the_agent_runs_them_in_is_the_priority_of_each(tmp_path):
    """The list above is registration order; the agent keeps a stable sort by priority, and that is the real order.

    Compared with the order the SDK's own list alone used to give, the parts of other distributions moved into the
    band they share: `ask-user` and `todos` left the list for their own distributions, and `long-output`,
    `tool-guidelines` and `tool-output` left it the same way. All of them are activated at rank 0 with a priority of
    their own (100 for these five, 80 for the skills), so they are handed over, and so run, first among the 100 band.
    `AgentsMdExtension` is still first on its 10, the permissions still run at 50 (the deny before the approval),
    the skills at 80, and the capabilities and side questions at 110 and 120. Nothing is ordered against anything it
    competes with: the question tool, the plan tool, the guidance and the two output keepers are features of their
    own, and the store still comes after `LongOutputExtension`, which is the one ordering that matters.
    """
    extensions = agent_extensions(make_config(tmp_path, todowrite_enabled=True))

    assert [extension.name for extension in sorted(extensions, key=lambda extension: extension.priority)] == [
        "AgentsMdExtension",
        "ShellDenyExtension",
        "SkillExtension",
        "AskUserExtension",
        "CodingBundle",
        "LongOutputExtension",
        "TodoWriteExtension",
        "ToolGuidelinesExtension",
        "ToolOutputExtension",
        "ParentModelSubAgents",
        "ShellApprovalExtension",
        "SessionStore",
        "UsageExtension",
        "ContextExtension",
        "OnDemandCompaction",
        "ModelCapabilities",
        "SideQuestions",
        "SwitchedHarness",
    ]


class _RecordingModel:
    """A model adapter that answers at once and keeps the tools each request offered it."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.offered: list[list[str]] = []

    async def stream(self, request):
        self.offered.append([tool.name for tool in request.tools])
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))


async def test_the_tools_the_model_is_offered_are_in_the_order_the_extensions_registered_them(tmp_path):
    """The one place registration order is visible: the tools array the provider is handed.

    The agent builds it as ``tuple(tool.definition for tool in context.tools.values())`` after every extension's
    ``on_tool`` has run in priority order, so within one priority it is the order the extensions registered their
    tools in. That is why this test changes when `ask-user` or `todos` move: both are parts of other distributions now,
    activated at rank 0, so `ask_user` is offered before the coding bundle's `read` and `todo_write` before the
    subagents' `task`, where the old list put them last and second to last. Nothing reads a tool's position — the
    model picks one by name and every extension finds its own — so this array is the whole effect of the move.
    """
    config = make_config(tmp_path, todowrite_enabled=True, subagent_enabled=True, skills_enabled=True)
    model = _RecordingModel()
    agent = await Agent.create(
        model,  # type: ignore[arg-type]
        config=AgentRunConfig(session_id="s"),
        extensions=list(agent_extensions(config)),
    )

    [event async for event in agent.stream("hi", config=AgentRunConfig(session_id="s"))]

    assert model.offered == [["ask_user", "read", "write_file", "edit", "bash", "todo_write", "task"]]


def test_switching_the_optional_extensions_off_leaves_them_out(tmp_path):
    config = make_config(tmp_path, ask_user_enabled=False, agents_md_enabled=False, skills_enabled=False)
    kinds = {type(extension) for extension in agent_extensions(config)}

    assert not kinds & {AskUserExtension, AgentsMdExtension, SkillExtension, TodoWriteExtension}


def test_every_factory_announces_the_name_it_builds(tmp_path):
    """Built with everything switched on, so a name that drifts from its class fails here and not at a first turn."""
    servers = tmp_path / "mcp.json"
    servers.write_text('{"servers": {"docs": {"type": "streamable-http", "url": "http://127.0.0.1:9/mcp"}}}')
    config = make_config(
        tmp_path,
        subagent_enabled=True,
        skills_enabled=True,
        mcp_enabled=True,
        mcp_config=servers,
        todowrite_enabled=True,
    )
    plugins = agent_plugins(config, **{names.MESSENGER: object.__new__(Messenger)})

    built = plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]

    assert plugins.failures == ()
    assert len(built) == len(plugins.contributed) and "ReportingMcpExtension" in [e.name for e in built]


def test_the_plan_is_always_reachable_yet_only_handed_to_the_agent_when_the_tool_is_on(tmp_path):
    off = agent_plugins(make_config(tmp_path))
    on = agent_plugins(make_config(tmp_path, todowrite_enabled=True))

    assert off.service("todos", TodoWriteExtension) not in off.agent_extensions()
    assert on.service("todos", TodoWriteExtension) in on.agent_extensions()


# -- the runtime ----------------------------------------------------------------------------------


def test_the_runtime_reads_its_extensions_back_from_the_plugins_that_made_them(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeEngine.preview(make_config(tmp_path), load_agent_plugins)
    plugins = runtime.plugins

    assert runtime.usage is plugins.service(names.USAGE, object)
    assert runtime.context is plugins.service(names.CONTEXT, object)
    assert runtime.sides is plugins.service(names.SIDES, object)
    assert runtime.approval is plugins.service(names.APPROVAL, object)
    assert runtime.compaction is plugins.service(names.COMPACTION, object)
    # What the plugins build on is the runtime's own, not a copy.
    assert plugins.service(names.PERSISTENCE, object) is runtime.persistence
    assert plugins.service(names.POLICY, object) is runtime.policy
    assert plugins.service(names.MODELS, dict) is runtime._models
    assert runtime.compaction.max_tokens == runtime.active_model.compaction_max_tokens
    assert runtime.plugins.failures == ()


def test_a_bundle_without_the_todo_plugin_shows_no_plan_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeEngine.preview(make_config(tmp_path), load_agent_plugins)
    runtime.plugins = Plugins()

    assert runtime.todos is None
    assert TerminalAgent(runtime).tasks() == ()


async def test_the_runtime_gives_the_agent_the_plugins_extensions_then_the_host(tmp_path, monkeypatch):
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
    runtime = runtime_module.ZettCodeEngine.preview(config, load_agent_plugins)
    extra = FakeEntryPoint("extra", offering("extra", "extra-ext"))
    # The parts of other distributions are passed here the way discovery would offer them: this test replaces
    # discovery with one entry point of its own, and the plan is one of them now.
    runtime.plugins = load_plugins(
        config,
        builtins=(*AGENT_PLUGINS, AskUser(), ProjectInstructions(), TodoPlan()),
        entry_points=[extra],
        shared=runtime_inputs(runtime),
    )
    await runtime.start()

    (extensions,) = given
    listed = [extension.name for extension in extensions]
    # The built-in ones first, the compaction the last of them; a third-party one after, the host last.
    assert listed[0] == "CodingBundle"
    assert listed.index("OnDemandCompaction") < listed.index("extra-ext") < listed.index("plugins")
    assert listed[-1] == "plugins"
    # The plan the shell reads is the extension the agent runs, and the usage it shows is what is counted.
    assert runtime.todos in extensions and runtime.usage in extensions and runtime.compaction in extensions
    await runtime.aclose()
