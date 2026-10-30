"""The `/plugins` page: a switch per plugin, written where that plugin's switch belongs, honoured at the next start."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from zettcode.app.plugins import TuiPlugin
from zettcode.app.plugins.builtin_commands import PluginCommand
from zettcode.app.plugins.loader import load_terminal_plugins
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import AGENT_PLUGINS
from zettcode.engine.plugins.plugin import PluginSetting


def _config(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        plugins_file=tmp_path / "plugins.json",
        mcp_enabled=False,
        skills_enabled=False,
    )
    for key, value in changes.items():
        object.__setattr__(config, key, value)
    return config


def test_the_switch_file_is_read_as_the_disabled_list(tmp_path: Path):
    from zettcode.config import read_disabled_plugins

    path = tmp_path / "plugins.json"
    path.write_text(json.dumps({"disabled": ["greeter", "  ", 7]}), encoding="utf-8")

    assert read_disabled_plugins(path) == ("greeter",)
    assert read_disabled_plugins(tmp_path / "missing.json") == ()


class Doubled(TuiPlugin):
    """A plugin that claims one name twice: a plain command and a terminal one."""

    name = "doubled"

    def activate(self, ctx) -> None:
        from zettcode.app.commands import CommandResult
        from zettcode.engine.plugins.commands import TextCommandResult

        async def plain(context):
            return TextCommandResult(message="plain")

        async def tui_command(context):
            return CommandResult(message="tui")

        ctx.commands.register("/dup", "plain", plain)
        assert ctx.tui is not None
        ctx.tui.register_command("dup", "tui", tui_command)


class Greeter(TuiPlugin):
    """An installed plugin, which is the kind a switch can turn off."""

    name = "greeter"

    def activate(self, ctx) -> None:
        pass


def test_a_hand_built_config_reads_its_own_switch_file(tmp_path: Path):
    """Every `Client(models=…)` builds a config this way: the file beside it is what the loader must read."""
    config = _config(tmp_path)
    point = EntryPoint(name="greeter", value=f"{__name__}:Greeter", group="zettcode.plugins")
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter"]}), encoding="utf-8")

    bundle = load_terminal_plugins(config, builtins=(), entry_points=(point,))

    assert [plugin.name for plugin in bundle.plugins] == [], "the file the config names, not the default one"


def test_a_plugin_cannot_claim_one_name_in_both_groups(tmp_path: Path):
    """Its own plain command and its own terminal command share one namespace, like every other plugin's."""
    point = EntryPoint(name="doubled", value=f"{__name__}:Doubled", group="zettcode.plugins")
    bundle = load_terminal_plugins(_config(tmp_path), builtins=(), entry_points=(point,))

    assert bundle.failures and "/dup" in bundle.failures[0], bundle.failures


def test_the_switch_file_and_the_configuration_file_stay_apart(tmp_path: Path, monkeypatch):
    """The configuration holds its own list; the switch file's names are merged where a switch needs them merged.

    They were merged into `disabled_plugins` once, which made a name the page wrote look like the reader's own line —
    and the page then refused to switch it back on.
    """
    from zettcode.config import load_config
    from zettcode.engine.plugins.switches import held_by_config, off_names

    config_file = tmp_path / "config.toml"
    config_file.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n[plugins]\ndisable = ["mine"]\n', encoding="utf-8")
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter", "acme", "mine"]}), encoding="utf-8")
    monkeypatch.setattr("zettcode.config.DEFAULT_PLUGINS_FILE", tmp_path / "plugins.json")

    config = load_config(tmp_path, path=config_file)
    object.__setattr__(config, "plugins_file", tmp_path / "plugins.json")

    assert config.disabled_plugins == ("mine",), "the configuration file's own line, not the merged list"
    assert held_by_config(config) == frozenset({"mine"})
    assert off_names(config) == ("acme", "greeter", "mine"), "what the next start leaves out, both lists"


