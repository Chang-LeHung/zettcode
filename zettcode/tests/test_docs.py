"""Guard bilingual page coverage and the offline terminal asset generator."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
from zett_agent.extensions.base import AgentExtension

from zettcode.app.agent.conversation.entries import TextEntry
from zettcode.app.agent.conversation.presenters import WelcomePresenter
from zettcode.app.brand import LOGO_LINES, LOGO_PALETTE, LOGO_PIXELS
from zettcode.app.commands import CommandContext, CommandUi
from zettcode.app.plugins import TerminalContainer
from zettcode.app.ui.widgets.welcome import WELCOME
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.tui import DARK, Canvas, Style
from zettcode.tui.theme_file import theme_from_toml

#: The repository root: the workspace around this package (``zettcode/``), which holds ``docs/``.
ROOT = Path(__file__).resolve().parents[2]


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
            if model.model.startswith("deepseek") and model.anthropic:
                # The web-search example: DeepSeek's Anthropic-compatible endpoint, the only one it is searched on.
                assert model.base_url == "https://api.deepseek.com/anthropic"
                assert model.web_search is True and model.can_search is True
                assert model.search_name == "web_search_20250305"
            elif model.model.startswith("deepseek"):
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
    assert len(examples) == 5
    namespace = {}
    for example in examples:
        exec(compile(example, path, "exec"), namespace)
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="example-model", token="example-key"),),
    )
    container = TerminalContainer(config)
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

    # The provider example is run as written: what the page says a plugin can describe is what loads.
    described = TerminalContainer(config)
    namespace["Acme"]().activate(described)
    (provider,) = described.providers
    assert (provider.name, provider.label, provider.api) == ("acme", "Acme AI", "chat")
    assert provider.base_url == "https://api.acme.example/v1" and provider.token_env == "ACME_API_KEY"

    # The extension example is run as written too, with a stand-in for the extension it names.
    class AuditExtension(AgentExtension):
        name = "audit"

    namespace["AuditExtension"] = AuditExtension
    handed = TerminalContainer(config)
    namespace["Audit"]().activate(handed)
    assert [type(contribution.extension) for contribution in handed.extensions] == [AuditExtension]


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

    monkeypatch.setattr(render_terminal.ZettCodeEngine, "start", refuse_start)
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
    assert all(line.text in text for line in LOGO_LINES)
    assert "example-token" not in text
    assert "zettcode-docs-" not in text


def test_published_brand_assets_match_the_shared_terminal_pixels(render_terminal):
    # The site's logo is the brand mark (the same file the editor extension ships); the pixel robot is the terminal's
    # own face and appears only in the terminal preview.
    assert (ROOT / "docs/public/logo.svg").read_text(encoding="utf-8").replace("<title>ZettCode</title>\n  ", "") == (
        ROOT / "clients/vscode/media/logo.svg"
    ).read_text(encoding="utf-8").replace("<title>ZettCode</title>\n  ", "")
    canvas = render_terminal.preview()
    assert (ROOT / "docs/public/terminal.svg").read_text(encoding="utf-8") == render_terminal.svg(canvas)
    lines = WelcomePresenter().lines(TextEntry(id=0, kind="welcome", text=WELCOME), 60, DARK, 0)
    for index, line in enumerate(lines[: len(LOGO_LINES)]):
        expected = Canvas(line.width, 1)
        expected.fill(0, 0, line.width, 1, style=Style(background="#232a2e"))
        expected.draw_spans(0, 0, line.spans)
        assert canvas.cells[index + 2][2 : 2 + line.width] == expected.cells[0]


def test_logo_svg_preserves_every_shared_pixel(render_terminal):
    root = ElementTree.fromstring(render_terminal.logo_svg())
    assert root.attrib["viewBox"] == "0 0 32 32"
    assert root.attrib["shape-rendering"] == "crispEdges"
    pixels = [["."] * 32 for _ in range(32)]
    palette = {colour: pixel for pixel, colour in LOGO_PALETTE.items()}
    for path in root.findall("{http://www.w3.org/2000/svg}path"):
        commands = re.findall(r"M(\d+) (\d+)h(\d+)v(\d+)h-(\d+)Z", path.attrib["d"])
        assert (
            "".join(f"M{left} {top}h{width}v{height}h-{back}Z" for left, top, width, height, back in commands)
            == path.attrib["d"]
        )
        for left, top, width, height, back in commands:
            assert width == back
            for row in range(int(top), int(top) + int(height)):
                for column in range(int(left), int(left) + int(width)):
                    assert pixels[row][column] == ".", "Brand pixels must never overlap or hide another colour"
                    pixels[row][column] = palette[path.attrib["fill"]]
    expected = ["." * 32] * 6
    for row in LOGO_PIXELS:
        expected.extend(["." + "".join(pixel * 2 for pixel in row) + "."] * 2)
    expected.extend(["." * 32] * 6)
    assert ["".join(row) for row in pixels] == expected


def test_terminal_svg_preserves_every_welcome_pixel_without_scaling_seams(render_terminal):
    root = ElementTree.fromstring(render_terminal.svg(render_terminal.preview()))
    assert root.attrib["shape-rendering"] == "crispEdges"
    left, top, width, height = 40, 40, 150, 100
    pixels = [["."] * width for _ in range(height)]
    palette = {colour: pixel for pixel, colour in LOGO_PALETTE.items()}
    for rect in root.iter("{http://www.w3.org/2000/svg}rect"):
        rect_left, rect_top = int(rect.get("x", "0")), int(rect.get("y", "0"))
        start_x, start_y = max(left, rect_left), max(top, rect_top)
        end_x = min(left + width, rect_left + int(rect.attrib["width"]))
        end_y = min(top + height, rect_top + int(rect.attrib["height"]))
        if start_x >= end_x or start_y >= end_y:
            continue
        pixel = palette.get(rect.attrib["fill"], ".")
        for row in range(start_y - top, end_y - top):
            pixels[row][start_x - left : end_x - left] = [pixel] * (end_x - start_x)
    expected = ["".join(pixel * 10 for pixel in row) for row in LOGO_PIXELS for _ in range(10)]
    assert ["".join(row) for row in pixels] == expected


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


# -- the guide's contents, its links, and the screens it shows ---------------------------------------------------


def _node_slug(text: str) -> str:
    """Return the anchor VitePress gives a heading: lower-cased, punctuation dropped, spaces to dashes."""
    return re.sub(r"[^\w\u4e00-\u9fff\- ]", "", text.strip().lower()).replace(" ", "-")


def _headings(path: Path) -> set[str]:
    """Return the anchors a page answers to: an explicit ``{#id}``, or the one its heading text gets."""
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.*)$", line)
        if match is None:
            continue
        text = match.group(1).strip()
        explicit = re.search(r"\{#([^}]+)\}\s*$", text)
        found.add(explicit.group(1) if explicit else _node_slug(re.sub(r"\{#([^}]+)\}\s*$", "", text)))
    return found


