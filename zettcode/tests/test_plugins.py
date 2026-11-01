"""Plugins: the ZettCode-owned API, the adapter, and entry-point loading."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from zettcode.app.agent.conversation.entries import EditEntry, EntryKind, ReadEntry, TextEntry
from zettcode.app.agent.conversation.presenters import Presenter
from zettcode.app.commands import CommandContext, CommandResult, CommandUi
from zettcode.app.plugins import (
    BUILTIN_PLUGINS,
    HOST_LINK,
    Activity,
    ActivityState,
    PluginContext,
    PluginUiMixin,
    ShellContext,
    TuiPlugin,
    TuiPlugins,
    load_terminal_plugins,
)
from zettcode.app.plugins.loader import terminal_context, terminal_plugins
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.extensions.usage import UsageSnapshot
from zettcode.engine.plugins import (
    AGENT_PLUGINS,
    PluginAgentMixin,
    PluginEventMixin,
    PluginExtension,
    PluginMaintenanceMixin,
    PluginMiddlewareMixin,
    PluginModelMixin,
    PluginRunMixin,
    PluginSetupMixin,
    PluginToolMixin,
    PluginTurnMixin,
)
from zettcode.engine.plugins import loader as loader_module
from zettcode.providers import Provider
from zettcode.tui import DARK, Span, Style, TextLine


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


class _SilentUi(CommandUi):
    """A set of surfaces that keeps what a command says, for the tests that only read the result."""

    def markdown(self, text: str) -> None:
        self.said.append(text)

    def notice(self, text: str) -> None:
        self.said.append(text)

    def error(self, text: str) -> None:
        self.said.append(text)

    def notify(self, text: str, *, level: str = "info") -> None:
        self.said.append(text)

    said: list[str]

    def __init__(self) -> None:
        self.said = []


class Greeter(TuiPlugin):
    """A plugin with one command and one hook, used across these tests."""

    name = "greeter"
    priority = 42

    def __init__(self) -> None:
        self.seen: list[object] = []

    def activate(self, ctx: PluginContext) -> None:
        assert ctx.tui is not None
        ctx.tui.register_command("greet", "say hello", self.greet)

    async def greet(self, argument: str) -> CommandResult:
        return CommandResult(notification=f"hello {argument}".strip())

    async def before_model(self, context, request) -> None:
        self.seen.append(("before_model", request))

    def accept(self, config, event) -> bool:
        self.seen.append(("accept", event))
        return True


class _TerminalOnly(TuiPlugin):
    """A plugin that registers a command: the shell's, and nobody else's."""

    name = "only-in-the-terminal"
    description = "a command a process without a screen never gets"

    def activate(self, ctx: PluginContext) -> None:
        assert ctx.tui is not None
        ctx.tui.register_command("hello", "say hello", lambda context: _noop())


async def _noop():
    return CommandResult()


def test_a_context_without_a_screen_has_no_tui_group(tmp_path: Path):
    """One context type: what it can hold is the groups it has, and a process with no terminal has no ``tui``."""
    headless = PluginContext(make_config(tmp_path), {})
    terminal = terminal_context(make_config(tmp_path))

    assert headless.tui is None, "no screen, no group: `if ctx.tui is None` is the plugin's guard"
    assert terminal.tui is not None
    assert headless.agent is not None and headless.commands is not None


async def test_a_plain_command_that_fails_is_reported_as_one(tmp_path: Path):
    """The plain result has three cases; the shell has two, so the third has to become its error path."""

    class Failing(TuiPlugin):
        name = "plain-failing"

        def activate(self, ctx: PluginContext) -> None:

            async def fail(context) -> object:
                raise ValueError("no such session")

            ctx.commands.register("/fail", "fail on purpose", fail)

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("failing", Failing)]
    )
    (command,) = plugins.commands

    with pytest.raises(ValueError, match="no such session"):
        await command.handler(CommandContext(argument="", ui=_SilentUi()))


async def test_two_plugins_cannot_claim_one_plain_command_name(tmp_path: Path):
    """``ctx.commands`` shares the shell's one namespace: the second claimant is refused, not shadowed."""

    class First(TuiPlugin):
        name = "first"

        def activate(self, ctx: PluginContext) -> None:
            ctx.commands.register("/dup", "first", _plain("first"))

    class Second(TuiPlugin):
        name = "second"

        def activate(self, ctx: PluginContext) -> None:
            ctx.commands.register("/dup", "second", _plain("second"))

    plugins = load_terminal_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("first", First), FakeEntryPoint("second", Second)],
    )

    assert plugins.failures and "/dup" in plugins.failures[0], plugins.failures