class _Bundle:
    """The parts of a loaded bundle `/plugins` reads.

    ``builtins`` maps the origin of each plugin compiled into the program to the configuration key that decides it,
    ``None`` for one that has none.
    """

    def __init__(
        self,
        names: list[str],
        *,
        builtins: dict[str, object] | None = None,
        failed: tuple[tuple[str, str], ...] = (),
        origins: dict[str, str] | None = None,
    ) -> None:
        compiled = dict(builtins or {})
        renamed = dict(origins or {})

        class _Plugin:
            def __init__(self, name: str) -> None:
                self.name = name
                self.origin = renamed.get(name, name)
                self.setting = compiled.get(name)

        self.plugins = [_Plugin(name) for name in names]
        self.builtins = tuple(compiled)
        self.failed = failed
        self.failures = tuple(f"{origin}: {why}" for origin, why in failed)


class _Transcript:
    """The conversation, as far as a command writes into it."""

    def __init__(self) -> None:
        self.notices: list[str] = []
        self.errors: list[str] = []

    def notice(self, text: str) -> None:
        self.notices.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)


@dataclass
class _RuntimeConfig:
    """The fields of the configuration a builtin plugin's switch writes, as this process reads them."""

    mcp_enabled: bool = True
    skills_enabled: bool = True


class _Host:
    """The shell, as far as a command that reads the bundle and opens a page needs it."""

    class _Agent:
        class _Runtime:
            def __init__(self, plugins: _Bundle, config: object) -> None:
                self.plugins = plugins
                self.config = config

        def __init__(self, plugins: _Bundle, config: object) -> None:
            self.runtime = self._Runtime(plugins, config)

    def __init__(self, plugins: _Bundle, config: object) -> None:
        self.agent = self._Agent(plugins, config)
        self.transcript = _Transcript()
        self.closed = 0

    def close_page(self) -> None:
        self.closed += 1


def _command_context(plugins: _Bundle, argument: str, config: object | None = None):
    from zettcode.app.commands import CommandContext

    return CommandContext(argument=argument, ui=object(), host=_Host(plugins, config or _RuntimeConfig()))  # type: ignore[arg-type]


def _page_of(result):
    """Return the page a `/plugins` result presents."""
    from zettcode.app.ui.widgets import PluginsPage

    assert result.widget is not None, "the command opens a page"
    assert isinstance(result.widget, PluginsPage), type(result.widget)
    return result.widget


async def test_the_page_lists_only_what_a_reader_can_switch(tmp_path: Path):
    config = _config(tmp_path, mcp_enabled=True)
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["acme"]}), encoding="utf-8")
    bundle = _Bundle(
        ["shell", "mcp", "greeter"],
        builtins={"shell": None, "mcp": PluginSetting("mcp_enabled", "mcp")},
        failed=(("broken", "no such module"),),
    )

    page = _page_of(await PluginCommand().plugins(_command_context(bundle, "", config)))

    assert [(row.name, row.builtin, row.enabled, row.setting) for row in page.rows] == [
        ("mcp", True, True, "mcp.enabled"),
        ("greeter", False, True, ""),
        ("broken", False, True, ""),
    ]
    assert "shell" not in [row.name for row in page.rows], "a plugin with nothing to press is not listed"
    assert page.rows[-1].failure == "no such module"


async def test_the_page_writes_every_change_and_says_what_the_next_start_does(tmp_path: Path):
    config = _config(tmp_path)
    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", False)
    page.on_apply(page.changes)

    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}
    assert context.host.closed == 1, "the page closes itself on Enter"
    assert "greeter will be off" in context.host.transcript.notices[0]
    assert "next start" in context.host.transcript.notices[0]


