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
    """Skip this suite where it cannot run, and say why rather than pretend it passed.

    Every test here reaches a remote host through a fake `ssh` that is a POSIX shell script started by its shebang, and
    every target is a POSIX path (`/home/...`), because the far side of a real connection is a POSIX shell. The plugin's
    own code keeps its Windows path (`start_new_session`, `killpg` and the worker's `SIGALRM` are guarded), but nothing
    here exercises it: a Windows run has no honest way to fake that host, so it says so instead of testing a shim.
    """
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(
        reason="the fake `ssh` host is a POSIX shell script and remote paths are POSIX; the Windows path is untested"
    )
    for item in items:
        item.add_marker(skip)
