"""Plugins: the ZettCode-owned API, the adapter, and entry-point loading."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.usage import UsageSnapshot
from zettcode.app.commands import CommandResult
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins import (
    Activity,
    ActivityState,
    Plugin,
    PluginAgentMixin,
    PluginContainer,
    PluginEventMixin,
    PluginExtension,
    PluginMaintenanceMixin,
    PluginMiddlewareMixin,
    PluginModelMixin,
    PluginRunMixin,
    Plugins,
    PluginSetupMixin,
    PluginToolMixin,
    PluginTurnMixin,
    PluginUiMixin,
    ShellContext,
    load_plugins,
)
from zettcode.plugins import loader as loader_module
from zettcode.tui import Span, TextLine


def test_the_activity_label_prefers_its_note_over_the_state_word():
    state = ActivityState(
        busy=False,
        status=Activity.READY,
        note=None,
        auto_shell=False,
        usage=UsageSnapshot(),
        tasks=(),
        frame=0,
    )

    assert state.label == "ready"
    assert replace(state, status=Activity.RUNNING, note="/model \u2026").label == "/model \u2026"


class FakeEntryPoint:
    """The slice of ``importlib.metadata.EntryPoint`` the loader touches."""

    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self._target = target

    def load(self) -> object:
        if isinstance(self._target, BaseException):
            raise self._target
        return self._target


class Greeter(Plugin):
    """A plugin with one command and one hook, used across these tests."""

    name = "greeter"
    priority = 42

    def __init__(self) -> None:
        self.seen: list[object] = []

    def activate(self, context: PluginContainer) -> None:
        context.register_command("greet", "say hello", self.greet)

    async def greet(self, argument: str) -> CommandResult:
        return CommandResult(notification=f"hello {argument}".strip())

    async def before_model(self, context, request) -> None:
        self.seen.append(("before_model", request))

    def accept(self, config, event) -> bool:
        self.seen.append(("accept", event))
        return True


def make_config(tmp_path: Path, **overrides: object) -> ZettCodeConfig:
    """Return a minimal validated config, optionally changed for one test."""
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="gpt", token="t"),))
    return replace(config, **overrides) if overrides else config


def loaded_names(plugins: Plugins) -> list[str]:
    """Return the plugin identities in the order the host will call them."""
    return [plugin.name for plugin in plugins.plugins]


async def test_a_class_entry_point_lands_in_the_host_with_its_commands(tmp_path: Path):
    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("greeter", Greeter)])

    # One host carries every plugin, so the agent sees one extension.
    (host,) = plugins.extensions
    assert isinstance(host, PluginExtension)
    assert [type(plugin) for plugin in host.plugins] == [Greeter]
    # The plugin's priority is the host's: the bundle rises to meet it.
    assert host.priority == 42
    (command,) = plugins.commands
    assert (command.name, command.description, command.type) == ("/greet", "say hello", "plugin")
    assert await command.handler("world") == CommandResult(notification="hello world")
    assert plugins.failures == ()


async def test_a_factory_or_an_instance_is_accepted(tmp_path: Path):
    class Factory(Plugin):
        name = "factory"

    class Instance(Plugin):
        name = "instance"

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[
            FakeEntryPoint("factory", lambda: Factory()),
            FakeEntryPoint("instance", Instance()),
        ],
    )

    assert loaded_names(plugins) == ["factory", "instance"]


async def test_a_name_falls_back_to_the_entry_point_and_the_slash_is_optional(tmp_path: Path):
    class Anonymous(Plugin):
        def activate(self, context: PluginContainer) -> None:
            context.register_command("/alias", "no slash needed", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("anon", Anonymous)])

    # The entry-point name is unique within the group, so it is the safer default
    # identity when the author did not name the plugin.
    assert loaded_names(plugins) == ["anon"]
    assert [command.name for command in plugins.commands] == ["/alias"]


async def test_many_plugins_share_one_host(tmp_path: Path):
    class Alpha(Plugin):
        def activate(self, context: PluginContainer) -> None:
            context.register_command("alpha", "first", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Beta(Plugin):
        def activate(self, context: PluginContainer) -> None:
            context.register_command("beta", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("alpha", Alpha), FakeEntryPoint("beta", Beta)],
    )

    (host,) = plugins.extensions
    assert isinstance(host, PluginExtension)
    assert host.priority == 100  # both plugins kept the default
    assert loaded_names(plugins) == ["alpha", "beta"]
    assert [command.name for command in plugins.commands] == ["/alpha", "/beta"]


async def test_two_plugins_with_the_same_class_name_stay_distinct(tmp_path: Path):
    """Same class shipped by two distributions: the entry-point name tells them apart."""

    class Tool(Plugin):
        def __init__(self, command: str) -> None:
            self.command = command

        def activate(self, context: PluginContainer) -> None:
            context.register_command(self.command, "do the thing", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[
            FakeEntryPoint("alpha", lambda: Tool("alpha")),
            FakeEntryPoint("beta", lambda: Tool("beta")),
        ],
    )

    assert loaded_names(plugins) == ["alpha", "beta"]
    assert [command.name for command in plugins.commands] == ["/alpha", "/beta"]
    assert plugins.failures == ()


async def test_two_plugins_cannot_claim_the_same_command(tmp_path: Path):
    """Command lookup takes the first match, so the second claim is rejected."""

    class First(Plugin):
        name = "first"

        def activate(self, context: PluginContainer) -> None:
            context.register_command("run", "first", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Second(Plugin):
        name = "second"

        def activate(self, context: PluginContainer) -> None:
            context.register_command("run", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("first", First), FakeEntryPoint("second", Second)],
    )

    assert loaded_names(plugins) == ["first"]
    assert [command.name for command in plugins.commands] == ["/run"]
    assert plugins.failures == ("second: command /run is already registered by another plugin",)


async def test_a_plugin_cannot_register_a_blank_or_duplicate_command(tmp_path: Path):
    class Blank(Plugin):
        name = "blank"

        def activate(self, context: PluginContainer) -> None:
            context.register_command("", "nothing", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Twice(Plugin):
        name = "twice"

        def activate(self, context: PluginContainer) -> None:
            context.register_command("twice", "first", self.noop)
            context.register_command("twice", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("blank", Blank), FakeEntryPoint("twice", Twice)],
    )

    assert plugins.extensions == () and plugins.plugins == ()
    assert plugins.commands == ()
    assert plugins.failures == (
        "blank: Command name cannot be empty",
        "twice: Command already registered: /twice",
    )


async def test_a_plugin_registers_into_the_four_row_slots(tmp_path: Path):
    class Badge(Plugin):
        name = "badge"

        def activate(self, container: PluginContainer) -> None:
            container.register_header_left(lambda context: f"h:{context.model.name}", name="app")
            container.register_status_right(self.status, name="tokens")

        def status(self, context: ShellContext) -> TextLine:
            return TextLine((Span("s"),))

    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("badge", Badge)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].left] == ["app"]
    assert [segment.name for segment in rows["status"].right] == ["tokens"]
    assert rows["header"].right == rows["status"].left == ()
    assert plugins.failures == ()


def test_the_plugin_base_composes_the_hook_groups():
    """Plugin is the two top-level groups; each agent group sits under the umbrella."""
    assert issubclass(Plugin, PluginAgentMixin) and issubclass(Plugin, PluginUiMixin)
    for group in (
        PluginSetupMixin,
        PluginRunMixin,
        PluginTurnMixin,
        PluginModelMixin,
        PluginToolMixin,
        PluginMaintenanceMixin,
        PluginEventMixin,
        PluginMiddlewareMixin,
    ):
        assert issubclass(PluginAgentMixin, group)


async def test_overriding_a_builder_fills_that_named_slot(tmp_path: Path):
    """The method name is the slot name, so an override lands where the builtin was."""

    class Declared(Plugin):
        name = "declared"

        def render_header_left(self, context: ShellContext) -> str:
            return "h"

        def render_status_right(self, context: ShellContext) -> TextLine:
            return TextLine((Span("s"),))

    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("declared", Declared)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].left] == ["header_left"]
    assert [segment.name for segment in rows["status"].right] == ["status_right"]
    assert plugins.failures == ()


async def test_a_plugin_with_a_plain_status_helper_is_not_captured(tmp_path: Path):
    """Only the documented builder names contribute a segment."""

    class Quiet(Plugin):
        name = "quiet"

        def status(self, context: ShellContext) -> str:  # a private helper, not a segment
            return "not a segment"

    plugins = load_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("quiet", Quiet)])

    assert all(row.left == () and row.right == () for row in plugins.rows)


async def test_a_plugin_overrides_a_builtin_segment_by_name(tmp_path: Path):
    """Bare ``load_plugins`` merges the builtin rows in first, so a same-named
    registration replaces that segment instead of adding a second one."""

    class Mine(Plugin):
        name = "mine"

        def render_header_right(self, context: ShellContext) -> str:
            return "mine"

    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("mine", Mine)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].right] == ["header_right"]
    assert [segment.name for segment in rows["status"].right] == ["status_right"]  # untouched


async def test_a_new_segment_appends_after_the_builtin_one(tmp_path: Path):
    class Branch(Plugin):
        name = "branch"

        def activate(self, container: PluginContainer) -> None:
            container.register_header_right(self.draw, name="branch")

        def draw(self, context: ShellContext) -> str:
            return "main"

    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("branch", Branch)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].right] == ["header_right", "branch"]


async def test_override_clears_the_side_it_names(tmp_path: Path):
    """``override=True`` leaves only the registering plugin's segments there."""

    class Banner(Plugin):
        name = "banner"

        def activate(self, container: PluginContainer) -> None:
            segment, displaced = container.register_status_left(self.draw, override=True)
            assert displaced is True  # the builtin's status_left was already there
            assert segment.name.startswith("segment-")

        def draw(self, context: ShellContext) -> str:
            return "banner"

    plugins = load_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("banner", Banner)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.builder(None) for segment in rows["status"].left] == ["banner"]
    assert rows["status"].right[0].name == "status_right"  # the other side survives