async def test_a_plugin_the_program_carries_is_written_to_the_configuration_file(tmp_path: Path, monkeypatch):
    from zettcode.paths import config_path

    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    assert config_path() == path, "the file the setting is written to is the one the settings are read from"

    config = _config(tmp_path, mcp_enabled=True)
    context = _command_context(_Bundle(["mcp"], builtins={"mcp": PluginSetting("mcp_enabled", "mcp")}), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("mcp", False)
    page.on_apply(page.changes)

    assert "[mcp]\nenabled = false" in path.read_text(encoding="utf-8")
    assert context.host.transcript.notices == [
        "mcp will be off from the next start; this session keeps the plugins it loaded."
    ]
    assert context.host.agent.runtime.config.mcp_enabled is False, "this process shows what it decided"


async def test_a_setting_cannot_be_written_without_a_configuration_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    config = _config(tmp_path, mcp_enabled=True)
    context = _command_context(_Bundle(["mcp"], builtins={"mcp": PluginSetting("mcp_enabled", "mcp")}), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("mcp", False)
    page.on_apply(page.changes)

    assert context.host.transcript.errors and "there is none" in context.host.transcript.errors[0]
    assert "already written" not in context.host.transcript.errors[0], "no switch file was written either"
    assert context.host.closed == 0, "the page stays open: nothing was applied"
    assert not (tmp_path / "plugins.json").exists()


async def test_enter_with_nothing_changed_writes_nothing(tmp_path: Path):
    config = _config(tmp_path)
    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.on_apply(page.changes)

    assert page.changes == {}
    assert not (tmp_path / "plugins.json").exists()
    assert context.host.transcript.notices == []


async def test_a_plugin_the_page_switched_off_can_be_switched_on_again_after_a_restart(tmp_path: Path, monkeypatch):
    """The page writes the switch file, which the next start reads — and which stays the switch file's own list.

    A page that took the switch file's names for the configuration file's own would offer no switch for the very name
    it wrote, and `set_enabled` would refuse with the wrong reason. This goes through `load_config`, as a restart does.
    """
    from zettcode.config import load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setattr("zettcode.config.DEFAULT_PLUGINS_FILE", tmp_path / "plugins.json")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config_file))
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter"]}), encoding="utf-8")

    config = load_config(tmp_path, path=config_file)
    object.__setattr__(config, "plugins_file", tmp_path / "plugins.json")
    assert config.disabled_plugins == (), "the name is the switch file's, not the configuration file's"

    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))
    assert page.rows[0].switchable, "the name came from the switch file, which this page may write"

    page.set("greeter", True)
    page.on_apply(page.changes)

    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": []}
    assert context.host.transcript.notices[0].startswith("greeter will be on")


async def test_installed_plugins_switched_off_as_a_group_have_no_switch(tmp_path: Path):
    config = _config(tmp_path, plugins_enabled=False)
    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", True)

    assert page.rows[0].enabled is False, "the next start loads none of them"
    assert page.rows[0].switchable is False
    assert "enabled = false" in (page.note or ""), "the row says why it cannot be switched"


async def test_a_plugin_the_configuration_file_switched_off_has_no_switch(tmp_path: Path):
    config = _config(tmp_path, disabled_plugins=("greeter",))
    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", True)
    page.on_apply(page.changes)

    assert "configuration file" in (page.note or "")
    assert page.changes == {}, "the switch is not the page's to move"
    assert not (tmp_path / "plugins.json").exists()


async def test_a_compiled_in_plugin_that_failed_is_listed_for_its_reason_with_no_switch(tmp_path: Path):
    config = _config(tmp_path, skills_enabled=True)
    context = _command_context(
        _Bundle(
            ["skills"],
            builtins={"skills": PluginSetting("skills_enabled", "skills"), "coding": None},
            failed=(("coding", "no plugin provides the model"),),
        ),
        "",
        config,
    )
    page = _page_of(await PluginCommand().plugins(context))

    assert [(row.name, row.builtin, bool(row.setting), bool(row.failure)) for row in page.rows] == [
        ("skills", True, True, False),
        ("coding", True, False, True),
    ]
    assert page.shown == {"skills": True}, "a plugin nobody could read a setting from has nothing to press"

    page.set("coding", False)

    assert "could not load" in (page.note or "")


