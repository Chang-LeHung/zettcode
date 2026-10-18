"""The SDK documentation shows code; the code has to be code that exists, and the pages have to be reachable."""

from __future__ import annotations

import ast
import asyncio
import builtins
import json
import re
import subprocess
from pathlib import Path

import pytest

import zettcode.sdk as sdk

#: The repository root: the workspace around this package (``zettcode/``), which holds ``docs/``.
ROOT = Path(__file__).resolve().parents[2]
ENGLISH = sorted((ROOT / "docs/sdk").glob("*.md"))
CHINESE = sorted((ROOT / "docs/zh/sdk").glob("*.md"))
PAGES = [str(path.relative_to(ROOT)) for path in ENGLISH + CHINESE]


def blocks(page: str) -> list[str]:
    text = (ROOT / page).read_text(encoding="utf-8")
    return re.findall(r"^```python[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


def slug(heading: str) -> str:
    """Return the anchor VitePress gives a heading: punctuation and spaces become one dash."""
    explicit = re.search(r"\{#([^}]+)\}\s*$", heading)
    if explicit:
        return explicit.group(1)
    text = re.sub(r"`", "", heading).strip().lower()
    return re.sub(r"[\s~!@#$%^&*()\-_+=\[\]{}|\\;:\"'“”‘’<>,.?/]+", "-", text).strip("-")


def anchors(path: Path) -> set[str]:
    text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE | re.DOTALL)
    return {slug(match.group(1)) for match in re.finditer(r"^#{1,6}\s+(.*)$", text, re.MULTILINE)}


def test_there_is_a_page_for_every_part_of_the_sdk():
    assert {path.stem for path in ENGLISH} == {
        "index",
        "quickstart",
        "concepts",
        "client",
        "running",
        "events",
        "approvals",
        "sessions",
        "errors",
        "cookbook",
        "reference",
    }


def test_every_english_page_has_a_chinese_counterpart():
    assert {path.name for path in ENGLISH} == {path.name for path in CHINESE}


@pytest.mark.parametrize("page", PAGES)
def test_every_example_is_valid_python(page):
    """An example that does not parse teaches nothing; top-level ``await`` is allowed since the SDK is async."""
    found = blocks(page)
    if Path(page).name == "index.md":
        assert found, "the front page shows the package in use"
    for position, source in enumerate(found, 1):
        try:
            compile(source, f"{page} example {position}", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError as error:
            pytest.fail(f"{page} example {position}: {error}\n{source}")


@pytest.mark.parametrize("page", PAGES)
def test_a_process_pool_example_is_guarded_by_main(page):
    """Found by running the recipe against a real model: where processes spawn (macOS, Windows) an unguarded pool breaks."""
    for source in blocks(page):
        if "ProcessPoolExecutor" in source or "multiprocessing" in source:
            assert 'if __name__ == "__main__":' in source


@pytest.mark.parametrize("page", PAGES)
def test_every_name_the_examples_take_from_the_package_exists(page):
    """``zc.Name`` in an example must be something ``zettcode.sdk`` really offers, or it fails for the reader."""
    names: set[str] = set()
    for source in blocks(page):
        names.update(re.findall(r"\bzc\.([A-Za-z_][A-Za-z_0-9]*)", source))

    assert {name for name in names if not hasattr(sdk, name)} == set()


@pytest.mark.parametrize("page", PAGES)
def test_every_import_in_an_example_resolves(page):
    """``from zettcode.sdk... import X`` must name something that exists."""
    import importlib

    missing: list[str] = []
    for source in blocks(page):
        for node in ast.walk(ast.parse(source, mode="exec", type_comments=False)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("zettcode.sdk"):
                module = importlib.import_module(node.module)
                missing.extend(f"{node.module}.{alias.name}" for alias in node.names if not hasattr(module, alias.name))
    assert missing == []


@pytest.mark.parametrize("page", PAGES)
def test_every_error_the_pages_name_exists(page):
    from zettcode.sdk import errors

    text = (ROOT / page).read_text(encoding="utf-8")
    named = {
        name
        for name in re.findall(r"`([A-Z][A-Za-z]+Error)`", text)
        if not hasattr(builtins, name) and not hasattr(asyncio, name)
    }

    assert {name for name in named if not hasattr(errors, name)} == set()


def test_the_error_pages_name_every_error():
    from zettcode.sdk import errors

    every = set(errors.__all__)
    for page in ("docs/sdk/errors.md", "docs/zh/sdk/errors.md", "docs/sdk/reference.md", "docs/zh/sdk/reference.md"):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert {name for name in every if f"`{name}`" not in text} == set(), page


@pytest.mark.parametrize("name", [path.name for path in ENGLISH])
def test_the_two_languages_show_the_same_examples(name):
    """The translation is not a different program: the same number of examples, using the same names."""
    english = blocks(f"docs/sdk/{name}")
    chinese = blocks(f"docs/zh/sdk/{name}")

    assert len(english) == len(chinese)

    def used(found: list[str]) -> set[str]:
        return set(re.findall(r"\bzc\.([A-Za-z_][A-Za-z_0-9]*)", "\n".join(found)))

    assert used(english) == used(chinese)


def test_every_public_name_is_documented_in_the_reference():
    for page in ("docs/sdk/reference.md", "docs/zh/sdk/reference.md"):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert {name for name in sdk.__all__ if name not in text} == set(), page


@pytest.mark.parametrize("page", PAGES)
def test_every_link_points_at_a_page_and_a_heading_that_exist(page):
    """A link is checked against the files themselves, so a renamed heading cannot leave a dead anchor."""
    path = ROOT / page
    text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE | re.DOTALL)
    broken: list[str] = []
    for link in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", link):
            continue
        target, _, fragment = link.partition("#")
        if not target:
            found = path
        elif target.startswith("./"):
            found = path.parent / f"{target[2:]}.md"
        elif target.startswith(("/sdk/", "/zh/sdk/")):
            relative = target.removeprefix("/zh").removeprefix("/sdk/") or "index"
            found = path.parent / f"{relative}.md"
        elif target.startswith(("/guide/", "/zh/guide/")):
            found = ROOT / "docs" / f"{target.lstrip('/')}.md"
        else:
            broken.append(f"{link} is not a link this page can resolve")
            continue
        if not found.is_file():
            broken.append(f"{link} names no page")
        elif fragment and fragment not in anchors(found):
            broken.append(f"{link} names no heading")

    assert broken == []


@pytest.mark.parametrize("page", ["docs/guide/overview.md", "docs/zh/guide/overview.md"])
def test_the_guide_points_at_the_sdk(page):
    text = (ROOT / page).read_text(encoding="utf-8")
    prefix = "/zh/sdk/" if "/zh/" in page else "/sdk/"

    assert f"]({prefix})" in text
    assert (ROOT / "docs" / prefix.strip("/") / "index.md").is_file()


@pytest.mark.parametrize("language,prefix", [("en", "/sdk/"), ("zh", "/zh/sdk/")])
def test_every_sdk_page_is_reachable_from_its_sidebar(language, prefix):
    script = (
        f'import {{ navigation }} from "{ROOT}/docs/.vitepress/navigation.ts";'
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
    navigation = json.loads(result.stdout)

    linked = [item["link"] for group in navigation["sidebar"][prefix] for item in group["items"]]
    expected = [prefix if path.stem == "index" else prefix + path.stem for path in ENGLISH]

    assert sorted(linked) == sorted(expected)
    assert len(linked) == len(set(linked))
    assert any(item.get("link") == prefix for item in navigation["nav"]), "the top bar leads into the SDK"