async def test_registering_reports_whether_it_displaced_a_segment(tmp_path: Path):
    """The tuple says what each registration cost: append, replace, or clear."""

    def draw(context: ShellContext) -> str:
        return "x"

    container = PluginContainer(make_config(tmp_path))
    assert container.register_status_left(draw, override=True)[1] is False  # nothing to clear yet
    assert container.register_status_left(draw, name="mine")[1] is False  # a new name appends
    assert container.register_status_left(draw, name="mine")[1] is True  # the same name replaces
    assert container.register_status_left(draw, override=True)[1] is True  # clears the whole side


async def test_disabled_and_switched_off_plugins_are_not_loaded(tmp_path: Path):
    one = FakeEntryPoint("greeter", Greeter)
    assert load_plugins(make_config(tmp_path, plugins_enabled=False), entry_points=[one], builtins=()) == Plugins()
    assert (
        load_plugins(make_config(tmp_path, disabled_plugins=("greeter",)), entry_points=[one], builtins=()) == Plugins()
    )

    # The switch only governs distributions: the builtin rows still load.
    loaded = load_plugins(make_config(tmp_path, plugins_enabled=False), entry_points=[one])
    assert loaded_names(loaded) == ["shell", "skills"]
    assert [row.region for row in loaded.rows] == ["header", "status"]
    assert all(row.left for row in loaded.rows)