async def test_a_page_opened_again_shows_what_the_last_one_wrote(tmp_path: Path, monkeypatch):
    """The switch is a new configuration object, so a page that read the one from activation would be lying."""
    path = tmp_path / "config.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    config = _config(tmp_path, mcp_enabled=True)
    context = _command_context(_Bundle(["mcp"], builtins={"mcp": PluginSetting("mcp_enabled", "mcp")}), "", config)

    page = _page_of(await PluginCommand().plugins(context))
    assert page.shown == {"mcp": True}
    page.set("mcp", False)
    page.on_apply(page.changes)

    again = _page_of(await PluginCommand().plugins(context))

    assert again.shown == {"mcp": False}, "the second page reads the configuration this session now holds"


async def test_disabling_writes_owner_only_and_only_for_a_real_name(tmp_path: Path, monkeypatch):
    import os
    import stat

    config = _config(tmp_path)
    command = PluginCommand()
    installed = EntryPoint(name="greeter", value=f"{__name__}:Greeter", group="zettcode.plugins")
    bundle = _Bundle(["greeter"])
    context = _command_context(bundle, "disable greeter", config)

    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: (installed,))
    result = await command.plugins(context)

    assert "off" in result.notification
    path = tmp_path / "plugins.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled": ["greeter"]}
    if sys.platform != "win32":
        # A POSIX permission; Windows has no equivalent, and chmod there changes only the read-only flag.
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    with pytest.raises(ValueError, match="No plugin is called"):
        await command.plugins(_command_context(bundle, "disable typo", config))


async def test_a_builtin_with_no_setting_cannot_be_switched_off(tmp_path: Path):
    config = _config(tmp_path)
    command = PluginCommand()

    with pytest.raises(ValueError, match="compiled into the program"):
        await command.plugins(_command_context(_Bundle(["shell"], builtins={"shell": None}), "disable shell", config))


async def test_a_name_in_both_lists_stays_the_configurations_own(tmp_path: Path, monkeypatch):
    """A set difference would call it the switch file's; the configuration goes on overriding it, so it has none."""
    from zettcode.config import load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n[plugins]\ndisable = ["greeter"]\n', encoding="utf-8")
    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["greeter"]}), encoding="utf-8")
    monkeypatch.setattr("zettcode.config.DEFAULT_PLUGINS_FILE", tmp_path / "plugins.json")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config_file))
    config = load_config(tmp_path, path=config_file)
    object.__setattr__(config, "plugins_file", tmp_path / "plugins.json")

    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))
    page.set("greeter", True)
    page.on_apply(page.changes)

    assert page.rows[0].switchable is False
    assert page.note and "configuration file" in page.note
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}


async def test_a_plugin_the_configuration_turned_off_as_a_group_cannot_be_written(tmp_path: Path):
    config = _config(tmp_path, plugins_enabled=False)
    context = _command_context(_Bundle(["greeter"]), "disable greeter", config)

    with pytest.raises(ValueError, match="plugins\\] enabled = false"):
        await PluginCommand().plugins(context)

    assert not (tmp_path / "plugins.json").exists()


async def test_a_plugin_is_written_with_its_origin_not_the_name_it_calls_itself(tmp_path: Path):
    config = _config(tmp_path)
    context = _command_context(_Bundle(["greeter"], origins={"greeter": "zettcode-greeter"}), "disable greeter", config)

    result = await PluginCommand().plugins(context)

    assert "off" in result.notification
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["zettcode-greeter"]}


