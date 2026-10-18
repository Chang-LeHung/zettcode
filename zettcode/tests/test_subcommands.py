"""A command can list the words it takes first, and the menu offers them after the command and a space."""

from __future__ import annotations

import asyncio

from test_zettcode_app import FakeConfig, _harness, build_app, rows_and_commands
from zettcode.app.commands import Command, CommandContext, CommandResult, Subcommand
from zettcode.app.ui import ZettCodeApp
from zettcode.app.ui.widgets.completer import CommandCompleter
from zettcode.plugins import PluginContainer


async def nothing(context: CommandContext) -> CommandResult:
    return CommandResult()


def completer() -> CommandCompleter:
    return CommandCompleter(
        (
            Command(
                "/deploy", "ship it", "plugin", nothing, subcommands=("staging", Subcommand("prod", "the real one"))
            ),
            Command("/plain", "takes anything", "plugin", nothing),
            Command("/dynamic", "asked each time", "plugin", nothing, subcommands=lambda: [Subcommand("now")]),
        )
    )


def values(candidates: object) -> list[str]:
    return [item.value for item in candidates]  # type: ignore[attr-defined]


def test_the_words_after_a_command_and_a_space_are_offered():
    found = completer()("/deploy ", len("/deploy "))

    assert values(found) == ["staging", "prod"]
    assert [item.description for item in found] == ["", "the real one"]


def test_what_has_been_typed_of_the_word_filters_them():
    assert values(completer()("/deploy pr", len("/deploy pr"))) == ["prod"]
    assert values(completer()("/deploy x", len("/deploy x"))) == []


def test_a_command_with_no_subcommands_offers_nothing_after_it():
    assert values(completer()("/plain ", len("/plain "))) == []
    assert values(completer()("/nosuch ", len("/nosuch "))) == []


def test_only_the_word_right_after_the_command_is_filtered():
    assert values(completer()("/deploy prod ", len("/deploy prod "))) == []
    assert values(completer()("/deploy prod st", len("/deploy prod st"))) == []
    # Not a command at all: the first word is ordinary text.
    assert values(completer()("deploy ", len("deploy "))) == []


def test_a_function_is_asked_each_time():
    calls: list[int] = []
    command = Command("/n", "", "plugin", nothing, subcommands=lambda: calls.append(1) or ["a", "b"])
    menu = CommandCompleter((command,))

    assert values(menu("/n ", 3)) == ["a", "b"]
    assert values(menu("/n ", 3)) == ["a", "b"]
    assert len(calls) == 2


def test_the_commands_are_still_offered_by_their_first_word():
    assert values(completer()("/d", 2)) == ["/deploy", "/dynamic"]


def test_a_plugin_registers_the_words_with_its_command():
    container = PluginContainer(FakeConfig())

    command = container.register_command("deploy", "ship it", nothing, subcommands=["staging", "prod"])

    assert [option.name for option in command.options()] == ["staging", "prod"]
    assert container.commands[0] is command


async def test_the_shell_offers_config_words_and_tab_takes_one():
    app = build_app()
    harness = _harness(app)

    harness.write("/config ")

    assert values(app.completions.items) == ["add", "remove", "list", "providers"]
    assert "show the models in the file" in harness.text()

    harness.write("re")
    assert values(app.completions.items) == ["remove"]

    harness.press("tab")

    assert app.composer.text == "/config remove "
    assert app.completions.visible is False


async def test_enter_on_a_word_that_says_everything_switches_at_once_without_a_picker():
    app = build_app()
    harness = _harness(app)
    assert app.agent.active_model.model == "gpt-5-mini"

    harness.write("/model ")
    harness.press("down")
    assert app.completions.current.value == "GPT-4o"
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.active_model.model == "gpt-4o"
    assert app.app.screens.top.name == "main"
    assert app.composer.text == ""


async def test_enter_straight_after_the_space_takes_the_highlighted_word_not_the_picker():
    app = build_app()
    harness = _harness(app)
    other = "light" if app.app.theme.name == "dark" else "dark"

    harness.write("/theme ")
    harness.press("down" if app.completions.current.value != other else "up")
    assert app.completions.current.value == other
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.app.theme.name == other
    assert app.app.screens.top.name == "main"


async def test_enter_on_part_of_a_word_that_says_everything_picks_it_and_runs():
    app = build_app()
    harness = _harness(app)

    harness.write("/theme li")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.app.theme.name == "light"
    assert app.composer.text == ""


def deploy_app() -> tuple[ZettCodeApp, list[str]]:
    """A shell with one plugin command whose first word is either complete (staging) or only a start (add)."""
    heard: list[str] = []

    async def deploy(context: CommandContext) -> CommandResult:
        heard.append(context.argument)
        return CommandResult()

    command = Command(
        "/deploy",
        "ship it",
        "plugin",
        deploy,
        subcommands=[Subcommand("add", needs_more=True), Subcommand("staging"), Subcommand("status")],
    )
    return build_app(plugins=rows_and_commands(commands=(command,))), heard


async def test_enter_straight_after_the_space_on_a_word_that_needs_more_runs_the_command_bare():
    app, heard = deploy_app()
    harness = _harness(app)

    harness.write("/deploy ")
    assert app.completions.current.value == "add"
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert heard == [""]
    assert app.composer.text == ""


async def test_enter_on_part_of_a_word_that_needs_more_only_completes_it():
    app, heard = deploy_app()
    harness = _harness(app)

    harness.write("/deploy ad")
    harness.press("enter")

    assert app.composer.text == "/deploy add "
    assert app.completions.visible is False
    assert heard == []


async def test_enter_on_part_of_a_complete_word_runs_it_with_the_word():
    app, heard = deploy_app()
    harness = _harness(app)

    harness.write("/deploy stag")
    assert app.completions.current.final is True
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert heard == ["staging"]
    assert app.composer.text == ""


async def test_the_levels_the_menu_lists_are_the_words_of_permission_and_effort_has_none():
    app = build_app()
    harness = _harness(app)

    harness.write("/permission ")
    assert values(app.completions.items) == list(app.agent.permissions)
    assert app.completions.items[0].description

    app.composer.clear()
    harness.write("/effort ")

    assert values(app.completions.items) == [], "effort has a panel with arrow keys instead"


async def test_the_models_are_offered_by_the_name_model_accepts():
    app = build_app()
    harness = _harness(app)

    harness.write("/model ")

    assert values(app.completions.items) == ["gpt-5-mini", "GPT-4o"]
    assert [item.description for item in app.completions.items] == ["gpt-5-mini", "gpt-4o"]
    assert all(app.agent.find_model(name) is not None for name in values(app.completions.items))
