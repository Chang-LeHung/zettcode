"""Static checks on the source tree: resolvable imports, and layers that hold.

Both checks read the source instead of importing it, so they also cover imports
that live inside functions — the ones a test run never executes.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
import pathlib
import re
import subprocess
import sys

import zettcode
from zettcode._compat import tomllib

#: Repository root, three levels above the package's ``__init__.py``.
ROOT = pathlib.Path(zettcode.__file__).resolve().parent.parent.parent

#: One piece of evidence in ``docs/internal/invariants.md``: a test file and,
#: within the same row, the bare names that follow it.
CITATION = re.compile(r"`([^`]+)`")
PREFIXED = re.compile(r"(test_[a-z_]+)\.py::([A-Za-z_][A-Za-z0-9_]*)")
BARE = re.compile(r"test_[a-z_]+")


def test_every_invariant_cites_a_test_that_exists():
    """A row's evidence has to be findable, or the mark cannot be trusted.

    Every row points at the test that fails when the rule breaks, and a row
    names the file once and then the rest of that row's tests by themselves, so
    this reads a row the way a reader does: the first citation names the file,
    the ones after it belong to it, and each has to exist there. A test renamed
    without its citation, or a name written with no file in front of it, sends a
    reader looking for evidence that is not where the row says it is.
    """
    document = (ROOT / "docs/internal/invariants.md").read_text(encoding="utf-8")
    missing: list[str] = []
    unqualified: list[str] = []
    checked = 0
    for line in document.splitlines():
        current: str | None = None
        for piece in CITATION.findall(line):
            prefixed = PREFIXED.fullmatch(piece)
            if prefixed:
                current, name = prefixed.group(1), prefixed.group(2)
            elif BARE.fullmatch(piece):
                if current is None:
                    unqualified.append(piece)
                    continue
                name = piece
            else:
                continue
            checked += 1
            source = (ROOT / "tests" / f"{current}.py").read_text(encoding="utf-8")
            if not re.search(rf"^\s*(?:async )?def {re.escape(name)}\(", source, re.MULTILINE):
                missing.append(f"{current}::{name}")

    assert checked > 150, f"the citations stopped parsing: {checked} read"
    assert unqualified == [], f"cite the file once in the row first: {unqualified}"
    assert missing == []


# A module under one of these prefixes may not import anything under the others:
# the framework stays standalone, and the agent side never reaches into the ui.
LAYERS = (
    ("zettcode.tui", ("zettcode.app", "zettcode.cli", "zettcode.config")),
    ("zettcode.app.agent", ("zettcode.app.ui",)),
)

#: Packages that re-export their subpackages lazily through ``__getattr__``.
FACADES = (
    "zettcode",
    "zettcode.app",
    "zettcode.app.agent",
    "zettcode.app.ui",
    "zettcode.app.ui.widgets",
    "zettcode.tui",
    "zettcode.tui.widgets",
)


def _sources() -> list[tuple[pathlib.Path, str, bool]]:
    """Return every module as ``(path, dotted name, is package)``."""
    root = pathlib.Path(zettcode.__file__).parent
    modules: list[tuple[pathlib.Path, str, bool]] = []
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        modules.append((path, ".".join(["zettcode", *parts]), is_package))
    return modules


def _resolved(module: str, is_package: bool, level: int, imported: str | None) -> str:
    """Return the dotted name a relative import points at."""
    package = module if is_package else module.rpartition(".")[0]
    for _ in range(level - 1):
        package = package.rpartition(".")[0]
    return f"{package}.{imported}" if imported else package


def _imports(path: pathlib.Path, module: str, is_package: bool) -> list[tuple[int, str, bool]]:
    """Return ``(line, dotted target, is relative)`` for every import in a file."""
    found: list[tuple[int, str, bool]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((node.lineno, _resolved(module, is_package, node.level, node.module), True))
            elif node.module:
                found.append((node.lineno, node.module, False))
    return found


def test_every_relative_import_resolves_to_a_real_module():
    """Moving a module is a chance to miscount the dots; check them all."""
    unresolved: list[str] = []
    for path, module, is_package in _sources():
        for line, target, relative in _imports(path, module, is_package):
            if not relative:
                continue
            try:
                exists = importlib.util.find_spec(target) is not None
            except ModuleNotFoundError:
                exists = False
            if not exists:
                unresolved.append(f"{module}:{line} resolves to {target}")

    assert unresolved == []


def test_layers_only_import_downwards():
    """`ui` reads `agent`, `agent` builds on `tui`, and `tui` stands alone."""
    violations: list[str] = []
    for path, module, is_package in _sources():
        for line, target, _ in _imports(path, module, is_package):
            for owner, forbidden in LAYERS:
                if module.startswith(owner) and target.startswith(forbidden):
                    violations.append(f"{module}:{line} imports {target}")

    assert violations == []


def test_every_facade_publishes_what_it_promises():
    """A lazy re-export is easy to get wrong, so every name has to resolve."""
    missing: list[str] = []
    for name in FACADES:
        module = importlib.import_module(name)
        for attribute in module.__all__:
            try:
                getattr(module, attribute)
            except AttributeError as error:
                missing.append(f"{name}.{attribute}: {error}")

    assert missing == []


def test_importing_the_package_does_not_build_the_application():
    """Names are imported on use: ``import zettcode`` must not load the runtime."""
    script = "import zettcode, sys; print('zett_agent' in sys.modules, 'zettcode.app.ui' in sys.modules)"

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_the_version_is_written_once_and_the_distribution_carries_it():
    """A copy of the version in ``pyproject`` would drift from the tag check.

    The installed metadata is compared as well, because it is what
    ``importlib.metadata`` reports to plugins and what a release actually
    publishes. Bumping ``__version__`` without rebuilding the editable install
    fails here until ``uv sync --reinstall-package zettcode`` runs; CI installs
    from scratch, so there the two always agree.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/zettcode/__init__.py"
    assert project["project"]["name"] == zettcode.__name__
    assert zettcode.__version__ == importlib.metadata.version("zettcode")


def test_a_facade_maps_every_name_to_the_module_it_statically_imports():
    """The runtime map and the static imports a checker reads must agree.

    A lazy ``__getattr__`` is invisible to a type checker, so each facade also
    imports its names under ``TYPE_CHECKING``. Nothing at runtime notices when
    the two drift apart — a reader's editor does — so they are compared here.
    """
    drifted: list[str] = []
    for name in FACADES:
        module = importlib.import_module(name)
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        mapping = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_EXPORTS"
        )
        static: dict[str, str] = {}
        for node in tree.body:
            if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    target = "." * child.level + (child.module or "")
                    for alias in child.names:
                        static[alias.asname or alias.name] = target
        if static != mapping:
            drifted.append(f"{name}: static {sorted(static)} vs map {sorted(mapping)}")

    assert drifted == []