def _plain(text: str):
    from zettcode.engine.plugins.commands import TextCommandResult

    async def handler(context) -> object:
        return TextCommandResult(message=text)

    return handler


async def test_a_plain_command_reaches_the_shell_beside_the_tuis_own(tmp_path: Path):
    """A plugin's ``ctx.commands`` entry is an ordinary command in the terminal: text and a toast, no page."""

    class Greeter(TuiPlugin):
        name = "plain-greeter"

        def activate(self, ctx: PluginContext) -> None:
            async def greet(context) -> object:
                from zettcode.engine.plugins.commands import TextCommandResult

                return TextCommandResult(message=f"hello {context.argument}", notification="said hello")

            ctx.commands.register("/greet", "say hello", greet)

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("greeter", Greeter)]
    )
    (command,) = plugins.commands

    result = await command.handler(CommandContext(argument="Ada", ui=_SilentUi()))

    assert (command.name, command.type, command.description) == ("/greet", "plugin", "say hello")
    assert (result.message, result.notification, result.widget) == ("hello Ada", "said hello", None)


async def test_a_document_a_plain_command_answers_with_opens_as_a_page(tmp_path: Path):
    """A ``markdown`` document is a page of the terminal's own, not another line in the conversation."""

    class Notes(TuiPlugin):
        name = "plain-notes"

        def activate(self, ctx: PluginContext) -> None:
            from zettcode.engine.plugins.commands import TextCommandResult

            ctx.commands.register(
                "/notes", "read the notes", lambda context: TextCommandResult(markdown="# Notes\n\nAll quiet.")
            )

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("notes", Notes)])
    (command,) = plugins.commands

    result = await command.handler(CommandContext(argument="", ui=_SilentUi()))

    from zettcode.app.ui.widgets import DocumentPage

    assert result.message == ""
    assert isinstance(result.widget, DocumentPage)
    assert result.widget.document.text == "# Notes\n\nAll quiet."
    assert result.widget.title == "/notes", "the page says which command opened it"


async def test_a_plain_command_with_a_message_only_still_opens_no_page(tmp_path: Path):
    """The document is a field beside the old ones, so a command written before it behaves as it did."""

    class Plain(TuiPlugin):
        name = "plain-only"

        def activate(self, ctx: PluginContext) -> None:
            from zettcode.engine.plugins.commands import TextCommandResult

            ctx.commands.register("/plain", "just words", lambda context: TextCommandResult(message="ok"))

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("plain", Plain)])
    (command,) = plugins.commands

    result = await command.handler(CommandContext(argument="", ui=_SilentUi()))

    assert (result.message, result.widget) == ("ok", None)


class _RecordingHost:
    """A shell that records the turn a preset asks it to start."""

    class _Client:
        permission = "ask"

    def __init__(self) -> None:
        self.client = self._Client()
        self.prompts: list[tuple[str, str | None, str | None]] = []

    async def prompt(self, text: str, *, shown: str | None = None, cache: str | None = None) -> bool:
        self.prompts.append((text, shown, cache))
        return True


