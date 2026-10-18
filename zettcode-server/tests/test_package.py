"""The server package exists as a workspace member: it builds, it imports, and its version is written once."""

from __future__ import annotations

import ast
from pathlib import Path

import zettcode_server


def test_the_version_is_written_once_and_read_from_the_package():
    source = Path(zettcode_server.__file__).read_text(encoding="utf-8")
    assigned = [
        node.value.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__version__"
    ]
    project = Path(__file__).resolve().parent.parent / "pyproject.toml"

    assert assigned == [zettcode_server.__version__]
    assert 'path = "src/zettcode_server/__init__.py"' in project.read_text(encoding="utf-8")


def test_the_wheel_builds_around_this_module():
    """Hatchling is told the package is ``src/zettcode_server``; a move without that edit ships an empty wheel."""
    project = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")

    assert 'packages = ["src/zettcode_server"]' in project
