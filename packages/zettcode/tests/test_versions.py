"""One version for everything this repository publishes, held by the check a pull request runs.

The program and the parts it is built from read their version from one file, so they cannot disagree. A plugin keeps
its own ``__version__`` — a wheel has to be buildable from its sdist, where the engine's file is not there — and a
requirement on one of our distributions carries a range written into a hand-edited ``pyproject.toml``. Those two are
what drifts, and this is what notices: the workspace is checked as it stands, and the helper's write is exercised on a
small tree so a bump is not only believed to be correct.

The same check runs in ``release.yml`` (``.github/scripts/versions.py --check``), which is why it is a script and not
only a test: a tag cannot be published while a plugin's version or a dependency floor is behind.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

#: The repository root: this file is `tests/test_versions.py`.
ROOT = pathlib.Path(__file__).resolve().parents[3]
HELPER = ROOT / ".github" / "scripts" / "versions.py"


@pytest.fixture()
def helper():
    """The script, imported by path so it can be exercised without the workflow around it."""
    spec = importlib.util.spec_from_file_location("versions", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(root: pathlib.Path, *, version: str = "1.2.3", plugin: str = "1.0.0", requirement: str = ">=1.0,<2") -> None:
    """Write a small workspace that has the two things that drift: a plugin's version and a dependency's range."""
    engine = root / "packages" / "zettcode-engine" / "src" / "zettcode"
    engine.mkdir(parents=True)
    (engine / "version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (root / "packages" / "zettcode-engine" / "pyproject.toml").write_text(
        '[project]\nname = "zettcode-engine"\ndynamic = ["version"]\n', encoding="utf-8"
    )
    plugin_root = root / "packages" / "zettcode-monitor"
    module = plugin_root / "src" / "zettcode" / "monitor"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text(f'__version__ = "{plugin}"\n', encoding="utf-8")
    (plugin_root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "zettcode-monitor"\n'
        'dynamic = ["version"]\n'
        "dependencies = [\n"
        f'  "zettcode-plugin-api{requirement}",\n'
        "]\n"
        "[tool.zettcode]\n"
        "plugin = true\n"
        "[tool.hatch.version]\n"
        'path = "src/zettcode/monitor/__init__.py"\n',
        encoding="utf-8",
    )
    program = root / "packages" / "zettcode"
    program.mkdir(parents=True)
    (program / "pyproject.toml").write_text(
        "[project]\n"
        'name = "zettcode"\n'
        'dynamic = ["version"]\n'
        "dependencies = [\n"
        '  "zettcode-engine",\n'
        "]\n"
        "[project.optional-dependencies]\n"
        f'monitor = ["zettcode-monitor{requirement}"]\n'
        f'all = ["zettcode-monitor{requirement}"]\n',
        encoding="utf-8",
    )


# -- the tree as it stands ---------------------------------------------------------------------------


def test_every_distribution_in_this_workspace_is_on_the_programs_version(helper):
    """The rule the pull request enforces: one number for the program, its parts and its plugins."""
    assert helper._problems(ROOT) == []


def test_the_check_finds_a_plugin_that_was_left_behind(helper, tmp_path):
    tree(tmp_path, plugin="0.9.0")

    problems = helper._problems(tmp_path)

    assert any("0.9.0" in problem and "1.2.3" in problem for problem in problems)


def test_the_check_finds_a_requirement_whose_floor_is_not_this_version(helper, tmp_path):
    tree(tmp_path, requirement=">=1.0,<2")

    problems = helper._problems(tmp_path)

    assert any("zettcode-plugin-api>=1.0,<2" in problem for problem in problems)


def test_the_check_finds_a_requirement_with_no_range_at_all(helper, tmp_path):
    """``zettcode`` names each part of the program, and a part added without a range is a part that can drift."""
    tree(tmp_path)

    problems = helper._problems(tmp_path)

    assert any("no range" in problem and "zettcode-engine" in problem for problem in problems)


# -- the write a release starts with ----------------------------------------------------------------


def test_setting_the_version_rewrites_the_plugins_version_and_every_range(helper, tmp_path):
    tree(tmp_path)

    changed = helper.set_version(tmp_path, "2.0.0")

    assert helper.version_of(tmp_path / version_file()) == "2.0.0"
    assert helper.version_of(tmp_path / "packages/zettcode-monitor/src/zettcode/monitor/__init__.py") == "2.0.0"
    text = (tmp_path / "packages/zettcode/pyproject.toml").read_text(encoding="utf-8")
    assert text.count("zettcode-monitor>=2.0.0,<2.1") == 2, "both the extra and the all extra"
    assert (tmp_path / "packages/zettcode-engine/pyproject.toml").read_text(encoding="utf-8").count("zettcode") == 1
    assert changed and helper._problems(tmp_path) == []


def test_setting_the_version_leaves_a_marker_after_the_requirement_alone(helper, tmp_path):
    tree(tmp_path)
    program = tmp_path / "packages/zettcode/pyproject.toml"
    program.write_text(
        program.read_text(encoding="utf-8").replace(
            '"zettcode-engine"', "\"zettcode-engine>=1.0,<2; python_version < '3.11'\""
        ),
        encoding="utf-8",
    )

    helper.set_version(tmp_path, "1.2.3")

    assert "\"zettcode-engine>=1.2.3,<1.3; python_version < '3.11'\"" in program.read_text(encoding="utf-8")


def test_setting_the_version_twice_changes_nothing_the_second_time(helper, tmp_path):
    tree(tmp_path)
    helper.set_version(tmp_path, "2.0.0")

    assert helper.set_version(tmp_path, "2.0.0") == []


def test_a_version_that_is_not_three_numbers_is_refused_before_anything_is_written(helper, tmp_path):
    tree(tmp_path)

    with pytest.raises(helper.VersionError, match="MAJOR.MINOR.PATCH"):
        helper.set_version(tmp_path, "2.0")

    assert helper.version_of(tmp_path / version_file()) == "1.2.3"


def test_a_requirement_pinned_by_hand_is_refused_rather_than_half_rewritten(helper, tmp_path):
    """Appending our range to `==1.0` writes `==1.0>=1.2.3,<1.3`, which pip cannot read."""
    tree(tmp_path)
    program = tmp_path / "packages/zettcode/pyproject.toml"
    program.write_text(
        program.read_text(encoding="utf-8").replace('"zettcode-engine"', '"zettcode-engine==1.0"'), encoding="utf-8"
    )

    assert any("cannot rewrite" in problem for problem in helper._problems(tmp_path))
    with pytest.raises(helper.VersionError, match="cannot rewrite"):
        helper.set_version(tmp_path, "2.0.0")

    assert helper.version_of(tmp_path / version_file()) == "1.2.3", "nothing was written"


def test_a_requirement_the_write_cannot_find_is_refused_before_anything_is_written(helper, tmp_path):
    """A string TOML joins across lines reads as one requirement and is not written as one, so a rewrite finds nothing."""
    tree(tmp_path, plugin="1.2.3", requirement=">=1.2.3,<1.3")
    program = tmp_path / "packages/zettcode/pyproject.toml"
    program.write_text(
        program.read_text(encoding="utf-8").replace('"zettcode-engine"', '"""zettcode-engine\\\n>=1.2.3,<1.3"""'),
        encoding="utf-8",
    )

    assert any("one line" in problem for problem in helper._problems(tmp_path))
    with pytest.raises(helper.VersionError, match="one line"):
        helper.set_version(tmp_path, "3.0.0")

    assert helper.version_of(tmp_path / version_file()) == "1.2.3", "nothing was written"


def test_the_ceiling_is_the_next_minor_line(helper):
    assert helper.major_minor("0.4.5") == "0.5"
    assert helper.major_minor("1.2.3") == "1.3"
    assert helper.major_minor("2") == "2.1"


def version_file() -> str:
    """The program's version file, relative to the repository root, as ``versions.py`` names it."""
    return "packages/zettcode-engine/src/zettcode/version.py"
