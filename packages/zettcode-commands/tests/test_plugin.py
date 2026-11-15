"""The commands plugin registers every command group, in the order /help lists them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from zettcode.app.plugins.loader import terminal_context
from zettcode.commands.plugin import CommandsPlugin
from zettcode.config import ModelConfig, ZettCodeConfig


def _config(tmp_path: Path) -> ZettCodeConfig:
    return replace(ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)))


def test_the_commands_are_registered_in_the_order_help_lists_them(tmp_path: Path):
    ctx = terminal_context(_config(tmp_path))

    CommandsPlugin().activate(ctx)

    names = [command.name for command in ctx.tui.registered_commands]
    assert names[:2] == ["/help", "/plugins"]
    assert names[-1:] == ["/hub"]
    assert {"/resume", "/model", "/btw", "/bash", "/clear", "/quit", "/hub"} <= set(names)
    assert [plain.name for plain in ctx.commands.commands] == ["/code-review"]


def test_without_a_screen_it_registers_nothing_and_does_not_fail(tmp_path: Path):
    from zettcode.engine.plugins.context import PluginContext

    ctx = PluginContext(_config(tmp_path), {})

    CommandsPlugin().activate(ctx)

    assert ctx.tui is None and ctx.commands.commands == ()


def test_the_model_menu_offers_a_name_with_spaces_beside_the_plain_ones():
    from types import SimpleNamespace

    from zettcode.commands.handlers import model_words
    from zettcode.sdk.types import ModelInfo

    def info(model: str, display: str | None = None, provider: str | None = None) -> ModelInfo:
        return ModelInfo(
            name=display or model,
            model=model,
            context_window=1_000,
            multimodal=False,
            efforts=(),
            display_model=display,
            provider=provider,
            api="anthropic",
        )

    models = (info("plain-model"), info("deepseek-flash", "DeepSeek V4.1 Flash", "deepseek"))
    host = SimpleNamespace(client=SimpleNamespace(models=models))

    words = model_words(host)  # type: ignore[arg-type]

    assert [word.name for word in words] == ["plain-model", "DeepSeek V4.1 Flash"]
    assert words[1].description == "plugin deepseek · anthropic · deepseek-flash"