async def test_a_preset_hands_the_cache_mode_it_asked_for_to_the_turn(tmp_path: Path):
    """A one-off report is worth reading the cache without extending it, and the preset says which it is."""

    class Review(TuiPlugin):
        name = "plain-review"

        def activate(self, ctx: PluginContext) -> None:
            from zettcode.engine.plugins.commands import TurnCommandResult

            ctx.commands.register(
                "/review",
                "review it",
                lambda context: TurnCommandResult(prompt="the brief", shown="/review", cache="read"),
            )

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("review", Review)])
    (command,) = plugins.commands
    host = _RecordingHost()

    await command.handler(CommandContext(argument="", ui=_SilentUi(), host=host))  # type: ignore[arg-type]

    assert host.prompts == [("the brief", "/review", "read")]


def test_a_plugin_declares_its_settings_and_the_readers_value_wins(tmp_path: Path):
    """The configuration cannot know a plugin's keys, so the plugin says what they are and what they default to."""
    source = tmp_path / "config.toml"
    source.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins.recap]\nafter_seconds = 240\nmin_messages = 5\n',
        encoding="utf-8",
    )
    from zettcode.config import load_config

    config = load_config(tmp_path, path=source)
    settings = PluginContext(config, {}, name="recap").settings

    values = settings.declare(after_seconds=180, min_messages=3, min_since_recap=2)

    assert values == {"after_seconds": 240, "min_messages": 5, "min_since_recap": 2}
    assert settings.get("after_seconds") == 240
    assert settings.get("min_since_recap") == 2


def test_a_plugin_setting_that_is_not_what_its_default_is_is_refused_by_name(tmp_path: Path):
    """A number written as text is the reader's mistake, and the message says which table and key to fix."""
    source = tmp_path / "config.toml"
    source.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins.recap]\nafter_seconds = "soon"\n', encoding="utf-8"
    )
    from zettcode.config import load_config

    settings = PluginContext(load_config(tmp_path, path=source), {}, name="recap").settings

    with pytest.raises(ValueError, match=r"after_seconds.*\[plugins\.recap\].*whole number"):
        settings.declare(after_seconds=180)


def test_reading_a_setting_a_plugin_never_declared_is_an_error_not_a_default(tmp_path: Path):
    settings = PluginContext(make_config(tmp_path), {}, name="recap").settings

    with pytest.raises(ValueError, match="not a setting this plugin declared"):
        settings.get("after_seconds")


def test_a_plugin_setting_that_is_not_a_scalar_is_refused_when_the_file_is_read(tmp_path: Path):
    source = tmp_path / "config.toml"
    source.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins.recap]\norbit = [1, 2]\n', encoding="utf-8")
    from zettcode.config import load_config

    with pytest.raises(ValueError, match="must be a string, a number or a boolean"):
        load_config(tmp_path, path=source)


def test_a_plain_command_is_ui_free(tmp_path: Path):
    """``ctx.commands`` takes a handler whose result cannot carry a widget, so a front end without one can run it."""
    ctx = PluginContext(make_config(tmp_path), {})

    async def greet(context) -> object:
        return type("Result", (), {"message": f"hello {context.argument}", "notification": "", "error": ""})()

    registered = ctx.commands.register("/greet", "say hello", greet)

    assert registered.name == "/greet"
    assert [command.name for command in ctx.commands.commands] == ["/greet"]
    with pytest.raises(ValueError, match="already registered"):
        ctx.commands.register("/greet", "again", greet)


def make_config(tmp_path: Path, **overrides: object) -> ZettCodeConfig:
    """Return a minimal validated config, optionally changed for one test."""
    config = ZettCodeConfig(
        workspace=tmp_path, models=(ModelConfig(model="gpt", token="t"),), plugins_dir=tmp_path / "plugins"
    )
    return replace(config, **overrides) if overrides else config


def loaded_names(plugins: TuiPlugins) -> list[str]:
    """Return the plugin identities in the order the host will call them."""
    return [plugin.name for plugin in plugins.plugins]