async def test_a_switch_file_that_cannot_be_written_says_so_and_leaves_the_configuration_alone(
    tmp_path: Path, monkeypatch
):
    from zettcode.paths import config_path

    path = tmp_path / "config.toml"
    original = '[[models]]\nmodel = "m"\ntoken = "t"\n'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    blocked = tmp_path / "blocked.json"
    blocked.mkdir()
    config = _config(tmp_path, plugins_file=blocked, skills_enabled=True)
    context = _command_context(
        _Bundle(["skills", "greeter"], builtins={"skills": PluginSetting("skills_enabled", "skills")}), "", config
    )
    page = _page_of(await PluginCommand().plugins(context))

    page.set("skills", False)
    page.set("greeter", False)
    page.on_apply(page.changes)

    assert config_path() == path
    assert path.read_text(encoding="utf-8") == original, "the configuration file is not touched"
    assert context.host.transcript.errors and "could not be written" in context.host.transcript.errors[0]
    assert context.host.closed == 0, "the page stays open when nothing was applied"


@pytest.mark.parametrize(
    "plugin", [plugin for plugin in AGENT_PLUGINS if plugin.setting is not None], ids=lambda p: p.name
)
def test_every_declared_setting_names_a_key_the_configuration_reads(plugin, tmp_path: Path, monkeypatch):
    """A table or key typo would write a line the configuration never reads, and the switch would do nothing.

    The write goes through the writer the switch itself uses (`set_boolean`), so the table it appends and the key it
    replaces are both exercised, and `load_config` is then asked what the file means.
    """
    from zettcode.config import load_config
    from zettcode.config_edit import set_boolean, write_text_atomically

    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("zettcode.config.DEFAULT_PLUGINS_FILE", tmp_path / "plugins.json")
    setting = plugin.setting
    assert setting is not None
    text = '[[models]]\nmodel = "m"\ntoken = "t"\n'
    for enabled in (True, False):
        # The first pass appends the table; the second replaces the key the first one wrote.
        text = set_boolean(text, setting.table, setting.key, enabled, where=config_file, command="/plugins")
        write_text_atomically(config_file, text)
        config = load_config(tmp_path, path=config_file)
        assert getattr(config, setting.field) is enabled, f"{setting.path} does not decide {setting.field}"


async def test_a_plugin_named_like_another_distribution_does_not_take_its_switch(tmp_path: Path, monkeypatch):
    """A plugin's own name is not an origin: switching `greeter` must write `greeter`, not the plugin's origin.

    The plugin here calls itself `greeter` and comes from `other`, so a map that let the name win would write `other`
    and leave the distribution the reader meant switched on.
    """
    config = _config(tmp_path)
    installed = (EntryPoint(name="greeter", value=f"{__name__}:Greeter", group="zettcode.plugins"),)
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: installed)
    context = _command_context(_Bundle(["greeter"], origins={"greeter": "other"}), "disable greeter", config)

    result = await PluginCommand().plugins(context)

    assert "greeter will be off" in result.notification
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}


async def test_a_plugin_named_like_a_compiled_in_one_does_not_take_its_name(tmp_path: Path, monkeypatch):
    """The same rule for the names the program carries: `shell` stays the builtin, not the plugin that borrowed it."""
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    config = _config(tmp_path)
    bundle = _Bundle(["shell"], origins={"shell": "other"}, builtins={"shell": None})

    written, _keys, problems = switches.set_many(config, {"shell": False}, bundle=bundle, entry_points=())

    assert written == {}, "the builtin cannot be switched, whatever a plugin calls itself"
    assert problems and "compiled into the program" in problems[0]
    assert not (tmp_path / "plugins.json").exists()


