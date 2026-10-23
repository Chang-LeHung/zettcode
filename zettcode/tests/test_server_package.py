"""The server ships in the one wheel: both console scripts, one version, no package of its own."""

from __future__ import annotations

from pathlib import Path

import zettcode
import zettcode.server

#: The project directory, one level above ``src``.
PROJECT = Path(zettcode.__file__).resolve().parent.parent.parent / "pyproject.toml"


def test_one_package_writes_both_console_scripts():
    project = PROJECT.read_text(encoding="utf-8")

    assert 'zettcode = "zettcode.cli:main"' in project
    assert 'zettcode-server = "zettcode.server.cli:main"' in project


def test_the_wheel_that_carries_the_agent_carries_the_server():
    """Hatchling ships ``src/zettcode``; the server is a subpackage of it, not a second distribution."""
    project = PROJECT.read_text(encoding="utf-8")

    assert 'packages = ["src/zettcode"]' in project
    assert Path(zettcode.server.__file__).resolve().parent == Path(zettcode.__file__).resolve().parent / "server"


def test_the_server_has_no_version_of_its_own():
    """One package, one version: ``zettcode-server --version`` names the version the agent was built at."""
    source = Path(zettcode.server.__file__).read_text(encoding="utf-8")

    assert "__version__" not in source
