"""Guard bilingual page coverage and the offline terminal asset generator."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

import zettcode
from zettcode.app.commands import CommandContext, CommandUi
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.plugins import PluginContainer
from zettcode.tui import Canvas, Style
from zettcode.tui.theme_file import theme_from_toml

ROOT = Path(zettcode.__file__).resolve().parents[2]


def code_blocks(path: str, language: str) -> list[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(rf"^```{language}[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "README.zh-CN.md",
        "docs/guide/getting-started.md",
        "docs/zh/guide/getting-started.md",
        "docs/guide/config.md",
        "docs/zh/guide/config.md",
    ],
)
def test_documented_config_examples_load_with_the_real_parser(path, tmp_path, monkeypatch):
    from zettcode import config as config_module
    from zettcode._compat import tomllib

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config_module, "_default_theme_file", lambda: None)
    examples = code_blocks(path, "toml")
    assert examples, f"No config examples found in {path}"

    for example in examples:
        payload = tomllib.loads(example)
        if "base" in payload:
            theme = theme_from_toml(example)
            assert theme.background is None, "Theme examples must preserve the terminal background by default"
            continue
        if "models" not in payload:
            example = '[[models]]\nmodel = "example-model"\ntoken = "example-key"\n\n' + example
        target = tmp_path / "config.toml"
        target.write_text(example, encoding="utf-8")
        config = load_config(tmp_path, path=target)
        assert config.workspace == tmp_path.resolve()
        for model in config.models:
            if model.model.startswith("deepseek"):
                assert model.base_url == "https://api.deepseek.com"
                assert model.responses_api is False
                assert model.compaction_max_tokens == 800_000
                assert model.multimodal is (model.model == "deepseek-flash")


@pytest.mark.parametrize("path", ["docs/guide/skills-and-mcp.md", "docs/zh/guide/skills-and-mcp.md"])
def test_documented_mcp_examples_parse_without_starting_servers(path):
    import json

    from zett_agent.extensions.mcp import McpConfiguration

    examples = code_blocks(path, "json")
    assert len(examples) == 2
    local, remote = [McpConfiguration.from_mapping(json.loads(example)) for example in examples]
    assert local.servers[0].command == "npx"
    assert local.servers[0].args == ("-y", "chrome-devtools-mcp@latest")
    assert remote.servers[0].url == "http://127.0.0.1:9000/mcp"


class ExampleCommandUi(CommandUi):
    def __init__(self):
        self.events = []

    def markdown(self, text):
        self.events.append(("markdown", text))

    def notice(self, text):
        self.events.append(("notice", text))

    def error(self, text):
        self.events.append(("error", text))

    def notify(self, text, *, level="info"):
        self.events.append((level, text))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["docs/guide/plugins.md", "docs/zh/guide/plugins.md"])
async def test_documented_plugin_registers_and_runs_its_command(path, tmp_path):
    examples = code_blocks(path, "python")
    assert len(examples) == 3
    namespace = {}
    for example in examples:
        exec(compile(example, path, "exec"), namespace)
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="example-model", token="example-key"),),
    )
    container = PluginContainer(config)
    plugin = namespace["Greeter"]()
    plugin.activate(container)
    assert [command.name for command in container.commands] == ["/greet"]
    ui = ExampleCommandUi()
    result = await container.commands[0].handler(CommandContext(argument="Ada", ui=ui))
    assert result.notification == "hello Ada"
    assert ui.events == []

    progress_handler = namespace["greet"]
    result = await progress_handler(plugin, CommandContext(argument="", ui=ui))
    assert ui.events == [("error", "Usage: /greet <name>")]
    assert result.message == ""
    ui.events.clear()
    result = await progress_handler(plugin, CommandContext(argument="Ada", ui=ui))
    assert ui.events == [("notice", "Preparing a greeting…")]
    assert result.message == "## Hello\n\nWelcome, Ada."


@pytest.fixture
def render_terminal():
    path = ROOT / "docs/scripts/render_terminal.py"
    spec = importlib.util.spec_from_file_location("render_terminal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_english_guide_page_has_a_chinese_counterpart():
    english = {path.name for path in (ROOT / "docs/guide").glob("*.md")}
    chinese = {path.name for path in (ROOT / "docs/zh/guide").glob("*.md")}

    assert english == chinese
    assert "overview.md" in english


def test_the_terminal_preview_is_offline_deterministic_and_leaves_no_workspace(render_terminal, monkeypatch):
    def refuse_start(*args, **kwargs):
        raise AssertionError("Documentation assets must never start a model or contact an API")

    monkeypatch.setattr(render_terminal.ZettCodeRuntime, "start", refuse_start)
    before = Path.cwd()
    real_cleanup = render_terminal.tempfile.TemporaryDirectory.cleanup

    def cleanup(directory):
        assert Path.cwd() == before, "Windows cannot remove a temporary directory while it is the current directory"
        real_cleanup(directory)

    monkeypatch.setattr(render_terminal.tempfile.TemporaryDirectory, "cleanup", cleanup)
    first = render_terminal.preview()
    second = render_terminal.preview()

    assert Path.cwd() == before
    assert render_terminal.svg(first) == render_terminal.svg(second)
    text = "\n".join("".join(cell.character for cell in row) for row in first.cells)
    assert "~/projects/api" in text
    assert "ZettCode" in text
    assert "▄ ▄" in text and "▀█▀" in text
    assert "example-token" not in text
    assert "zettcode-docs-" not in text


def test_a_failed_preview_restores_the_working_directory(render_terminal, monkeypatch):
    def fail_to_paint(self):
        raise RuntimeError("paint failed")

    monkeypatch.setattr(render_terminal.Canvas, "__post_init__", fail_to_paint)
    before = Path.cwd()

    with pytest.raises(RuntimeError, match="paint failed"):
        render_terminal.preview()

    assert Path.cwd() == before


def test_the_terminal_svg_escapes_text_and_does_not_duplicate_wide_glyphs(render_terminal):
    canvas = Canvas(12, 1)
    canvas.draw_text(0, 0, '<script>&"中', Style(foreground="#123456"))

    source = render_terminal.svg(canvas)
    root = ElementTree.fromstring(source)
    text = "".join(node.text or "" for node in root.iter("{http://www.w3.org/2000/svg}text"))

    assert text == '<script>&"中'
    assert "<script>" not in source
    assert source.count("中") == 1
    assert "\x1b" not in source