async def test_a_failed_switch_file_keeps_the_refusals_of_the_same_batch(tmp_path: Path):
    config = _config(tmp_path)
    blocked = tmp_path / "blocked.json"
    blocked.mkdir()
    object.__setattr__(config, "plugins_file", blocked)
    context = _command_context(_Bundle(["greeter"], failed=(("broken", "no such module"),)), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", False)
    page.on_apply({"greeter": False, "typo": False})

    messages = context.host.transcript.errors
    assert any("No plugin is called 'typo'" in text for text in messages), "the invalid name is still reported"
    assert any("could not be written" in text for text in messages)
    assert context.host.transcript.notices == []


async def test_a_configuration_that_fails_after_the_switch_file_says_which_half_landed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    config = _config(tmp_path, skills_enabled=True)
    context = _command_context(
        _Bundle(["skills", "greeter"], builtins={"skills": PluginSetting("skills_enabled", "skills")}), "", config
    )
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", False)
    page.set("skills", False)
    page.on_apply(page.changes)

    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}
    message = context.host.transcript.errors[0]
    assert "there is none" in message and "already written to the switch file: greeter off" in message
    assert context.host.closed == 0, "the page stays open so the reader sees it"


async def test_a_lock_held_by_another_session_is_reported_with_what_else_was_refused(tmp_path: Path, monkeypatch):
    from zettcode import filelock

    monkeypatch.setattr(filelock.SingletonLock, "acquire", lambda self, wait: False)
    config = _config(tmp_path)
    context = _command_context(_Bundle(["greeter"]), "", config)
    page = _page_of(await PluginCommand().plugins(context))

    page.set("greeter", False)
    page.on_apply({"greeter": False, "typo": False})

    assert any("No plugin is called 'typo'" in text for text in context.host.transcript.errors)
    assert any("another session is changing the plugin switches" in text for text in context.host.transcript.errors)
    assert not (tmp_path / "plugins.json").exists()


def test_the_return_of_a_failed_configuration_write_says_what_landed(tmp_path: Path, monkeypatch):
    """The page reports on `problems`, so what `set_many` says it wrote has to be exact even when it fails."""
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    config = _config(tmp_path, skills_enabled=True)
    bundle = _Bundle(["skills", "greeter"], builtins={"skills": PluginSetting("skills_enabled", "skills")})

    written, keys, problems = switches.set_many(
        config, {"greeter": False, "skills": False}, bundle=bundle, entry_points=()
    )

    assert written == {"greeter": False}, "only the name the switch file took, not the configuration key"
    assert keys == [], "nothing for a caller to apply in memory"
    assert len(problems) == 1 and "already written" in problems[0]
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}


def test_a_keys_only_write_that_fails_claims_no_switch_file(tmp_path: Path, monkeypatch):
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    config = _config(tmp_path, skills_enabled=True)
    bundle = _Bundle(["skills"], builtins={"skills": PluginSetting("skills_enabled", "skills")})

    written, keys, problems = switches.set_many(config, {"skills": False}, bundle=bundle, entry_points=())

    assert (written, keys) == ({}, [])
    assert problems and "already written" not in problems[0]


def test_a_plugin_named_like_a_switched_off_distribution_does_not_take_its_name(tmp_path: Path, monkeypatch):
    """The third origin loop: the switch file's and the configuration file's names are origins too."""
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    config = _config(tmp_path, disabled_plugins=("held",))
    bundle = _Bundle(["held"], origins={"held": "other"})

    written, _keys, problems = switches.set_many(config, {"held": True}, bundle=bundle, entry_points=())

    assert written == {}
    assert problems and "remove it from [plugins] disable" in problems[0], "the configuration file's line, not a write"
    assert not (tmp_path / "plugins.json").exists()


def test_a_switch_file_that_fails_returns_nothing_written(tmp_path: Path):
    from zettcode.engine.plugins import switches

    blocked = tmp_path / "blocked.json"
    blocked.mkdir()
    config = _config(tmp_path, plugins_file=blocked)
    bundle = _Bundle(["greeter"])

    written, keys, problems = switches.set_many(
        config, {"greeter": False, "typo": False}, bundle=bundle, entry_points=()
    )

    assert (written, keys) == ({}, []), "the page reports on problems, so this must not claim the name"
    assert len(problems) == 2, problems
    assert "No plugin is called 'typo'" in problems[0]
    assert "could not be written" in problems[1]


