"""The server is its own distribution, and the one a reader installs still writes both console scripts."""

from __future__ import annotations

from pathlib import Path

import zettcode.server
import zettcode.version

ROOT = Path(__file__).resolve().parents[3]

#: The program's project directory: the distribution a reader installs and the one that owns the console scripts.
PROGRAM = ROOT / "packages" / "zettcode" / "pyproject.toml"

#: The server's, which is a distribution of its own.
SERVER = ROOT / "packages" / "zettcode-server" / "pyproject.toml"


def test_the_program_writes_both_console_scripts():
    project = PROGRAM.read_text(encoding="utf-8")

    assert 'zettcode = "zettcode.cli:main"' in project
    assert 'zettcode-server = "zettcode.server.cli:main"' in project


def test_the_server_is_a_distribution_of_its_own_that_the_program_depends_on():
    """Hatchling ships ``src/zettcode/server`` from the server's tree; the program names it among its dependencies."""
    from packaging.requirements import Requirement

    from zettcode._compat import tomllib

    project = SERVER.read_text(encoding="utf-8")
    needs = {Requirement(line).name for line in tomllib.loads(project)["project"]["dependencies"]}
    named = {
        Requirement(line).name for line in tomllib.loads(PROGRAM.read_text(encoding="utf-8"))["project"]["dependencies"]
    }

    assert 'packages = ["src/zettcode"]' in project
    assert "zettcode-sdk" in needs, "the server is built on the SDK, and must not carry it itself"
    assert "zettcode-server" in named, "the program a reader installs is what brings the server"
    assert Path(zettcode.server.__file__).resolve().parent == SERVER.parent / "src" / "zettcode" / "server"


def test_the_server_has_no_version_of_its_own():
    """One version for the repository: ``zettcode-server --version`` reads the file the engine ships."""
    cli = (SERVER.parent / "src" / "zettcode" / "server" / "cli.py").read_text(encoding="utf-8")

    assert "from zettcode.version import __version__" in cli
    assert "__version__ =" not in cli


def test_every_distribution_reads_the_one_version_file():
    """A second copy of the version would drift from the release tag; the engine ships the only one."""
    engine = ROOT / "packages" / "zettcode-engine" / "src" / "zettcode" / "version.py"
    assert zettcode.version.__version__ in engine.read_text(encoding="utf-8")

    # The engine ships the file; every other distribution of the program reads it. A plugin keeps a literal of its own
    # instead (its sdist has to build outside this checkout) and carries the same number; `test_versions.py` holds the
    # two together, and the plugins are not in `packages/`'s generated order.
    for name in sorted(
        project.parent.name
        for project in (ROOT / "packages").glob("*/pyproject.toml")
        if "plugin = true" not in project.read_text(encoding="utf-8")
    ):
        text = (ROOT / "packages" / name / "pyproject.toml").read_text(encoding="utf-8")
        expected = (
            'path = "src/zettcode/version.py"'
            if name == "zettcode-engine"
            else 'path = "../zettcode-engine/src/zettcode/version.py"'
        )
        assert expected in text, name
