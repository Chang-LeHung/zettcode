"""Use the checkout's shared test isolation; an unpacked sdist remains independent."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SUPPORT = ROOT / "support"
if (ROOT / "pyproject.toml").is_file() and SUPPORT.is_dir():
    sys.path.insert(0, str(SUPPORT))
    for _suite in sorted((ROOT / "packages").glob("*/tests")):
        sys.path.append(str(_suite))
    _SHARED = SUPPORT / "conftest.py"
    exec(compile(_SHARED.read_text(encoding="utf-8"), str(_SHARED), "exec"), globals())


def pytest_collection_modifyitems(items):
    """This suite's fake SSH executables, remote paths and process groups require a POSIX host."""
    if sys.platform == "win32":
        skip = pytest.mark.skip(
            reason="SSH tests require a POSIX fake host, paths and process groups; Windows SSH is untested"
        )
        for item in items:
            item.add_marker(skip)