async def test_a_broken_plugin_is_reported_and_never_stops_the_others(tmp_path: Path):
    class Exploding(Plugin):
        name = "exploding"

        def activate(self, context: PluginContainer) -> None:
            raise RuntimeError("bad config")

    class NotAPlugin:
        pass

    class Working(Plugin):
        name = "working"

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[
            FakeEntryPoint("exploding", Exploding),
            FakeEntryPoint("not-a-plugin", NotAPlugin),
            FakeEntryPoint("import-error", RuntimeError("cannot import")),
            FakeEntryPoint("working", Working),
        ],
    )

    assert loaded_names(plugins) == ["working"]
    assert plugins.failures == (
        "exploding: bad config",
        "not-a-plugin: factory returned NotAPlugin, not a Plugin",
        "import-error: cannot import",
    )


async def test_a_duplicate_plugin_name_is_rejected(tmp_path: Path):
    class Copy(Plugin):
        name = "greeter"

    plugins = load_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("greeter", Greeter), FakeEntryPoint("copy", Copy)],
    )

    assert loaded_names(plugins) == ["greeter"]
    assert plugins.failures == ("copy: duplicate plugin name 'greeter'",)


async def test_the_host_forwards_every_hook_to_each_plugin():
    one, two = Greeter(), Greeter()
    two.name = "second"
    host = PluginExtension([one, two])
    context, request = object(), object()

    await host.on_tool(context)
    await host.on_state(context)
    await host.on_message(context)
    await host.before_run(context)
    await host.before_turn(context)
    await host.before_model(context, request)
    await host.before_tool(context, request)
    await host.on_compact(context)

    assert host.accept(None, request) is True
    expected = [("before_model", request), ("accept", request)]
    assert one.seen == expected and two.seen == expected