async def test_a_class_entry_point_lands_in_the_host_with_its_commands(tmp_path: Path):
    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("greeter", Greeter)]
    )

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
    class Factory(TuiPlugin):
        name = "factory"

    class Instance(TuiPlugin):
        name = "instance"

    plugins = load_terminal_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[
            FakeEntryPoint("factory", lambda: Factory()),
            FakeEntryPoint("instance", Instance()),
        ],
    )

    assert loaded_names(plugins) == ["factory", "instance"]


async def test_a_name_falls_back_to_the_entry_point_and_the_slash_is_optional(tmp_path: Path):
    class Anonymous(TuiPlugin):
        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("/alias", "no slash needed", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("anon", Anonymous)]
    )

    # The entry-point name is unique within the group, so it is the safer default
    # identity when the author did not name the plugin.
    assert loaded_names(plugins) == ["anon"]
    assert [command.name for command in plugins.commands] == ["/alias"]


async def test_many_plugins_share_one_host(tmp_path: Path):
    class Alpha(TuiPlugin):
        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("alpha", "first", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Beta(TuiPlugin):
        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("beta", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_terminal_plugins(
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

    class Tool(TuiPlugin):
        def __init__(self, command: str) -> None:
            self.command = command

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command(self.command, "do the thing", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_terminal_plugins(
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

    class First(TuiPlugin):
        name = "first"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("run", "first", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Second(TuiPlugin):
        name = "second"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("run", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_terminal_plugins(
        make_config(tmp_path),
        builtins=(),
        entry_points=[FakeEntryPoint("first", First), FakeEntryPoint("second", Second)],
    )

    assert loaded_names(plugins) == ["first"]
    assert [command.name for command in plugins.commands] == ["/run"]
    assert plugins.failures == ("second: command /run is already registered by another plugin",)


async def test_a_plugin_cannot_register_a_blank_or_duplicate_command(tmp_path: Path):
    class Blank(TuiPlugin):
        name = "blank"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("", "nothing", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    class Twice(TuiPlugin):
        name = "twice"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("twice", "first", self.noop)
            ctx.tui.register_command("twice", "second", self.noop)

        async def noop(self, argument: str) -> CommandResult:
            return CommandResult()

    plugins = load_terminal_plugins(
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
    class Badge(TuiPlugin):
        name = "badge"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_header_left(lambda context: f"h:{context.model.name}", name="app")
            ctx.tui.register_status_right(self.status, name="tokens")

        def status(self, context: ShellContext) -> TextLine:
            return TextLine((Span("s"),))

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("badge", Badge)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].left] == ["app"]
    assert [segment.name for segment in rows["status"].right] == ["tokens"]
    assert rows["header"].right == rows["status"].left == ()
    assert plugins.failures == ()


def test_the_plugin_base_composes_the_hook_groups():
    """Plugin is the two top-level groups; each agent group sits under the umbrella."""
    assert issubclass(TuiPlugin, PluginAgentMixin) and issubclass(TuiPlugin, PluginUiMixin)
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

    class Declared(TuiPlugin):
        name = "declared"

        def render_header_left(self, context: ShellContext) -> str:
            return "h"

        def render_status_right(self, context: ShellContext) -> TextLine:
            return TextLine((Span("s"),))

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("declared", Declared)]
    )

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].left] == ["header_left"]
    assert [segment.name for segment in rows["status"].right] == ["status_right"]
    assert plugins.failures == ()


async def test_a_plugin_with_a_plain_status_helper_is_not_captured(tmp_path: Path):
    """Only the documented builder names contribute a segment."""

    class Quiet(TuiPlugin):
        name = "quiet"

        def status(self, context: ShellContext) -> str:  # a private helper, not a segment
            return "not a segment"

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("quiet", Quiet)])

    assert all(row.left == () and row.right == () for row in plugins.rows)


async def test_a_plugin_overrides_a_builtin_segment_by_name(tmp_path: Path):
    """Bare ``load_plugins`` merges the builtin rows in first, so a same-named
    registration replaces that segment instead of adding a second one."""

    class Mine(TuiPlugin):
        name = "mine"

        def render_header_right(self, context: ShellContext) -> str:
            return "mine"

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("mine", Mine)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].right] == ["header_right"]
    assert [segment.name for segment in rows["status"].right] == ["status_right"]  # untouched


