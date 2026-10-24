"""``/config``: the models in the file, from inside the shell, against a real config file."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from plugin_helpers import runtime_inputs
from zettcode._compat import tomllib
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.ui import ZettCodeApp
from zettcode.app.ui.widgets import FormPage, InputPage, ModelSettingsPage
from zettcode.app.ui.widgets.input_page import MASK
from zettcode.config import load_config
from zettcode.config_edit import ConfigEditError
from zettcode.engine import core as runtime_module
from zettcode.engine.core import ZettCodeEngine
from zettcode.plugins import AGENT_PLUGINS, Plugin, PluginContainer, load_plugins
from zettcode.providers import BUILTIN_PROVIDERS, Api, Provider
from zettcode.tui import ListPage, walk
from zettcode.tui.testing import Harness

BASE = """\
# my config
[[models]]
model = "gpt-5-mini"
token = "sk-one"

# second
[[models]]
model = "gpt-4o"
display_model = "GPT-4o"
token = "sk-two"
base_url = "https://proxy.example.com/v1"

[skills]
enabled = false
"""


class Fixture:
    """A real shell over a real config file in a temporary directory."""

    def __init__(self, app: ZettCodeApp, path: Path, harness: Harness) -> None:
        self.app, self.path, self.harness = app, path, harness

    @property
    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def models(self) -> list[dict]:
        return tomllib.loads(self.text)["models"]

    @property
    def configured(self) -> tuple[str, ...]:
        return tuple(model.model for model in self.app.agent.models)

    def screen(self) -> str:
        return self.harness.render().text

    def page(self, kind: type):
        return next((w for w in walk(self.app.app.screens.top.widget) if isinstance(w, kind)), None)

    async def command(self, line: str) -> None:
        self.harness.write(line)
        self.harness.press("enter")
        await asyncio.wait_for(self.app.task, 3.0)

    def errors(self) -> list[str]:
        return [entry.text for entry in self.app.transcript.entries if getattr(entry, "level", None) == "error"]

    def notices(self) -> list[str]:
        return [entry.text for entry in self.app.transcript.entries if getattr(entry, "level", None) == "info"]

    def choose(self, label: str) -> None:
        """Pick the row of the list on screen whose label starts with ``label``."""
        page = self.page(ListPage)
        assert page is not None, self.screen()
        items = page.list.items
        index = next(i for i, item in enumerate(items) if item.label.lstrip(" 0123456789.").startswith(label))
        page.list.select(index, notify=False)
        self.harness.press("enter")

    def type(self, text: str) -> None:
        self.harness.write(text)
        self.harness.press("enter")

    # -- the panel of one model: names on the left, values on the right ---------------------------------

    @property
    def panel(self) -> ModelSettingsPage:
        page = self.page(ModelSettingsPage)
        assert page is not None, self.screen()
        return page

    def go(self, key: str) -> None:
        """Move the cursor to a row of the panel the way a reader does, with Down."""
        for _ in range(len(self.panel.children) + 1):
            if self.panel.focus_key() == key:
                return
            self.harness.press("down")
        raise AssertionError(f"the cursor never reached {key!r}\n{self.screen()}")

    def edit(self, key: str, text: str) -> None:
        """Replace what a typed row holds."""
        self.go(key)
        self.panel.editor(key).set_text("")
        self.harness.write(text)

    def pick(self, key: str, word: str) -> None:
        """Put a choice on a word: to the first with Home, then right."""
        self.go(key)
        self.harness.press("home")
        for _ in range(next(s.words.index(word) for s in self.panel.settings if s.key == key)):
            self.harness.press("right")

    def act(self, key: str) -> None:
        """Do one of the actions at the foot of the panel."""
        self.go(key)
        self.harness.press("enter")


@pytest.fixture
def shell(tmp_path, monkeypatch):
    def build(text: str = BASE, **overrides: object) -> Fixture:
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
        monkeypatch.setattr(runtime_module.os, "chdir", lambda _path: None)
        workspace = tmp_path / "work"
        workspace.mkdir(exist_ok=True)
        config = replace(
            load_config(workspace, path=path),
            store=tmp_path / "sessions",
            plugins_enabled=False,
            skills_enabled=False,
            mcp_enabled=False,
            **overrides,
        )
        app = ZettCodeApp(ZettCodeAgent(ZettCodeEngine.preview(config)))
        app.app.resize(110, 30)
        app.app.mount()
        return Fixture(app, path, Harness(app=app.app))

    return build


# -- /config list and /config providers ---------------------------------------------------------------


async def test_list_shows_every_model_with_the_current_one_marked_and_never_a_token(shell):
    fx = shell()

    await fx.command("/config list")

    shown = "\n".join(entry.text for entry in fx.app.transcript.entries)
    assert "gpt-5-mini (current)" in shown and "GPT-4o" in shown and "https://proxy.example.com/v1" in shown
    assert "sk-one" not in shown and "sk-two" not in shown


async def test_providers_lists_the_builtins_and_custom(shell):
    fx = shell()

    await fx.command("/config providers")

    shown = "\n".join(entry.text for entry in fx.app.transcript.entries)
    for provider in BUILTIN_PROVIDERS:
        assert f"`{provider.name}`" in shown
    assert "`custom`" in shown


async def test_an_unknown_subcommand_says_how_to_use_the_command(shell):
    fx = shell()

    await fx.command("/config frobnicate")

    assert any("Usage: /config" in error for error in fx.errors())


# -- /config add on one line ---------------------------------------------------------------------------


async def test_add_with_everything_on_the_line_writes_the_model_and_changes_nothing_else(shell):
    fx = shell()

    await fx.command("/config add deepseek --model deepseek-chat --token sk-new")

    assert fx.models[-1] == {"model": "deepseek-chat", "token": "sk-new", "base_url": "https://api.deepseek.com"}
    assert fx.text.startswith("# my config\n"), "the banner is where it was"
    assert "# second" in fx.text and "[skills]\nenabled = false" in fx.text
    assert fx.errors() == []


async def test_add_makes_the_model_available_at_once_without_a_restart_and_without_switching(shell):
    fx = shell()
    before = fx.app.agent.active_model

    await fx.command("/config add deepseek --model deepseek-chat --token sk-new")

    assert fx.configured == ("gpt-5-mini", "gpt-4o", "deepseek-chat")
    assert fx.app.agent.active_model == before, "adding is not choosing"
    fx.app.change_model("deepseek-chat")
    assert fx.app.agent.active_model.model == "deepseek-chat"
    assert fx.app.agent.active_model.base_url == "https://api.deepseek.com"


async def test_add_for_each_protocol_writes_the_flag_that_selects_it(shell):
    fx = shell()

    await fx.command("/config add anthropic --model claude-x --token k1")
    await fx.command("/config add custom --api responses --url https://r.example/v1 --model r1 --token k2")
    await fx.command(
        "/config add custom --api chat --url https://c.example/v1 --model c1 --token k3 --name Chatty --multimodal"
    )

    by_model = {m["model"]: m for m in fx.models}
    assert by_model["claude-x"]["anthropic"] is True and "responses_api" not in by_model["claude-x"]
    assert by_model["r1"]["responses_api"] is True and "anthropic" not in by_model["r1"]
    assert "anthropic" not in by_model["c1"] and "responses_api" not in by_model["c1"]
    assert by_model["c1"]["display_model"] == "Chatty" and by_model["c1"]["multimodal"] is True
    assert {m.model: m.api for m in fx.app.agent.models} == {
        "gpt-5-mini": "chat", "gpt-4o": "chat", "claude-x": "anthropic", "r1": "responses", "c1": "chat",
    }  # fmt: skip


async def test_add_can_turn_web_search_on_and_refuses_it_on_deepseeks_chat_endpoint(shell):
    fx = shell()

    await fx.command("/config add anthropic --model claude-x --token k1 --web-search")
    by_model = {m["model"]: m for m in fx.models}
    assert by_model["claude-x"]["web_search"] is True and "web_search_name" not in by_model["claude-x"]
    assert fx.errors() == []

    before = fx.text
    await fx.command("/config add deepseek --model deepseek-chat --token sk-new --web-search")

    assert any("DeepSeek serves web search only on its Anthropic-compatible endpoint" in e for e in fx.errors())
    assert fx.text == before, "nothing was written for a model that cannot search"


async def test_add_refuses_a_bad_address_and_writes_nothing(shell):
    fx = shell()
    before = fx.text

    await fx.command("/config add custom --api chat --url not-a-url --model m --token t")

    assert any("http or https" in error for error in fx.errors())
    assert fx.text == before and fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_add_refuses_an_unknown_provider_and_names_the_known_ones(shell):
    fx = shell()
    before = fx.text

    await fx.command("/config add nonesuch --model m --token t")

    assert any("Unknown provider 'nonesuch'" in e and "deepseek" in e for e in fx.errors())
    assert fx.text == before


async def test_a_failed_add_does_not_leave_the_shell_stuck_busy(shell):
    fx = shell()

    await fx.command("/config add nonesuch")

    assert fx.app._busy is False


async def test_a_token_typed_on_the_line_is_not_echoed_into_the_conversation_or_the_listing(shell):
    fx = shell()

    await fx.command("/config add deepseek --model deepseek-chat --token sk-SECRET-123")
    await fx.command("/config list")

    shown = "\n".join(getattr(entry, "text", "") for entry in fx.app.transcript.entries)
    assert "sk-SECRET-123" not in shown and "sk-SECRET-123" not in fx.screen()


# -- /config add: the form ----------------------------------------------------------------------------


def form_of(fx):
    page = fx.page(FormPage)
    assert page is not None, fx.screen()
    return page


async def test_add_with_a_provider_shows_one_form_and_only_the_model_id_is_required(shell):
    fx = shell()

    await fx.command("/config add deepseek")
    page = form_of(fx)

    assert [field.key for field in page.fields] == ["model", "token", "url", "name", "temperature"]
    assert [field.key for field in page.fields if field.required] == ["model"]
    assert page.focus_key() == "model", "the cursor starts in the first line"
    assert fx.page(InputPage) is None


async def test_tab_moves_between_the_lines_and_enter_saves_them_all_at_once(shell):
    fx = shell()
    await fx.command("/config add deepseek")

    fx.harness.write("deepseek-chat")
    fx.harness.press("tab")
    assert form_of(fx).focus_key() == "token"
    fx.harness.write("sk-typed")
    fx.harness.press("enter")

    assert fx.page(FormPage) is None, "the panel closed when it was saved"
    assert fx.models[-1] == {"model": "deepseek-chat", "token": "sk-typed", "base_url": "https://api.deepseek.com"}
    assert fx.configured[-1] == "deepseek-chat"


async def test_the_token_may_be_left_empty_and_then_none_is_written(shell, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fx = shell()
    await fx.command("/config add custom --api chat --url http://localhost:11434/v1")

    fx.harness.write("llama3")
    fx.harness.press("enter")

    assert fx.models[-1] == {"model": "llama3", "base_url": "http://localhost:11434/v1", "chat": True}
    assert fx.configured[-1] == "llama3" and fx.errors() == []


async def test_the_model_id_may_not_be_empty_and_the_cursor_goes_to_it(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    fx.harness.press("tab")
    fx.harness.write("sk-kept")

    fx.harness.press("enter")
    page = form_of(fx)

    assert page.refusal == "model id is required" and "model id is required" in fx.screen()
    assert page.focus_key() == "model", "back to the line that is wrong"
    assert page.values["token"] == "sk-kept", "and nothing that was typed is lost"
    assert fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_the_refusal_goes_once_the_reader_starts_correcting(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    fx.harness.press("enter")
    assert form_of(fx).refusal

    fx.harness.write("d")

    assert form_of(fx).refusal == ""


async def test_shift_tab_and_the_arrow_keys_move_too_and_go_round_at_either_end(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    keys = [field.key for field in form_of(fx).fields]

    fx.harness.press("backtab")
    assert form_of(fx).focus_key() == keys[-1], "back from the first goes to the last"
    fx.harness.press("tab")
    assert form_of(fx).focus_key() == keys[0], "and forward from the last goes to the first"
    fx.harness.press("down")
    assert form_of(fx).focus_key() == keys[1]
    fx.harness.press("up")
    assert form_of(fx).focus_key() == keys[0]


async def test_the_token_line_hides_what_is_typed(shell):
    fx = shell()
    await fx.command("/config add deepseek --model deepseek-chat")
    fx.harness.press("tab")
    assert form_of(fx).focus_key() == "token"

    fx.harness.write("sk-hidden-token")
    screen = fx.screen()

    assert "sk-hidden-token" not in screen
    assert MASK * len("sk-hidden-token") in screen


async def test_the_token_is_masked_but_what_is_saved_is_what_was_typed(shell):
    fx = shell()
    await fx.command("/config add deepseek --model deepseek-chat")
    fx.harness.press("tab")
    fx.harness.write("sk-exact")
    fx.harness.press("enter")

    assert fx.models[-1]["token"] == "sk-exact"


async def test_a_pasted_newline_does_not_end_up_inside_a_line(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    fx.harness.press("tab")
    fx.harness.paste("sk-pasted\n")
    fx.harness.press("shift_enter")

    assert form_of(fx).areas["token"].text == "sk-pasted"


async def test_a_custom_endpoint_asks_which_api_and_then_shows_one_form(shell):
    fx = shell()

    await fx.command("/config add custom")
    assert fx.page(ListPage) is not None and "Which API" in fx.screen()
    fx.choose("anthropic")
    page = form_of(fx)
    assert "url" not in [field.key for field in page.fields], "an Anthropic endpoint has an address of its own"
    fx.harness.write("claude-x")
    fx.harness.press("tab")
    fx.harness.write("sk-a")
    fx.harness.press("enter")

    assert fx.models[-1] == {"model": "claude-x", "token": "sk-a", "anthropic": True}


async def test_a_custom_chat_endpoint_needs_its_address_and_says_chat_in_the_file(shell):
    fx = shell()
    await fx.command("/config add custom")

    fx.choose("chat")
    page = form_of(fx)
    assert [field.key for field in page.fields if field.required] == ["model", "url"]
    fx.harness.write("my-model")
    fx.harness.press("tab")
    fx.harness.write("sk-a")
    fx.harness.press("tab")
    fx.harness.write("https://llm.example/v1")
    fx.harness.press("enter")

    assert fx.models[-1] == {"model": "my-model", "token": "sk-a", "base_url": "https://llm.example/v1", "chat": True}


async def test_a_custom_endpoint_without_an_address_is_refused_at_that_line(shell):
    fx = shell()
    await fx.command("/config add custom --api chat")
    fx.harness.write("my-model")

    fx.harness.press("enter")

    assert form_of(fx).refusal == "address is required" and form_of(fx).focus_key() == "url"


async def test_a_bad_address_is_refused_in_place_and_can_be_corrected(shell):
    fx = shell()
    await fx.command("/config add custom --api chat")
    fx.harness.write("my-model")
    fx.harness.press("tab")
    fx.harness.press("tab")
    fx.harness.write("llm.example")
    fx.harness.press("enter")
    page = form_of(fx)

    assert "http or https" in page.refusal and "http or https" in fx.screen(), "the reason is on screen"
    assert page.focus_key() == "url" and page.areas["url"].text == "llm.example", "the slip is what is left to fix"
    assert page.areas["model"].text == "my-model"
    for _ in range(len("llm.example")):
        fx.harness.press("backspace")
    assert form_of(fx).refusal == "", "and the reason goes once it is being corrected"
    fx.harness.write("https://llm.example/v1")
    fx.harness.press("enter")
    assert fx.page(FormPage) is None and fx.models[-1]["base_url"] == "https://llm.example/v1"


async def test_a_temperature_is_checked_for_the_api_and_written_when_given(shell):
    fx = shell()
    await fx.command("/config add anthropic --model claude-x")
    for _ in range(3):
        fx.harness.press("tab")
    assert form_of(fx).focus_key() == "temperature"

    fx.harness.write("1.5")
    fx.harness.press("enter")
    assert "0 to 1" in form_of(fx).refusal and fx.configured == ("gpt-5-mini", "gpt-4o")
    for _ in range(3):
        fx.harness.press("backspace")
    fx.harness.write("0.3")
    fx.harness.press("enter")

    assert fx.models[-1]["temperature"] == 0.3
    assert fx.app.agent.models[-1].temperature == 0.3


async def test_the_hint_under_the_form_follows_the_cursor(shell):
    fx = shell()
    await fx.command("/config add deepseek")

    assert "exactly as its documentation writes it" in fx.screen()
    fx.harness.press("tab")
    assert "Leave it empty for a local server" in fx.screen()
    assert "exactly as its documentation writes it" not in fx.screen()


async def test_every_line_is_a_box_with_its_label_on_the_border(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    page = form_of(fx)
    screen = fx.screen()

    for field in page.fields:
        assert f"\u2500 {page.label_of(field)} " in screen, f"{field.key}: the label is on the top border"
    assert screen.count("\u256d") == screen.count("\u2570") == len(page.fields), "one box a line"
    assert page.boxed and all(box.rect.height == 3 for box in page.children if hasattr(box, "area"))


async def test_the_box_the_cursor_is_in_is_bright_and_the_others_are_not(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    theme = fx.app.app.theme

    def border_of(key: str):
        box = next(b for b in form_of(fx).children if getattr(b, "field", None) and b.field.key == key)
        canvas = fx.app.app.render()
        return canvas.cells[box.rect.y][box.rect.x].style.foreground

    assert border_of("model") == theme.accent_bright and border_of("token") == theme.muted
    fx.harness.press("tab")
    assert border_of("model") == theme.muted and border_of("token") == theme.accent_bright


async def test_a_press_on_a_box_puts_the_cursor_in_it_the_border_included(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    fx.screen()  # a frame, so the page has been laid out
    box = next(b for b in form_of(fx).children if getattr(b, "field", None) and b.field.key == "url")

    fx.harness.mouse_down(box.rect.x, box.rect.y + 1)  # the left border
    fx.harness.mouse_up(box.rect.x, box.rect.y + 1)
    assert form_of(fx).focus_key() == "url"

    fx.harness.mouse_down(box.rect.x + 6, box.rect.y)  # the top border, on the label
    fx.harness.mouse_up(box.rect.x + 6, box.rect.y)
    assert form_of(fx).focus_key() == "url"
    other = next(b for b in form_of(fx).children if getattr(b, "field", None) and b.field.key == "token")
    fx.harness.mouse_down(other.rect.x + 4, other.rect.y + 1)  # the editor itself
    fx.harness.mouse_up(other.rect.x + 4, other.rect.y + 1)
    assert form_of(fx).focus_key() == "token"


async def test_a_terminal_too_short_for_boxes_gets_one_row_a_line_and_everything_still_works(shell):
    fx = shell()
    fx.app.app.resize(110, 14)
    await fx.command("/config add deepseek")
    screen = fx.screen()
    page = form_of(fx)

    assert not page.boxed and "\u256d" not in screen, "no room for boxes"
    for field in page.fields:
        assert page.label_of(field) in screen
    fx.harness.write("deepseek-chat")
    fx.harness.press("tab")
    fx.harness.write("sk-short")
    fx.harness.press("enter")

    assert fx.models[-1] == {"model": "deepseek-chat", "token": "sk-short", "base_url": "https://api.deepseek.com"}


async def test_the_boxes_come_back_when_the_terminal_grows_again(shell):
    fx = shell()
    fx.app.app.resize(110, 14)
    await fx.command("/config add deepseek")
    fx.screen()
    assert not form_of(fx).boxed

    fx.app.app.resize(110, 40)
    fx.screen()

    assert form_of(fx).boxed and "\u256d" in fx.screen()


# -- /config: the panel ------------------------------------------------------------------------------------


async def test_the_panel_lists_the_models_from_the_file_with_a_row_to_add_one(shell):
    fx = shell()

    await fx.command("/config")

    screen = fx.screen()
    assert "Models" in screen and "gpt-5-mini (current)" in screen and "GPT-4o" in screen and "+ Add a model" in screen
    assert "config.toml" in screen, "the file being edited is named"
    assert "sk-one" not in screen


async def test_the_panel_reads_the_file_not_what_the_session_started_with(shell):
    fx = shell()
    fx.path.write_text(BASE + '\n[[models]]\nmodel = "added-by-hand"\ntoken = "t"\n', encoding="utf-8")

    await fx.command("/config")

    assert "added-by-hand" in fx.screen()


async def test_every_row_of_the_provider_picker_says_what_it_speaks_in_the_same_kind_of_words(shell):
    """The picker showed a note on some rows, an article on one, and a bare address on two."""
    fx = shell()
    await fx.command("/config")
    fx.choose("+ Add")

    rows = {item.label: item.description for item in fx.page(ListPage).list.items}

    assert set(rows) == {*(p.label for p in BUILTIN_PROVIDERS), "Custom"}
    for label, description in rows.items():
        assert description and not description.startswith(("the ", "The ", "http")), (label, description)
        assert not description.endswith("."), (label, description)
    assert rows["DeepSeek"] == rows["Groq"] == "chat completions"
    assert rows["Anthropic"] == "Anthropic Messages API"
    assert rows["Custom"] == "any endpoint; you give the address and the protocol"


async def test_a_plugin_provider_with_no_note_is_shown_by_its_protocol_and_not_by_its_address(shell):
    fx = shell()
    runtime = fx.app.agent.runtime
    runtime.plugins = load_plugins(
        replace(runtime.config, plugins_enabled=True),
        builtins=(),
        entry_points=[FakePoint("bare", Bare)],
    )
    await fx.command("/config")
    fx.choose("+ Add")

    rows = {item.label: item.description for item in fx.page(ListPage).list.items}

    assert rows["Bare AI"] == "Responses API"


async def test_the_api_question_names_each_protocol_without_an_article(shell):
    fx = shell()
    await fx.command("/config add custom")

    rows = [(item.label, item.description) for item in fx.page(ListPage).list.items]

    assert rows == [
        ("chat", "chat completions"),
        ("responses", "Responses API"),
        ("anthropic", "Anthropic Messages API"),
    ]


async def test_the_form_after_the_provider_is_worded_alike(shell):
    """Each hint is a sentence that ends with a full stop and starts with a capital."""
    fx = shell()
    await fx.command("/config add custom")
    fx.choose("chat")
    page = form_of(fx)

    for field in page.fields:
        assert field.hint[0].isupper() and field.hint.endswith((".", "1.", "2.")) or field.hint.endswith("."), field
    hints = {field.key: field.hint for field in page.fields}
    assert hints["model"] == "The id the provider calls the model, exactly as its documentation writes it."
    assert hints["url"] == "The address the client appends its route to, such as https://api.example.com/v1."
    assert hints["token"].startswith("Your key for this endpoint.")


async def test_a_provider_with_suggested_models_gives_them_as_an_example(shell):
    fx = shell()
    runtime = fx.app.agent.runtime
    runtime.plugins = load_plugins(
        replace(runtime.config, plugins_enabled=True), builtins=(), entry_points=[FakePoint("bare", Suggests)]
    )
    await fx.command("/config add suggests")

    page = form_of(fx)
    assert page.fields[0].hint.endswith("For example: one, two, three")
    assert page.fields[0].placeholder == "one"


async def test_adding_from_the_panel_goes_provider_then_one_form(shell):
    fx = shell()
    await fx.command("/config")

    fx.choose("+ Add")
    assert "which provider" in fx.screen()
    fx.choose("DeepSeek")
    fx.harness.write("deepseek-chat")
    fx.harness.press("tab")
    fx.harness.write("sk-panel")
    fx.harness.press("enter")

    assert fx.models[-1]["token"] == "sk-panel" and fx.configured[-1] == "deepseek-chat"
    assert any("added" in notice and "deepseek-chat" in notice for notice in fx.notices())
    assert not any("sk-panel" in notice for notice in fx.notices())


async def test_custom_is_the_last_provider_in_the_panel(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("+ Add")

    page = fx.page(ListPage)

    assert page.list.items[-1].value == "custom"
    assert [item.value.name for item in page.list.items[:-1]] == [p.name for p in BUILTIN_PROVIDERS]


async def test_escape_in_the_provider_list_goes_back_to_the_model_list(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("+ Add")

    fx.harness.press("escape")

    assert "Models" in fx.screen() and "which provider" not in fx.screen()


async def test_a_model_in_the_panel_has_every_setting_on_a_row_with_its_name_on_the_left(shell):
    fx = shell()
    await fx.command("/config")

    fx.choose("GPT-4o")

    screen = fx.screen()
    for label in (
        "Token",
        "API",
        "Address",
        "Model id",
        "Shown name",
        "Images",
        "Web search",
        "Search tool",
        "Temperature",
        "Context window",
        "Compress at",
        "Use this model",
        "Remove",
    ):
        assert label in screen
    row = next(line for line in screen.splitlines() if "Address" in line)
    assert row.index("Address") < row.index("https://proxy.example.com/v1"), "the name is left of the value"
    assert "sk-two" not in screen, "the token is never shown"
    assert fx.panel.focus_key() == "token", "the cursor starts in the first row"


async def test_images_and_web_search_are_the_rail_of_the_statusline_with_a_word_beside_it(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    off = next(line for line in fx.screen().splitlines() if "Web search" in line)
    fx.go("web_search")
    fx.harness.write(" ")
    on = next(line for line in fx.screen().splitlines() if "Web search" in line)

    assert "\u25cf" + "\u2500" * 9 in off and off.rstrip().endswith("off")
    assert on.rstrip().endswith("on")
    assert fx.panel.values["web_search"] is True


async def test_the_api_is_a_choice_that_marks_the_word_it_is_on(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    row = next(line for line in fx.screen().splitlines() if "API" in line.split("chat")[0])

    assert "\u25c9 chat" in row and "\u25cb responses" in row and "\u25cb anthropic" in row
    fx.go("api")
    fx.harness.press("right")
    assert fx.panel.values["api"] == "responses" and "\u25c9 responses" in fx.screen()
    fx.harness.press("end")
    assert fx.panel.values["api"] == "anthropic"


async def test_up_and_down_move_between_rows_and_go_round_at_the_ends(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    fx.harness.press("up")
    assert fx.panel.focus_key() == "remove"
    fx.harness.press("down")
    assert fx.panel.focus_key() == "token"
    fx.harness.press("tab")
    assert fx.panel.focus_key() == "api"
    fx.harness.press("backtab")
    assert fx.panel.focus_key() == "token"


async def test_a_press_on_a_row_puts_the_cursor_in_it_and_a_press_on_a_switch_turns_it_over(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    rows = fx.screen().splitlines()
    y = next(i for i, line in enumerate(rows) if "Address" in line)
    fx.harness.mouse_down(5, y)
    assert fx.panel.focus_key() == "base_url"

    y = next(i for i, line in enumerate(fx.screen().splitlines()) if "Web search" in line)
    x = fx.screen().splitlines()[y].index("\u25cf")
    fx.harness.mouse_down(x, y)

    assert fx.panel.focus_key() == "web_search" and fx.panel.values["web_search"] is True


async def test_the_panel_turns_a_models_web_search_on_and_off_and_names_its_tool(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.go("web_search")
    fx.harness.press("right")

    fx.harness.press("enter")

    gpt = next(model for model in fx.models if model["model"] == "gpt-4o")
    assert gpt["web_search"] is True and "web_search_name" not in gpt
    assert next(m for m in fx.app.agent.models if m.model == "gpt-4o").web_search is True

    await fx.command("/config")
    fx.choose("GPT-4o")
    assert fx.panel.values["web_search"] is True, "the switch starts where the file has it"
    fx.edit("web_search_name", "web_search_20250305")
    fx.harness.press("enter")
    assert next(m for m in fx.models if m["model"] == "gpt-4o")["web_search_name"] == "web_search_20250305"

    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.go("web_search")
    fx.harness.press("left")
    fx.harness.press("enter")

    assert "web_search" not in next(model for model in fx.models if model["model"] == "gpt-4o")
    assert fx.errors() == []


async def test_web_search_is_refused_on_deepseeks_chat_endpoint_at_the_row_that_asked_for_it(shell):
    fx = shell('[[models]]\nmodel = "deepseek-chat"\ntoken = "t"\nbase_url = "https://api.deepseek.com"\n')
    await fx.command("/config")
    fx.choose("deepseek-chat")
    fx.go("web_search")
    fx.harness.press("right")

    fx.harness.press("enter")

    assert "Anthropic" in fx.panel.refusal and fx.panel.focus_key() == "web_search"
    assert "web_search" not in fx.models[0], "nothing was written"
    assert fx.panel.values["web_search"] is True, "and the row stays as it was set"


async def test_use_this_model_switches_to_it_and_closes_the_panel(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    fx.act("use")

    assert fx.app.agent.active_model.model == "gpt-4o" and fx.app.app.screens.top.name == "main"


async def test_use_this_model_saves_what_was_changed_first(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("token", "sk-fresh")

    fx.act("use")

    assert fx.models[1]["token"] == "sk-fresh"
    assert fx.app.agent.active_model.model == "gpt-4o" and fx.app.agent.active_model.token == "sk-fresh"


async def test_changing_a_token_rewrites_only_that_key_of_that_model(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    assert fx.panel.editor("token").text == "", "the existing token is never put in the box"

    fx.edit("token", "sk-rotated")
    assert "sk-rotated" not in fx.screen(), "what is typed as a token is painted as bullets"
    fx.harness.press("enter")

    assert fx.models[1]["token"] == "sk-rotated" and fx.models[0]["token"] == "sk-one"
    assert fx.models[1]["base_url"] == "https://proxy.example.com/v1" and fx.models[1]["display_model"] == "GPT-4o"
    assert "# second" in fx.text and fx.text.startswith("# my config")


async def test_an_empty_token_row_leaves_the_token_alone(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("temperature", "0.5")

    fx.harness.press("enter")

    assert fx.models[1]["token"] == "sk-two" and fx.models[1]["temperature"] == 0.5


async def test_changing_the_token_of_the_model_in_use_keeps_it_in_use(shell):
    fx = shell()
    fx.app.change_model("gpt-4o")
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("token", "sk-rotated")

    fx.harness.press("enter")

    assert fx.app.agent.active_model.model == "gpt-4o" and fx.app.agent.active_model.token == "sk-rotated"


async def test_the_address_shows_the_current_one_and_a_bad_one_is_refused_where_it_was_typed(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    assert fx.panel.editor("base_url").text == "https://proxy.example.com/v1"
    fx.edit("token", "sk-keep-me")
    fx.edit("base_url", "proxy2.example.com")

    fx.harness.press("enter")

    assert "http or https" in fx.panel.refusal and fx.panel.focus_key() == "base_url"
    assert "http or https" in fx.screen()
    assert fx.panel.editor("token").text == "sk-keep-me", "every row stays as typed"
    assert fx.models[1]["base_url"] == "https://proxy.example.com/v1", "nothing was written"


async def test_clearing_the_address_removes_the_key(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("base_url", "")

    fx.harness.press("enter")

    assert "base_url" not in fx.models[1] and fx.app.agent.models[1].base_url is None


async def test_the_shown_name_and_the_model_id_are_saved_together_with_one_enter(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("display_model", "Fast")
    fx.edit("model", "gpt-4.1")

    fx.harness.press("enter")

    assert fx.models[1]["display_model"] == "Fast" and fx.models[1]["model"] == "gpt-4.1"
    assert any("updated Fast" in notice for notice in fx.notices())


async def test_the_model_id_cannot_be_left_empty(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("model", "")

    fx.harness.press("enter")

    assert "model id is required" in fx.panel.refusal and fx.panel.focus_key() == "model"
    assert fx.models[1]["model"] == "gpt-4o"


async def test_saving_with_nothing_changed_writes_nothing_and_says_so(shell):
    fx = shell()
    before = fx.text
    await fx.command("/config")
    fx.choose("GPT-4o")

    fx.harness.press("enter")

    assert fx.text == before and any("nothing changed" in notice for notice in fx.notices())
    assert fx.app.app.screens.top.name == "main"


async def test_the_title_says_when_a_row_was_edited(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    assert "edited" not in fx.screen().split("Token")[0]

    fx.edit("temperature", "1")

    assert "edited" in fx.screen().split("Token")[0]


async def test_removing_asks_first_and_keep_is_the_default(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.act("remove")

    assert "Remove this model?" in fx.screen()
    fx.harness.press("enter")  # the highlighted row

    assert fx.configured == ("gpt-5-mini", "gpt-4o"), "Enter on the default kept it"


async def test_removing_a_model_edits_the_file_and_the_session(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.act("remove")

    fx.choose("Remove GPT-4o")

    assert [m["model"] for m in fx.models] == ["gpt-5-mini"] and fx.configured == ("gpt-5-mini",)
    assert "# my config" in fx.text and "[skills]" in fx.text
    assert any("removed GPT-4o" in n for n in fx.notices())


async def test_removing_the_model_in_use_moves_to_its_neighbour_and_says_so(shell):
    fx = shell()
    fx.app.change_model("gpt-4o")

    await fx.command("/config remove 2")

    assert fx.app.agent.active_model.model == "gpt-5-mini"
    assert any(
        getattr(e, "kind", "") == "announcement" or "gpt-5-mini" in getattr(e, "text", "")
        for e in fx.app.transcript.entries
    )


async def test_removing_the_only_model_is_refused(shell):
    fx = shell('[[models]]\nmodel = "only"\ntoken = "t"\n')

    await fx.command("/config remove 1")

    assert any("only model" in e for e in fx.errors()) and fx.configured == ("only",)


# -- /config remove on one line --------------------------------------------------------------------------


async def test_remove_by_number_and_by_name(shell):
    fx = shell()
    await fx.command("/config add deepseek --model d1 --token t")
    await fx.command("/config add deepseek --model d2 --token t --name Two")

    await fx.command("/config remove 3")
    await fx.command("/config remove Two")

    assert fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_remove_with_a_name_that_matches_two_asks_for_a_number(shell):
    fx = shell()
    await fx.command("/config add custom --api chat --url https://b.example/v1 --model gpt-4o --token t")

    await fx.command("/config remove gpt-4o")

    assert any("more than one model" in e for e in fx.errors()) and len(fx.configured) == 3


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("/config remove", "Usage"),
        ("/config remove 9", "no model number 9"),
        ("/config remove ghost", "No model called"),
    ],
)
async def test_remove_refuses_what_it_cannot_find(shell, line, message):
    fx = shell()
    before = fx.text

    await fx.command(line)

    assert any(message in e for e in fx.errors()) and fx.text == before


# -- the file is the reader's -----------------------------------------------------------------------------


async def test_a_file_with_models_written_another_way_is_refused_with_a_reason_and_left_alone(shell):
    inline = 'models = [{ model = "a", token = "t" }]\n'
    fx = shell(inline)

    await fx.command("/config add deepseek --model m --token t")
    await fx.command("/config")

    assert any("edit the file by hand" in e for e in fx.errors()) and fx.text == inline


async def test_a_file_that_was_broken_by_hand_after_the_start_is_refused_not_overwritten(shell):
    fx = shell()
    fx.path.write_text("[[models\n", encoding="utf-8")

    await fx.command("/config add deepseek --model m --token t")

    assert any("not valid TOML" in e for e in fx.errors()) and fx.text == "[[models\n"


async def test_a_file_that_vanished_is_reported_not_recreated(shell):
    fx = shell()
    fx.path.unlink()

    await fx.command("/config add deepseek --model m --token t")

    assert any("does not exist" in e for e in fx.errors()) and not fx.path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
async def test_the_permissions_of_the_file_survive_an_edit(shell):
    fx = shell()
    os.chmod(fx.path, 0o600)

    await fx.command("/config add deepseek --model m --token t")

    assert stat.S_IMODE(fx.path.stat().st_mode) == 0o600


async def test_a_write_that_fails_leaves_the_file_and_the_session_as_they_were(shell, monkeypatch):
    fx = shell()
    before = fx.text

    def fail(source, target):
        raise OSError("read-only file system")

    monkeypatch.setattr(os, "replace", fail)

    await fx.command("/config add deepseek --model m --token t")

    assert any("could not be written" in e for e in fx.errors())
    assert fx.text == before and fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_after_an_edit_a_fresh_load_of_the_file_agrees_with_the_running_session(shell):
    fx = shell()
    await fx.command("/config add deepseek --model deepseek-chat --token sk-x --multimodal")
    await fx.command("/config remove 1")

    reloaded = load_config(fx.path.parent / "work", path=fx.path)

    assert reloaded.models == fx.app.agent.models


# -- the session after an edit ---------------------------------------------------------------------------


async def test_replacing_models_keeps_the_one_in_use_and_moves_the_compaction_thresholds_with_it(shell):
    fx = shell()
    fx.app.change_model("gpt-4o")
    runtime = fx.app.agent.runtime

    runtime.replace_models(runtime.config.models + (replace(runtime.config.models[0], model="extra"),))

    assert runtime.active_model.model == "gpt-4o"
    assert runtime.compaction.max_tokens == runtime.active_model.compaction_max_tokens


def test_replacing_models_with_none_is_refused(shell):
    fx = shell()

    with pytest.raises(ValueError, match="At least one model"):
        fx.app.agent.runtime.replace_models(())


async def test_the_header_shows_the_model_that_replaced_a_removed_one(shell):
    fx = shell()
    fx.app.change_model("gpt-4o")
    assert "GPT-4o" in fx.screen().splitlines()[0]

    await fx.command("/config remove 2")

    assert "gpt-5-mini" in fx.screen().splitlines()[0]


# -- the agent ----------------------------------------------------------------------------------------------


def test_the_agent_offers_the_builtin_providers_first(shell):
    fx = shell()

    assert [p.name for p in fx.app.agent.providers][: len(BUILTIN_PROVIDERS)] == [p.name for p in BUILTIN_PROVIDERS]


def test_file_models_pairs_each_model_with_the_keys_the_file_writes(shell):
    fx = shell()

    pairs = fx.app.agent.file_models()

    assert [m.model for m, _ in pairs] == ["gpt-5-mini", "gpt-4o"]
    assert pairs[0][1] == {"model": "gpt-5-mini", "token": "sk-one"}


def test_a_token_from_the_environment_is_not_written_into_the_file_by_an_edit(shell, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    fx = shell('[[models]]\nmodel = "a"\n\n[[models]]\nmodel = "b"\ntoken = "t"\n')

    fx.app.agent.update_configured_model(1, {"model": "b", "token": "t2"})

    assert "sk-from-env" not in fx.text and fx.text.startswith('[[models]]\nmodel = "a"\n')


def test_editing_a_model_that_is_not_there_is_an_error_not_a_crash(shell):
    fx = shell()

    with pytest.raises(ConfigEditError):
        fx.app.agent.remove_configured_model(7)


# -- plugins can describe providers --------------------------------------------------------------------------


class Acme(Plugin):
    name = "acme"

    def activate(self, container: PluginContainer) -> None:
        container.register_provider(
            Provider("acme", "Acme AI", base_url="https://api.acme.example/v1", note="from the acme plugin")
        )


class Bare(Plugin):
    name = "bare"

    def activate(self, container: PluginContainer) -> None:
        container.register_provider(Provider("bare", "Bare AI", api=Api.RESPONSES, base_url="https://bare.example/v1"))


class Suggests(Plugin):
    name = "suggests"

    def activate(self, container: PluginContainer) -> None:
        container.register_provider(
            Provider("suggests", "Suggests AI", base_url="https://s.example/v1", models=("one", "two", "three", "four"))
        )


class FakePoint:
    def __init__(self, name: str, target: object) -> None:
        self.name, self._target = name, target

    def load(self) -> object:
        return self._target


def test_a_plugin_provider_is_offered_by_the_agent_after_the_builtins(shell):
    fx = shell()
    runtime = fx.app.agent.runtime
    runtime.plugins = load_plugins(
        replace(runtime.config, plugins_enabled=True), builtins=(), entry_points=[FakePoint("acme", Acme)]
    )

    names = [p.name for p in fx.app.agent.providers]

    assert names[-1] == "acme" and names[: len(BUILTIN_PROVIDERS)] == [p.name for p in BUILTIN_PROVIDERS]


async def test_a_plugin_provider_works_with_config_add(shell):
    fx = shell()
    runtime = fx.app.agent.runtime
    runtime.plugins = load_plugins(
        replace(runtime.config, plugins_enabled=True),
        builtins=AGENT_PLUGINS,
        entry_points=[FakePoint("acme", Acme)],
        shared=runtime_inputs(runtime),
    )

    await fx.command("/config add acme --model acme-1 --token sk-acme")

    assert fx.models[-1] == {
        "model": "acme-1",
        "token": "sk-acme",
        "base_url": "https://api.acme.example/v1",
    }


async def test_a_plugin_provider_is_a_row_in_the_panel(shell):
    fx = shell()
    runtime = fx.app.agent.runtime
    runtime.plugins = load_plugins(
        replace(runtime.config, plugins_enabled=True), builtins=(), entry_points=[FakePoint("acme", Acme)]
    )
    await fx.command("/config")

    fx.choose("+ Add")

    assert "Acme AI" in fx.screen() and "from the acme plugin" in fx.screen()


# -- the panel is a surface of its own -----------------------------------------------------------------------


async def test_the_form_panel_hides_what_is_underneath_it(shell):
    """The status line's keys must not show beside the panel's own text."""
    fx = shell()
    await fx.command("/config add deepseek --model deepseek-chat")

    rows = fx.screen().splitlines()
    panel = [row for row in rows if "enter save" in row]

    assert panel and "interrupt" not in panel[0] and "^D" not in panel[0]


# -- Escape goes back one step; it never throws the whole thing away -------------------------------------------


async def test_escape_from_the_form_of_a_custom_endpoint_goes_back_to_the_api_list_and_writes_nothing(shell):
    fx = shell()
    before = fx.text
    await fx.command("/config add custom")
    fx.choose("chat")
    fx.harness.write("my-model")

    fx.harness.press("escape")

    assert fx.page(ListPage) is not None and "Which API" in fx.screen()
    assert fx.text == before and fx.app.app.screens.top.name == "page"


async def test_the_api_can_be_chosen_again_and_the_form_goes_on_from_there(shell):
    fx = shell()
    await fx.command("/config add custom")
    fx.choose("chat")
    fx.harness.press("escape")

    fx.choose("anthropic")
    fx.harness.write("claude-x")
    fx.harness.press("enter")

    assert fx.models[-1] == {"model": "claude-x", "anthropic": True}


async def test_escape_from_the_form_of_the_panel_goes_back_to_the_provider_list(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("+ Add")
    fx.choose("DeepSeek")
    assert fx.page(FormPage) is not None

    fx.harness.press("escape")

    assert "which provider" in fx.screen()
    fx.harness.press("escape")
    assert "Models" in fx.screen() and "+ Add a model" in fx.screen()
    fx.harness.press("escape")
    assert fx.app.app.screens.top.name == "main", "and only from the very first page does it close"


async def test_escape_from_the_form_of_a_typed_line_closes_because_nothing_is_behind_it(shell):
    fx = shell()
    before = fx.text
    await fx.command("/config add deepseek")

    fx.harness.press("escape")

    assert fx.app.app.screens.top.name == "main" and fx.text == before


async def test_going_back_writes_nothing(shell):
    fx = shell()
    before = fx.text
    await fx.command("/config add deepseek --model deepseek-chat")
    fx.harness.press("tab")
    fx.harness.write("sk-secret")
    fx.harness.press("escape")

    assert fx.text == before and "sk-secret" not in fx.text


async def test_the_keys_line_says_back_when_there_is_a_step_behind_and_cancel_when_there_is_not(shell):
    fx = shell()
    await fx.command("/config add deepseek")
    assert "esc cancel" in fx.screen() and "tab next line" in fx.screen() and "enter save" in fx.screen()
    fx.harness.press("escape")
    await fx.command("/config")
    fx.choose("+ Add")
    fx.choose("DeepSeek")

    assert "esc back" in fx.screen()


async def test_escape_in_the_panel_of_a_model_goes_back_to_the_list_and_writes_nothing_of_what_was_typed(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.edit("token", "sk-abandoned")
    fx.go("web_search")
    fx.harness.press("right")
    before = fx.text

    fx.harness.press("escape")

    assert "+ Add a model" in fx.screen() and fx.page(ModelSettingsPage) is None
    assert fx.text == before and "sk-abandoned" not in fx.text


async def test_escape_in_the_actions_goes_back_to_the_model_list(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")

    fx.harness.press("escape")

    assert "+ Add a model" in fx.screen() and "Use this model" not in fx.screen()


async def test_escape_in_the_remove_question_goes_back_to_the_models_actions_and_removes_nothing(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.act("remove")

    fx.harness.press("escape")

    assert "Use this model" in fx.screen() and fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_keeping_a_model_returns_to_its_actions_too(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    fx.act("remove")

    fx.choose("Keep it")

    assert "Use this model" in fx.screen() and fx.configured == ("gpt-5-mini", "gpt-4o")


async def test_a_token_is_never_put_back_in_the_form_after_going_back(shell):
    """The api list is behind the form of a custom endpoint; coming back to the form shows no token the reader typed."""
    fx = shell()
    await fx.command("/config add custom")
    fx.choose("chat")
    fx.harness.write("my-model")
    fx.harness.press("tab")
    fx.harness.write("sk-never-shown-again")
    fx.harness.press("escape")

    fx.choose("chat")

    assert form_of(fx).areas["token"].text == ""
    assert "sk-never-shown-again" not in fx.screen()


# -- changing the protocol of a model already in the file ---------------------------------------------------


async def _to_api(fx, model: str, api: str) -> None:
    await fx.command("/config")
    fx.choose(model)
    fx.pick("api", api)
    fx.harness.press("enter")


@pytest.mark.parametrize(
    ("api", "keys"),
    [("responses", {"responses_api": True}), ("anthropic", {"anthropic": True}), ("chat", {})],
)
async def test_the_protocol_of_a_model_can_be_changed_to_each_of_the_three(shell, api, keys):
    # It starts on the Responses API, so every row below is a change or, for that one, a no-op.
    fx = shell(BASE.replace('token = "sk-two"', 'token = "sk-two"\nresponses_api = true'))
    await _to_api(fx, "GPT-4o", api)

    entry = fx.models[1]
    assert {k: v for k, v in entry.items() if k in ("anthropic", "responses_api")} == keys
    assert entry["token"] == "sk-two" and entry["base_url"] == "https://proxy.example.com/v1"
    assert fx.app.agent.models[1].api == api
    assert any((api in notice) if api != "responses" else ("nothing changed" in notice) for notice in fx.notices())


async def test_changing_between_anthropic_and_responses_never_leaves_both_set(shell):
    fx = shell()
    await _to_api(fx, "GPT-4o", "anthropic")
    await _to_api(fx, "GPT-4o", "responses")

    assert fx.models[1].get("responses_api") is True and "anthropic" not in fx.models[1]
    assert fx.errors() == []


async def test_the_api_row_starts_on_the_current_protocol(shell):
    fx = shell()
    await fx.command("/config")

    fx.choose("GPT-4o")

    assert fx.panel.values["api"] == "chat" and "\u25c9 chat" in fx.screen()


async def test_changing_the_protocol_of_the_model_in_use_keeps_it_in_use(shell):
    fx = shell()
    fx.app.change_model("gpt-4o")

    await _to_api(fx, "GPT-4o", "responses")

    assert fx.app.agent.active_model.model == "gpt-4o" and fx.app.agent.active_model.api == "responses"


async def test_moving_the_api_changes_nothing_until_enter(shell):
    fx = shell()
    await fx.command("/config")
    fx.choose("GPT-4o")
    before = fx.text
    fx.pick("api", "anthropic")

    assert fx.text == before and fx.app.agent.models[1].api == "chat"
    fx.harness.press("escape")

    assert fx.text == before


async def test_choosing_the_protocol_it_already_has_changes_nothing_in_the_file(shell):
    fx = shell()
    before = fx.models

    await _to_api(fx, "GPT-4o", "chat")

    assert fx.models == before


async def test_the_api_row_starts_on_the_current_one_when_it_is_not_the_first(shell):
    fx = shell(BASE.replace('token = "sk-two"', 'token = "sk-two"\nanthropic = true'))
    await fx.command("/config")
    fx.choose("GPT-4o")

    assert fx.panel.values["api"] == "anthropic" and "\u25c9 anthropic" in fx.screen()
