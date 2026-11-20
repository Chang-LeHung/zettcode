"""The plain ``/harness`` the server and the editor run: the switch, gen as a preset, and reset as words."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult, TurnCommandResult
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.services import HARNESS
from zettcode.jit_harness.brief import CACHE_MISS, GEN_BRIEF, LOCKED
from zettcode.jit_harness.plain import register_plain


def _context(tmp_path: Path, *, on: bool = False) -> tuple[HarnessSwitch, PluginContext]:
    switch = HarnessSwitch(on=on)
    context = PluginContext(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)),
        {HARNESS: switch},
        name="harness",
    )
    return switch, context


def test_the_plain_command_has_the_terminal_name_and_words(tmp_path: Path):
    _, context = _context(tmp_path)

    register_plain(context)

    (command,) = context.commands.commands
    assert command.name == "/harness"
    assert command.when_busy == "refuse"
    assert [getattr(word, "name", word) for word in command.subcommands] == ["gen", "reset", "use", "save", "fork"]


def test_no_word_reports_the_switch_without_a_panel(tmp_path: Path):
    _, context = _context(tmp_path, on=True)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext())

    assert isinstance(result, TextCommandResult)
    assert "**on**" in result.message and "/harness gen" in result.message


def test_gen_turns_the_switch_on_and_returns_the_turn(tmp_path: Path):
    switch, context = _context(tmp_path)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext(argument="gen a tool for TODOs"))

    assert isinstance(result, TurnCommandResult)
    assert switch.on is True
    assert result.prompt.startswith(GEN_BRIEF)
    assert "a tool for TODOs" in result.prompt
    assert result.shown == "/harness gen a tool for TODOs"


def test_reset_turns_it_off_and_deletes_nothing(tmp_path: Path):
    switch, context = _context(tmp_path, on=True)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext(argument="reset"))

    assert isinstance(result, TextCommandResult)
    assert switch.on is False
    assert "Nothing was deleted" in result.message
    assert CACHE_MISS in result.message, "the editor says what the terminal says: the tools left the request"
    assert result.notification == "", "the message is the answer; the chat does not also show a toast"


def test_reset_of_a_harness_that_was_off_does_not_claim_a_cache_miss(tmp_path: Path):
    _, context = _context(tmp_path, on=False)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext(argument="reset"))

    assert isinstance(result, TextCommandResult) and CACHE_MISS not in result.message


def test_a_held_session_refuses_gen_without_moving_the_switch(tmp_path: Path):
    switch, context = _context(tmp_path)
    register_plain(context)
    (command,) = context.commands.commands
    host = SimpleNamespace(locked=True)

    result = command.handler(PlainCommandContext(argument="gen", host=host))  # type: ignore[arg-type]

    assert isinstance(result, TextCommandResult)
    assert result.message == LOCKED
    assert switch.on is False


def test_another_word_lists_the_ones_it_takes(tmp_path: Path):
    _, context = _context(tmp_path)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext(argument="on"))

    assert isinstance(result, TextCommandResult)
    assert "not a word" in result.message
    assert "/harness gen" in result.message and "/harness reset" in result.message


def test_reset_takes_nothing_after_it(tmp_path: Path):
    switch, context = _context(tmp_path, on=True)
    register_plain(context)
    (command,) = context.commands.commands

    result = command.handler(PlainCommandContext(argument="reset now"))

    assert isinstance(result, TextCommandResult)
    assert "takes nothing after it" in result.message
    assert "not a word" not in result.message, "reset is a word; only what follows it is wrong"
    assert switch.on is True, "a usage error changes nothing"


def test_importing_the_plain_command_does_not_import_the_widgets():
    """The split exists so the server never loads the terminal; prove it in a process of its own."""
    script = (
        "import sys\n"
        "import zettcode.jit_harness.plain\n"
        "loaded = sorted(name for name in sys.modules if name == 'zettcode.tui' or name.startswith('zettcode.tui.'))\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def _library_context(tmp_path: Path):
    from zettcode.jit_harness.selection import HARNESS_CHOICES, HarnessChoices

    switch = HarnessSwitch(on=True)
    choices = HarnessChoices()
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        harness_dir=tmp_path / "harness",
    )
    context = PluginContext(config, {HARNESS: switch, HARNESS_CHOICES: choices}, name="harness")
    register_plain(context)
    (command,) = context.commands.commands
    entry = config.harness_dir / "library" / "todos" / "todos"
    entry.mkdir(parents=True)
    (entry / "__init__.py").write_text("", encoding="utf-8")
    (entry / "MANIFEST").write_text(
        'name = "todos"\nversion = "1"\ndescription = "d"\ntools = ["t"]\n', encoding="utf-8"
    )
    return command, choices, config


def test_the_editor_can_share_a_library_harness_and_copy_one(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "config.toml"))
    command, choices, config = _library_context(tmp_path)

    shared = command.handler(PlainCommandContext(argument="use todos"))
    assert isinstance(shared, TextCommandResult) and "`todos`" in shared.message and CACHE_MISS in shared.message
    assert choices.default is not None and choices.default.directory == config.harness_dir / "library" / "todos"

    copied = command.handler(PlainCommandContext(argument="fork todos mine"))
    assert "Copied `todos` as `mine`" in copied.message
    assert (config.harness_dir / "library" / "mine" / "todos" / "MANIFEST").is_file()

    assert "Nothing was changed" in command.handler(PlainCommandContext(argument="use nope")).message


def test_save_in_the_editor_needs_a_session_to_name(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "config.toml"))
    command, _, _ = _library_context(tmp_path)

    result = command.handler(PlainCommandContext(argument="save x"))

    assert "needs a session" in result.message