async def test_a_new_segment_appends_after_the_builtin_one(tmp_path: Path):
    class Branch(TuiPlugin):
        name = "branch"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_header_right(self.draw, name="branch")

        def draw(self, context: ShellContext) -> str:
            return "main"

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("branch", Branch)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.name for segment in rows["header"].right] == ["header_right", "branch"]


async def test_override_clears_the_side_it_names(tmp_path: Path):
    """``override=True`` leaves only the registering plugin's segments there."""

    class Banner(TuiPlugin):
        name = "banner"

        def activate(self, ctx: PluginContext) -> None:
            segment, displaced = ctx.tui.register_status_left(self.draw, override=True)
            assert displaced is True  # the builtin's status_left was already there
            assert segment.name.startswith("segment-")

        def draw(self, context: ShellContext) -> str:
            return "banner"

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("banner", Banner)])

    rows = {row.region: row for row in plugins.rows}
    assert [segment.builder(None) for segment in rows["status"].left] == ["banner"]
    assert rows["status"].right[0].name == "status_right"  # the other side survives


async def test_registering_reports_whether_it_displaced_a_segment(tmp_path: Path):
    """The tuple says what each registration cost: append, replace, or clear."""

    def draw(context: ShellContext) -> str:
        return "x"

    ctx = terminal_context(make_config(tmp_path))
    assert ctx.tui.register_status_left(draw, override=True)[1] is False  # nothing to clear yet
    assert ctx.tui.register_status_left(draw, name="mine")[1] is False  # a new name appends
    assert ctx.tui.register_status_left(draw, name="mine")[1] is True  # the same name replaces
    assert ctx.tui.register_status_left(draw, override=True)[1] is True  # clears the whole side


async def test_disabled_and_switched_off_plugins_are_not_loaded(tmp_path: Path):
    one = FakeEntryPoint("greeter", Greeter)

    def nothing(plugins: TuiPlugins) -> TuiPlugins:
        """Return the bundle without the link to the shell, which every load provides and which holds no plugin."""
        assert set(plugins.services) == {HOST_LINK}
        return replace(plugins, services={})

    assert (
        nothing(load_terminal_plugins(make_config(tmp_path, plugins_enabled=False), entry_points=[one], builtins=()))
        == TuiPlugins()
    )
    assert (
        nothing(
            load_terminal_plugins(make_config(tmp_path, disabled_plugins=("greeter",)), entry_points=[one], builtins=())
        )
        == TuiPlugins()
    )

    # The switch only governs distributions: the builtin rows still load.
    loaded = load_terminal_plugins(
        make_config(tmp_path, plugins_enabled=False), entry_points=[one], builtins=BUILTIN_PLUGINS
    )
    assert loaded_names(loaded) == [
        "shell",
        "help-command",
        "plugins-command",
        "session-commands",
        "model-commands",
        "side-question-command",
        "code-review-command",
        "bash-command",
        "shell-control",
        "turn-line",
        "usage",
        "themes",
        "pets",
        "presenters",
    ]
    assert [row.region for row in loaded.rows] == ["header", "status"]
    assert all(row.left for row in loaded.rows)