def test_a_lock_held_elsewhere_returns_nothing_written(tmp_path: Path, monkeypatch):
    from zettcode import filelock
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(filelock.SingletonLock, "acquire", lambda self, wait: False)
    config = _config(tmp_path)
    bundle = _Bundle(["greeter"])

    written, keys, problems = switches.set_many(config, {"greeter": False}, bundle=bundle, entry_points=())

    assert (written, keys) == ({}, [])
    assert problems and "another session is changing the plugin switches" in problems[0]


def test_a_plugin_named_like_a_name_the_switch_file_holds_does_not_take_it(tmp_path: Path):
    """The other half of the third loop: the names `plugins.json` holds are origins, and a plugin may not take one."""
    from zettcode.engine.plugins import switches

    (tmp_path / "plugins.json").write_text(json.dumps({"disabled": ["held"]}), encoding="utf-8")
    config = _config(tmp_path)
    bundle = _Bundle(["held"], origins={"held": "other"})

    written, _keys, problems = switches.set_many(config, {"held": True}, bundle=bundle, entry_points=())

    assert written == {"held": True}, "the file's own name, not the plugin's origin"
    assert problems == []
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": []}


def test_an_invalid_name_and_a_failed_configuration_are_both_reported(tmp_path: Path, monkeypatch):
    from zettcode.engine.plugins import switches

    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    config = _config(tmp_path, skills_enabled=True)
    bundle = _Bundle(["skills"], builtins={"skills": PluginSetting("skills_enabled", "skills")})

    written, keys, problems = switches.set_many(
        config, {"skills": False, "typo": False}, bundle=bundle, entry_points=()
    )

    assert (written, keys) == ({}, [])
    assert len(problems) == 2, problems
    assert "No plugin is called 'typo'" in problems[0]
    assert "there is none" in problems[1]


def test_a_configuration_edit_refused_after_another_key_leaves_the_file_untouched(tmp_path: Path, monkeypatch):
    """Both keys are edited in memory and written once, so a file that refuses one takes neither."""
    from zettcode.engine.plugins import switches

    path = tmp_path / "config.toml"
    original = 'mcp = { enabled = true }\nskills = { enabled = true }\n\n[[models]]\nmodel = "m"\ntoken = "t"\n'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    monkeypatch.setattr(switches.loader, "installed_entry_points", lambda: ())
    config = _config(tmp_path, mcp_enabled=True, skills_enabled=True)
    bundle = _Bundle(
        ["mcp", "skills"],
        builtins={
            "mcp": PluginSetting("mcp_enabled", "mcp"),
            "skills": PluginSetting("skills_enabled", "skills"),
        },
    )

    written, keys, problems = switches.set_many(config, {"mcp": False, "skills": False}, bundle=bundle, entry_points=())

    assert (written, keys) == ({}, []), "the first key was edited in memory only"
    assert problems and "cannot edit safely" in problems[0]
    assert path.read_text(encoding="utf-8") == original


def test_two_plugins_where_one_name_is_the_others_origin(tmp_path: Path):
    """Two loaded plugins may collide: one's self-name may equal the other's origin, and the origin must win.

    The loader's identity is the plugin name, not the origin, so this is allowed. The switch the page drew belongs to
    the distribution, so a click must be written under the origin — whichever order the two plugins loaded in.
    """
    from zettcode.engine.plugins import switches

    config = _config(tmp_path)
    # `keeper` comes from `greeter`; the plugin that calls itself `greeter` comes from `other`.
    bundle = _Bundle(["keeper", "greeter"], origins={"keeper": "greeter", "greeter": "other"})

    written, _keys, problems = switches.set_many(config, {"greeter": False}, bundle=bundle, entry_points=())

    assert problems == []
    assert written == {"greeter": False}, "the name `greeter` is a distribution's origin here"
    assert json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8")) == {"disabled": ["greeter"]}
