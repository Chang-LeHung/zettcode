"""The release helper in `.github/scripts`: which packages a run publishes, and which it leaves alone.

The script lives outside the packages, so nothing else would run it. The part worth pinning is the decision — a tag
that names the wrong package, or a manual run that publishes everything because a variable went missing, is only
visible here — so these tests load it by path and replace the one function that asks PyPI. No network, no release.
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import urllib.error
from importlib.metadata import version

import pytest

#: The repository root: this file is `tests/test_release_packages.py`.
ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github" / "scripts" / "release_packages.py"


@pytest.fixture()
def helper():
    """The script, imported by path so it can be exercised without the workflow around it."""
    spec = importlib.util.spec_from_file_location("release_packages", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package(helper, directory: str, version: str = "1.0", plugins: tuple[str, ...] = ()):
    """A package as `describe` would build one, with the directory as its distribution name."""
    return helper.Package(pathlib.Path(directory), directory, version, (directory, *plugins))


def test_a_tag_names_a_package_by_its_directory_or_by_its_plugin_name(helper):
    found = [
        package(helper, "zettcode-monitor", "0.2.0", ("monitor",)),
        package(helper, "zettcode-recap", "0.1.0", ("recap",)),
    ]

    assert [p.directory for p in helper.by_tag(found, "monitor-v0.2.0")] == ["zettcode-monitor"]
    assert [p.directory for p in helper.by_tag(found, "zettcode-recap-v0.1.0")] == ["zettcode-recap"]


def test_a_tag_that_names_no_package_is_refused_and_says_which_would(helper):
    found = [package(helper, "zettcode-monitor", "0.2.0", ("monitor",))]

    # ZettCode's own `v*` tag reaches this workflow's filter; it must be told apart from a plugin's.
    with pytest.raises(helper.Release, match="names no package"):
        helper.by_tag(found, "v0.3.3")
    with pytest.raises(helper.Release, match="monitor, zettcode-monitor"):
        helper.by_tag(found, "nope-v1.0")


def test_a_tag_whose_version_is_not_the_checkouts_is_refused(helper):
    found = [package(helper, "zettcode-monitor", "0.2.0", ("monitor",))]

    with pytest.raises(helper.Release, match="declares 0.2.0"):
        helper.by_tag(found, "monitor-v0.3.0")


def test_two_packages_answering_to_one_name_is_refused(helper):
    found = [package(helper, "a", "1.0", ("shared",)), package(helper, "shared", "1.0")]

    with pytest.raises(helper.Release, match="ambiguous"):
        helper.by_tag(found, "shared-v1.0")


def test_a_manual_run_publishes_nothing_unless_it_names_a_package_or_asks_for_all(helper, monkeypatch):
    found = [package(helper, "a"), package(helper, "b")]
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.delenv("RELEASE_PACKAGE", raising=False)
    monkeypatch.delenv("RELEASE_ALL", raising=False)

    with pytest.raises(helper.Release, match="tick `all`"):
        helper.choose(found)

    # What a bare dispatch actually sends: the boolean input evaluates to "false", not to empty.
    monkeypatch.setenv("RELEASE_ALL", "false")
    with pytest.raises(helper.Release, match="tick `all`"):
        helper.choose(found)

    monkeypatch.setenv("RELEASE_ALL", "true")
    assert helper.choose(found) == found

    monkeypatch.setenv("RELEASE_PACKAGE", "b")
    assert [p.directory for p in helper.choose(found)] == ["b"]

    monkeypatch.setenv("RELEASE_PACKAGE", "monitor")
    with pytest.raises(helper.Release, match="not a directory"):
        helper.choose(found)


def test_a_run_the_script_does_not_know_never_means_everything(helper, monkeypatch):
    found = [package(helper, "a"), package(helper, "b")]
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    with pytest.raises(helper.Release, match="tag or a manual run"):
        helper.choose(found)


def test_the_packages_in_the_tree_describe_themselves(helper):
    """The real `packages/` is readable, and each version is the one its distribution was installed with."""
    found = helper.discover()

    assert found, "packages/ holds at least one distribution"
    for described in found:
        assert described.prefixes[0] == described.directory
        assert (ROOT / "packages" / described.directory / "src").is_dir(), described.directory
        installed = version(described.name)
        assert described.version == installed, (
            f"{described.name}: pyproject.toml says {described.version} and the environment has {installed}; "
            "run `uv sync` after a version bump"
        )


def test_a_package_the_helper_cannot_read_is_reported_rather_than_crashing(helper, tmp_path):
    project = tmp_path / "pyproject.toml"

    project.write_text('[project]\nname = "x"\nversion = "1.0"\n', encoding="utf-8")
    with pytest.raises(helper.Release, match="dependency-groups"):
        helper.describe(tmp_path)

    # A `dev` group and no tests is the split the reviewer of this contract would miss: `make test` skips the package
    # and the release job's pytest exits 4.
    project.write_text(
        '[project]\nname = "x"\nversion = "1.0"\n[dependency-groups]\ndev = ["pytest"]\n', encoding="utf-8"
    )
    with pytest.raises(helper.Release, match="no tests/ directory"):
        helper.describe(tmp_path)

    project.write_text('[tool.hatch.version]\npath = "x.py"\n', encoding="utf-8")
    with pytest.raises(helper.Release, match=r"no \[project\] table"):
        helper.describe(tmp_path)

    project.write_text('[project]\ndynamic = ["version"]\n', encoding="utf-8")
    with pytest.raises(helper.Release, match=r"no name"):
        helper.describe(tmp_path)


def test_a_dynamic_version_is_read_from_the_file_pyproject_names(helper, tmp_path):
    directory = tmp_path / "x"
    module = directory / "src" / "x"
    module.mkdir(parents=True)
    (directory / "tests").mkdir()
    (directory / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndynamic = ["version"]\n'
        '[dependency-groups]\ndev = ["pytest"]\n'
        '[tool.hatch.version]\npath = "src/x/__init__.py"\n',
        encoding="utf-8",
    )
    # Annotated as well: the script reads the value, not the spelling of the assignment.
    (module / "__init__.py").write_text('__version__: str = "1.2.3"\n', encoding="utf-8")

    described = helper.describe(directory)

    assert (described.name, described.version, described.prefixes) == ("x", "1.2.3", ("x",))


def test_the_workflow_reads_the_targets_and_whether_there_are_any(helper, tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    helper.report([{"dir": "x", "name": "x", "version": "1.0"}])
    helper.report([])

    assert outputs.read_text(encoding="utf-8") == (
        'targets=[{"dir": "x", "name": "x", "version": "1.0"}]\nany=true\ntargets=[]\nany=false\n'
    )
    assert "nothing new to publish" in summary.read_text(encoding="utf-8")


def test_a_package_pypi_has_never_seen_is_not_published(helper, monkeypatch):
    """404 is the new-package case: nothing is listed under that name, so there is nothing to skip."""

    def not_found(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://pypi.org/pypi/x/json", 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(helper.urllib.request, "urlopen", not_found)

    assert helper.published("x", "1.0") is False


def test_a_version_in_pypis_listing_is_what_skips_a_release(helper, monkeypatch):
    listing = json.dumps({"releases": {"1.0": [], "1.1": []}}).encode()
    monkeypatch.setattr(helper.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(listing))

    assert helper.published("x", "1.0") is True
    assert helper.published("x", "2.0") is False


def test_a_pypi_that_answers_or_a_network_that_does_not_is_a_named_failure(helper, monkeypatch):
    def broken(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://pypi.org/pypi/x/json", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(helper.urllib.request, "urlopen", broken)
    with pytest.raises(helper.Release, match="answered 500"):
        helper.published("x", "1.0")

    def no_route(*_args, **_kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(helper.urllib.request, "urlopen", no_route)
    with pytest.raises(helper.Release, match="could not ask PyPI"):
        helper.published("x", "1.0")


def test_a_version_pypi_already_lists_is_skipped_instead_of_published_again(helper, tmp_path, monkeypatch):
    """Re-running a release, or re-pushing a tag that published, has to be a no-op that still succeeds."""
    outputs = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("RELEASE_ALL", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setattr(helper, "published", lambda name, version: name == "zettcode-monitor")

    helper.main()

    written = dict(line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines())
    expected = [p for p in helper.discover() if p.name != "zettcode-monitor"]
    assert json.loads(written["targets"]) == [
        {"dir": p.directory, "name": p.name, "version": p.version} for p in expected
    ]
    assert written["any"] == "true"