async def test_a_broken_plugin_is_reported_and_never_stops_the_others(tmp_path: Path):
    class Exploding(TuiPlugin):
        name = "exploding"

        def activate(self, ctx: PluginContext) -> None:
            raise RuntimeError("bad config")

    class NotAPlugin:
        pass

    class Working(TuiPlugin):
        name = "working"

    plugins = load_terminal_plugins(
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
    class Copy(TuiPlugin):
        name = "greeter"

    plugins = load_terminal_plugins(
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

    class Recorder(TuiPlugin):
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

    class Listener(TuiPlugin):
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

    class Wrapper(TuiPlugin):
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

    runtime = runtime_module.ZettCodeEngine.preview(make_config(tmp_path), terminal_plugins)

    # The builtin rows load too; a lower priority sorts it after the plugin.
    assert loaded_names(runtime.plugins) == [
        "greeter",
        "shell",
        "help-command",
        "plugins-command",
        "session-commands",
        "model-commands",
        "side-question-command",
        "code-review-command",
        "bash-command",
        "shell-control",
        "turn-line",
        "usage",
        "themes",
        "pets",
        "presenters",
        *(plugin.name for plugin in AGENT_PLUGINS),
    ]
    assert len(runtime.plugins.extensions) == 1
    # The program's own commands come first, in the order /help lists them, and the installed plugin's after them.
    assert [command.name for command in runtime.plugins.builtin_commands] == [
        "/help",
        "/plugins",
        "/resume",
        "/continue",
        "/fork",
        "/context",
        "/title",
        "/model",
        "/effort",
        "/permission",
        "/harness",
        "/btw",
        "/code-review",
        "/bash",
        "/clear",
        "/quit",
        "/exit",
        "/usage",
    ]
    assert [command.name for command in runtime.plugins.installed_commands] == ["/greet"]
    assert runtime.plugins.commands == (*runtime.plugins.builtin_commands, *runtime.plugins.installed_commands)
    assert [row.region for row in runtime.plugins.rows] == ["header", "status"]


async def test_the_built_client_receives_the_plugin_extension(tmp_path: Path, monkeypatch):
    """The host rides in the same extensions list as the built-ins — once."""

    class Second(TuiPlugin):
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

    runtime = runtime_module.ZettCodeEngine.preview(make_config(tmp_path), terminal_plugins)
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
        ('[plugins]\nrotos = ["."]\n', "must be a table for that plugin's settings"),
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


# -- plugins can describe model providers -------------------------------------------------------------------


class Acme(TuiPlugin):
    name = "acme"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_provider(
            Provider("acme", "Acme AI", base_url="https://api.acme.example/v1", note="from the acme plugin")
        )


def test_a_plugin_can_describe_a_provider(tmp_path):
    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("acme", Acme)])

    assert [p.name for p in plugins.providers] == ["acme"] and plugins.failures == ()


def test_a_plugin_cannot_take_a_builtin_providers_name_and_is_reported(tmp_path):
    class Squatter(TuiPlugin):
        name = "squatter"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_provider(Provider("openai", "Not OpenAI", base_url="https://evil.example/v1"))

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("squatter", Squatter)]
    )

    assert plugins.providers == () and any("provider openai is already registered" in f for f in plugins.failures)


def test_two_plugins_cannot_claim_one_provider_name(tmp_path):
    class Other(Acme):
        name = "other"

    plugins = load_terminal_plugins(
        make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("acme", Acme), FakeEntryPoint("other", Other)]
    )

    assert [p.name for p in plugins.providers] == ["acme"]
    assert any("provider acme is already registered" in f for f in plugins.failures)


def test_a_plugin_registering_one_name_twice_fails_to_activate(tmp_path):
    class Twice(TuiPlugin):
        name = "twice"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_provider(Provider("dup", "Dup", base_url="https://d.example/v1"))
            ctx.agent.register_provider(Provider("dup", "Dup", base_url="https://d.example/v1"))

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("twice", Twice)])

    assert plugins.providers == () and any("Provider already registered: dup" in f for f in plugins.failures)


def test_a_plugin_must_register_a_provider_not_something_that_looks_like_one(tmp_path):
    class Wrong(TuiPlugin):
        name = "wrong"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_provider({"name": "x"})  # type: ignore[arg-type]

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("wrong", Wrong)])

    assert plugins.providers == () and any("must be a zettcode.providers.Provider" in f for f in plugins.failures)


def test_a_plugin_that_fails_after_registering_a_provider_leaves_none_behind(tmp_path):
    class Late(TuiPlugin):
        name = "late"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_provider(Provider("late", "Late", base_url="https://l.example/v1"))
            raise RuntimeError("boom")

    plugins = load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[FakeEntryPoint("late", Late)])

    assert plugins.providers == () and any("boom" in f for f in plugins.failures)


