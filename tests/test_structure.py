"""Static checks on the source tree: resolvable imports, and layers that hold.

Both checks read the source instead of importing it, so they also cover imports
that live inside functions — the ones a test run never executes.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
import subprocess
import sys

import zettcode

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