def _navigation(language: str) -> dict:
    """Read the sidebar and menus the site really builds, by running its own ``navigation.ts``."""
    script = (
        "import { navigation } from "
        f'"{ROOT}/docs/.vitepress/navigation.ts";'
        f"console.log(JSON.stringify(navigation({language!r})));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"node cannot run the site's navigation: {result.stderr[-300:]}")
    return json.loads(result.stdout)


def _linked_slugs(navigation: dict, prefix: str, *, menus: bool = True) -> list[str]:
    """Return every page the sidebar links to, in order and subgroups included; optionally the menus too."""
    found: list[str] = []

    def visit(item: dict) -> None:
        link = item.get("link")
        if link and link.startswith(prefix):
            found.append(link[len(prefix) :])
        for child in item.get("items", ()):
            visit(child)

    for group in navigation["sidebar"][prefix]:
        visit(group)
    if menus:
        for menu in navigation["nav"]:
            for item in menu.get("items", ()):
                visit(item)
    return found


@pytest.mark.parametrize(
    "language,prefix,directory", [("en", "/guide/", "docs/guide"), ("zh", "/zh/guide/", "docs/zh/guide")]
)
def test_every_guide_page_is_reachable_from_the_sidebar(language, prefix, directory):
    """A page that exists but is not in the sidebar can only be found by guessing its address."""
    navigation = _navigation(language)
    linked = _linked_slugs(navigation, prefix, menus=False)
    pages = {path.stem for path in (ROOT / directory).glob("*.md")}

    assert pages - set(linked) == set(), "every page is listed"
    assert set(linked) <= pages, "and nothing listed is missing"
    assert len(linked) == len(set(linked)), "no page listed twice"
    if prefix in ("/guide/", "/zh/guide/"):
        assert "usage" in linked and "context" in linked

    # The menus list the same pages again, and not all of them by design: the first pages are reached from their
    # own nav entries. What must hold is that no menu points anywhere that is not a page.
    menu_links = [
        link for menu in navigation["nav"] for link in _linked_slugs({"sidebar": {prefix: []}, "nav": [menu]}, prefix)
    ]
    assert set(menu_links) <= pages


def test_the_models_and_context_pages_are_nested_together():
    """The three pages about the window are one subject, so the sidebar lists them under one heading."""
    navigation = _navigation("en")

    subgroups = [
        group
        for section in navigation["sidebar"]["/guide/"]
        for group in section["items"]
        if group.get("items") and group["text"] == "Models & context"
    ]

    assert len(subgroups) == 1
    assert [page["link"] for page in subgroups[0]["items"]] == ["/guide/models", "/guide/context", "/guide/usage"]


def test_every_guide_link_points_at_a_page_and_an_anchor_that_exists():
    """A guide link is checked against the files themselves: a renamed heading must not leave a dead anchor."""
    anchors = {path.stem: _headings(path) for path in (ROOT / "docs/guide").glob("*.md")}
    anchors |= {f"zh/{path.stem}": _headings(path) for path in (ROOT / "docs/zh/guide").glob("*.md")}
    broken: list[str] = []
    for path in sorted((ROOT / "docs/guide").glob("*.md")) + sorted((ROOT / "docs/zh/guide").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for link in re.findall(r"\]\((/[^)\s]+)\)", text):
            if link.startswith(("#", "/screens/", "/sdk/", "/zh/sdk/")):  # the SDK pages are checked by test_sdk_docs
                continue
            target, _, anchor = link.partition("#")
            page = target.removeprefix("/zh/guide/") if target.startswith("/zh/") else target.removeprefix("/guide/")
            page = f"zh/{page}" if target.startswith("/zh/") else page
            if page not in anchors:
                broken.append(f"{path.name}: {link} names no page")
            elif anchor and anchor not in anchors[page]:
                broken.append(f"{path.name}: {link} names no heading")

    assert broken == []


def test_every_picture_the_guide_shows_is_published():
    """The clips below the pictures are the page's own words; the files they name must be in ``docs/public``."""
    broken: list[str] = []
    for path in sorted((ROOT / "docs/guide").glob("*.md")) + sorted((ROOT / "docs/zh/guide").glob("*.md")):
        for source in re.findall(r"!\[[^\]]*\]\((/[^)\s]+)\)", path.read_text(encoding="utf-8")):
            if not (ROOT / "docs/public" / source.removeprefix("/")).is_file():
                broken.append(f"{path.name}: {source}")

    assert broken == []


def test_published_screens_match_the_widgets_that_paint_them():
    """The pictures are generated, not drawn: this fails when a widget changes and they were not regenerated."""
    module = _render_screens()

    for name, text in module.render_all().items():
        published = ROOT / "docs/public/screens" / name
        assert published.is_file(), f"{name} was never written"
        assert published.read_text(encoding="utf-8") == text, (
            f"{name} is out of date: run docs/scripts/render_screens.py"
        )


def test_the_screens_agree_with_what_the_guide_says_about_them():
    """Every figure the pages quote is on the picture they quote it from, so the prose cannot drift from the sample."""
    module = _render_screens()
    pictures = {
        name: "".join("".join(cell.character for cell in row) for row in paint().cells)
        for name, paint, _ in module.SCREENS
    }
    quoted = {
        "usage-models": ("3.14M tokens", "43 requests · 3 sessions", "61.07%", "2.40M tokens · 34 requests"),
        "usage-sessions": ("Fix the parser crash", "76.51%", "1.45M", "Pagination for /use"),
        "usage-calendar": ("Sat 17 Oct 2026", "16 active days · longest streak 4", "168K tokens"),
        "context": ("103,241 / 200,000", "51.6%", "compacts at 160,000 tokens (80.0%)", "62,069", "60.1%"),
        "context-near": ("158,900 / 200,000", "1,100", "Compaction summary", "93,654"),
        "context-resumed": ("84,000 / 200,000", "pending", "42.0%"),
    }
    for name, figures in quoted.items():
        for figure in figures:
            assert figure in pictures[name], f"{name} does not show {figure!r}"


def _render_screens():
    """Load ``docs/scripts/render_screens.py`` the way the guide's generator is run."""
    sys.path.insert(0, str(ROOT / "docs/scripts"))
    try:
        # `render_screens` imports `render_terminal` by name, and a dataclass in the module needs the module itself
        # registered while its body runs: `module_from_spec` alone leaves that lookup empty.
        spec = importlib.util.spec_from_file_location("render_screens", ROOT / "docs/scripts/render_screens.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["render_screens"] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT / "docs/scripts"))
    return module