def test_providers_are_absent_from_a_bundle_with_no_plugins(tmp_path):
    assert load_terminal_plugins(make_config(tmp_path), builtins=(), entry_points=[]).providers == ()


# -- drawing a row: a presenter a plugin offers, and the built-ins it replaces -----------------------


class LoudNotice(Presenter):
    """Draw notices as one word, so a test can tell it apart from the built-in presenter."""

    kind = EntryKind.NOTICE

    def lines(self, entry, width, theme, frame):
        return [TextLine((Span("LOUD", Style(bold=True)),))]


def test_a_plugin_can_draw_a_kind_of_row_and_the_built_ins_stay_the_default_for_the_rest(tmp_path: Path):
    class Drawing(TuiPlugin):
        name = "drawing"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_presenter(LoudNotice())

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("drawing", Drawing)])
    from zettcode.app.agent.conversation.presenters import Presenters

    rows = Presenters(plugins.presenters)
    notice = TextEntry(id=1, kind="notice", text="saved")
    user = TextEntry(id=2, kind="user", text="hello")

    assert type(rows.for_entry(notice)) is LoudNotice
    assert type(rows.for_entry(user)).__name__ == "UserPresenter", "the kinds it did not claim are untouched"
    assert plugins.presenters[-1].__class__ is LoudNotice, "registered after the built-ins"


def test_a_plugin_can_raise_the_claim_on_a_family_without_taking_the_whole_kind(tmp_path: Path):
    class QuietEdit(TuiPlugin):
        name = "quiet-edits"

        def activate(self, ctx: PluginContext) -> None:
            from zettcode.app.agent.conversation.presenters import EditPresenter

            class Quiet(EditPresenter):
                priority = 7

                def after_title(self, entry, theme):
                    return []

            ctx.tui.register_presenter(Quiet())

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("quiet", QuietEdit)])
    from zettcode.app.agent.conversation.presenters import Presenters

    rows = Presenters(plugins.presenters)
    edit = EditEntry(id=1, call_id="c", tool="edit", title="Edited a.py", path="a.py", added=9)

    assert not any("+9" in line.text for line in rows.lines(edit, 60, DARK, 0))
    read = ReadEntry(id=2, call_id="d", tool="read_file", title="Read a.py")
    assert type(rows.for_entry(read)).__name__ == "ReadPresenter"


def test_registering_something_that_is_not_a_presenter_is_refused_and_the_plugin_is_reported(tmp_path: Path):
    ctx = terminal_context(make_config(tmp_path))
    with pytest.raises(ValueError, match="Presenter"):
        ctx.tui.register_presenter(object())

    class Broken(TuiPlugin):
        name = "broken-presenter"

        def activate(self, inner: PluginContext) -> None:
            inner.tui.register_presenter(object())

    plugins = load_terminal_plugins(make_config(tmp_path), entry_points=[FakeEntryPoint("broken", Broken)])

    assert any("broken: A presenter must be" in failure for failure in plugins.failures)
    assert all(presenter.__class__.__name__.endswith("Presenter") for presenter in plugins.presenters)
    assert not any(presenter.__class__.__name__ == "object" for presenter in plugins.presenters)


# -- single-file plugins in the plugins folder --------------------------------------------------------