async def test_hooks_fan_out_in_priority_order_and_the_host_rises_with_them():
    calls: list[str] = []

    class Recorder(Plugin):
        def __init__(self, tag: str, priority: int) -> None:
            self.tag = tag
            self.priority = priority

        async def before_model(self, context, request) -> None:
            calls.append(self.tag)

    host = PluginExtension([Recorder("late", 100), Recorder("early", 10), Recorder("middle", 50)])
    await host.before_model(None, None)

    assert calls == ["early", "middle", "late"]
    assert host.priority == 10  # the earliest plugin decides where the bundle sits


async def test_every_plugin_sees_an_external_event_even_after_one_accepts():
    """The agent broadcasts to all extensions; one accept must not mute the rest."""
    seen: list[str] = []

    class Listener(Plugin):
        def __init__(self, tag: str, answer: bool) -> None:
            self.tag = tag
            self.answer = answer

        def accept(self, config, event) -> bool:
            seen.append(self.tag)
            return self.answer

    host = PluginExtension([Listener("first", True), Listener("second", False), Listener("third", True)])

    assert host.accept(None, "event") is True
    assert seen == ["first", "second", "third"]


async def test_the_host_nests_the_model_and_tool_middleware():
    order: list[str] = []

    class Wrapper(Plugin):
        def __init__(self, tag: str, priority: int) -> None:
            self.tag = tag
            self.priority = priority

        async def on_model_request(self, context, request, call_next):
            order.append(f"{self.tag}:in")
            async for event in call_next(request):
                yield event
            order.append(f"{self.tag}:out")

        async def on_tool_call(self, context, call, call_next):
            order.append(f"{self.tag}:tool")
            return await call_next()

    host = PluginExtension([Wrapper("late", 100), Wrapper("early", 10)])

    async def call_next(request):
        order.append("provider")
        yield "event"

    async def tool_next() -> str:
        return "result"

    assert [event async for event in host.on_model_request(None, "request", call_next)] == ["event"]
    assert await host.on_tool_call(None, None, tool_next) == "result"
    assert order == ["early:in", "late:in", "provider", "late:out", "early:out", "early:tool", "late:tool"]


def test_an_empty_host_keeps_the_default_priority():
    host = PluginExtension([])

    assert host.plugins == ()
    assert host.priority == 100


async def test_the_runtime_preview_installs_plugin_extensions_and_commands(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr(loader_module, "installed_entry_points", lambda: (FakeEntryPoint("greeter", Greeter),))

    runtime = runtime_module.ZettCodeRuntime.preview(make_config(tmp_path))

    # The builtin rows load too; a lower priority sorts it after the plugin.
    assert loaded_names(runtime.plugins) == ["greeter", "shell", "skills"]
    assert len(runtime.plugins.extensions) == 1
    assert [command.name for command in runtime.plugins.commands] == ["/greet"]
    assert [row.region for row in runtime.plugins.rows] == ["header", "status"]


async def test_the_built_client_receives_the_plugin_extension(tmp_path: Path, monkeypatch):
    """The host rides in the same extensions list as the built-ins — once."""

    class Second(Plugin):
        name = "second"

    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr(
        loader_module,
        "installed_entry_points",
        lambda: (FakeEntryPoint("greeter", Greeter), FakeEntryPoint("second", Second)),
    )
    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response) -> None:
            pass

        async def aclose(self) -> None:
            pass

    async def fake_create_agent(model, **kwargs):
        captured.update(kwargs)
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)

    runtime = runtime_module.ZettCodeRuntime.preview(make_config(tmp_path))
    await runtime.start()

    names = [type(extension).__name__ for extension in captured["extensions"]]
    assert names.count("PluginExtension") == 1


def test_the_config_reads_the_plugin_switches(tmp_path: Path):
    source = tmp_path / "config.toml"
    source.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins]\nenabled = false\ndisable = ["one"]\n',
        encoding="utf-8",
    )
    from zettcode.config import load_config

    config = load_config(tmp_path, path=source)

    assert config.plugins_enabled is False
    assert config.disabled_plugins == ("one",)


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('[plugins]\nrotos = ["."]\n', "Unknown config keys in the \\[plugins\\] table"),
        ('[plugins]\ndisable = "one"\n', "must be an array of non-empty strings"),
        ('[plugins]\ndisable = [""]\n', "must be an array of non-empty strings"),
        ('[plugins]\nenabled = "yes"\n', "must be bool"),
    ],
)
def test_the_config_rejects_bad_plugin_settings(tmp_path: Path, table: str, message: str):
    source = tmp_path / "config.toml"
    source.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n\n{table}', encoding="utf-8")
    from zettcode.config import load_config

    with pytest.raises(ValueError, match=message):
        load_config(tmp_path, path=source)