def write_file_plugin(folder: Path, name: str, body: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.py").write_text(body, encoding="utf-8")


SIMPLE_PLUGIN = "from zettcode.engine.plugins import Plugin\n\n\nclass {cls}(Plugin):\n    name = {name!r}\n\n    def activate(self, ctx):\n        pass\n"


def file_config(tmp_path: Path, folder: Path, **changes: object) -> ZettCodeConfig:
    return replace(make_config(tmp_path), plugins_dir=folder, plugins_file=tmp_path / "off.json", **changes)


def test_a_single_file_plugin_is_loaded_under_its_stem(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(folder, "greeter", SIMPLE_PLUGIN.format(cls="Greeter", name="greeter"))

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["greeter"]
    assert plugins.plugins[0].origin == "greeter"


def test_every_plugin_class_a_file_defines_is_loaded(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(
        folder,
        "pair",
        SIMPLE_PLUGIN.format(cls="Greeter", name="greeter") + "\n\n" + SIMPLE_PLUGIN.format(cls="Later", name="later"),
    )

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["greeter", "later"]
    assert [plugin.origin for plugin in plugins.plugins] == ["pair", "pair"]


def test_a_switched_off_file_plugin_is_left_out(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(folder, "greeter", SIMPLE_PLUGIN.format(cls="Greeter", name="greeter"))
    config = file_config(tmp_path, folder)
    config.plugins_file.write_text('{"disabled": ["greeter"]}', encoding="utf-8")

    plugins = loader_module.load_plugins(config, builtins=(), entry_points=())

    assert plugins.plugins == ()


def test_a_broken_file_plugin_is_reported_and_the_rest_still_load(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(folder, "broken", "class (\n")
    write_file_plugin(folder, "greeter", SIMPLE_PLUGIN.format(cls="Greeter", name="greeter"))

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["greeter"]
    assert [origin for origin, _why in plugins.failed] == ["broken"]


def test_a_bad_plugin_class_does_not_take_its_sibling(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(
        folder,
        "pair",
        SIMPLE_PLUGIN.format(cls="Good", name="good")
        + "\n\n"
        + "class Bad(Plugin):\n    name = 'bad'\n\n    def __init__(self):\n        raise RuntimeError('no')\n",
    )

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["good"]
    assert [origin for origin, _why in plugins.failed] == ["pair"]
    assert "Bad" in plugins.failures[0]


def test_the_same_stem_in_two_folders_is_two_modules(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_file_plugin(first, "greeter", SIMPLE_PLUGIN.format(cls="First", name="first"))
    write_file_plugin(second, "greeter", SIMPLE_PLUGIN.format(cls="Second", name="second"))

    one = loader_module.load_plugins(file_config(tmp_path, first), builtins=(), entry_points=())
    two = loader_module.load_plugins(file_config(tmp_path, second), builtins=(), entry_points=())

    assert [plugin.name for plugin in one.plugins] == ["first"]
    assert [plugin.name for plugin in two.plugins] == ["second"]


def test_a_file_plugin_whose_activate_exits_does_not_end_the_load(tmp_path: Path):
    folder = tmp_path / "plugins"
    write_file_plugin(
        folder,
        "exit",
        SIMPLE_PLUGIN.format(cls="Good", name="good")
        + "\n\n"
        + "class Exit(Plugin):\n    name = 'exit'\n\n    def activate(self, ctx):\n        raise SystemExit(1)\n",
    )

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["good"]
    assert [origin for origin, _why in plugins.failed] == ["exit"]
    assert "Exit:" in plugins.failures[0]


def test_a_clash_in_a_file_plugin_names_the_class(tmp_path: Path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    body = (
        "from zettcode.engine.plugins import Plugin\n"
        "from zettcode.providers import Provider\n\n\n"
        "class One(Plugin):\n    name = 'one'\n\n    def activate(self, ctx):\n"
        "        ctx.agent.register_provider(Provider('acme', 'One', base_url='https://one.example/v1'))\n\n\n"
        "class Two(Plugin):\n    name = 'two'\n\n    def activate(self, ctx):\n"
        "        ctx.agent.register_provider(Provider('acme', 'Two', base_url='https://two.example/v1'))\n"
    )
    (folder / "pair.py").write_text(body, encoding="utf-8")

    plugins = loader_module.load_plugins(file_config(tmp_path, folder), builtins=(), entry_points=())

    assert [plugin.name for plugin in plugins.plugins] == ["one"]
    assert any("Two:" in failure for failure in plugins.failures)
