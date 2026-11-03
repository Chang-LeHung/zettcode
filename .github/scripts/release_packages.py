"""Decide which `packages/*` distributions a release run publishes, and which it leaves alone.

One tag names one package — `<name>-v<version>`, where `<name>` is the directory or the plugin name its entry point
declares, as `monitor-v0.2.0` has always been — and `workflow_dispatch` names one by its directory, or asks for every
package with `all`. An event that is neither is an error rather than "everything": a release run may not guess.

Whichever way a package is picked, what decides the outcome is its own `pyproject.toml` and what PyPI already has: the
version hatchling reads from the package's `__init__.py` is what would be published, and a version PyPI already lists
is skipped. Re-running a release, or re-pushing a tag that published, is then a no-op instead of a failure, and a new
package under `packages/` needs no workflow of its own.

Writes `targets` (a JSON array of `{"dir", "name", "version"}`, for the later jobs to loop over) and `any` to
`$GITHUB_OUTPUT`, and a table to the step summary.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

if sys.version_info >= (3, 11):
    import tomllib
else:  # the workflow runs 3.12; this keeps the script runnable on the oldest version the project claims
    import tomli as tomllib

#: Where a distribution's releases are listed. A 404 means the name was never published, which is a new package.
PYPI = "https://pypi.org/pypi/{name}/json"

#: The repository root: this file is `.github/scripts/release_packages.py`.
ROOT = pathlib.Path(__file__).resolve().parents[2]


class Release(Exception):
    """Something a reader has to fix before anything is published."""


class Package:
    """One directory under `packages/`, as its `pyproject.toml` describes it."""

    def __init__(self, directory: pathlib.Path, name: str, version: str, prefixes: tuple[str, ...]) -> None:
        #: The directory name, which is what the workflow input and the later jobs use.
        self.directory = directory.name
        self.name = name
        self.version = version
        #: What a tag may call this package: its directory and the plugin names its entry points declare.
        self.prefixes = prefixes


def _assigned_version(path: pathlib.Path) -> str:
    """The `__version__` a module assigns at the top level, read without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets: tuple[ast.expr, ...] = (node.target,)
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = tuple(node.targets)
            value = node.value
        else:
            continue
        if not any(getattr(target, "id", "") == "__version__" for target in targets):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise Release(f'{path}: no __version__ = "…" at the top level')


def describe(directory: pathlib.Path) -> Package:
    """Read one package's name, version and plugin names from its `pyproject.toml`."""
    source = directory / "pyproject.toml"
    settings = tomllib.loads(source.read_text(encoding="utf-8"))
    project = settings.get("project")
    if project is None:
        raise Release(f"{source}: no [project] table")
    name = project.get("name")
    if not name:
        raise Release(f"{source}: [project] has no name")
    version = project.get("version")
    if version is None:
        # The version is written once, in the package; `tool.hatch.version` says which file.
        try:
            written = settings["tool"]["hatch"]["version"]["path"]
        except KeyError:
            raise Release(f"{source}: a dynamic version needs the [tool.hatch.version] path read here") from None
        version = _assigned_version(directory / written)
    if not settings.get("dependency-groups", {}).get("dev"):
        # The release workflow installs this group into the environment it tests in, so the package says what its tests
        # import instead of the workflow guessing.
        raise Release(f"{source}: no [dependency-groups] dev; the release workflow installs it to run the tests")
    if not (directory / "tests").is_dir():
        # `make test` skips a package with no tests, and the release job would fail inside pytest with code 4 instead:
        # say so here, where the message names the package.
        raise Release(f"{directory}: no tests/ directory; the release runs them before publishing")
    plugins = tuple(project.get("entry-points", {}).get("zettcode.plugins", {}))
    return Package(directory, name, version, (directory.name, *plugins))


def discover() -> list[Package]:
    """Every distribution in `packages/`, in the order `ls` would print them."""
    found = [
        describe(directory)
        for directory in sorted((ROOT / "packages").iterdir())
        if (directory / "pyproject.toml").is_file()
    ]
    if not found:
        raise Release("packages/ holds no distribution")
    return found


def published(name: str, version: str) -> bool:
    """Whether PyPI already lists this exact version, which is the whole reason a run is skipped."""
    request = urllib.request.Request(PYPI.format(name=name), headers={"User-Agent": "zettcode-release"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            listing = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise Release(f"PyPI answered {error.code} for {name}") from error
    except OSError as error:  # no network, a timeout, a proxy that refused
        raise Release(f"could not ask PyPI about {name}: {error}") from error
    return version in listing.get("releases", {})


def by_tag(found: list[Package], tag: str) -> list[Package]:
    """The package a `<name>-v<version>` tag names, with the tag's version checked against the checkout's."""
    matches = [(package, prefix) for package in found for prefix in package.prefixes if tag.startswith(f"{prefix}-v")]
    if not matches:
        prefixes = ", ".join(sorted({prefix for package in found for prefix in package.prefixes}))
        raise Release(
            f"tag {tag!r} names no package; a tag looks like <name>-v<version>, where <name> is one of: {prefixes}"
        )
    packages = {package.name for package, _ in matches}
    if len(packages) > 1:
        raise Release(
            f"tag {tag!r} is ambiguous between {', '.join(sorted(packages))}; use one package's directory name"
        )
    package, prefix = matches[0]
    tagged = tag[len(prefix) + 2 :]
    if tagged != package.version:
        raise Release(f"tag {tag!r} says {tagged}, but {package.name} in this commit declares {package.version}")
    return [package]


def by_directory(found: list[Package], asked: str) -> list[Package]:
    """The package the dispatch input names, by its directory."""
    for package in found:
        if package.directory == asked:
            return [package]
    directories = ", ".join(package.directory for package in found)
    raise Release(f"{asked!r} is not a directory under packages/; they are: {directories}")


def choose(found: list[Package]) -> list[Package]:
    """The packages this run offers to publish, before the PyPI check."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "push":
        tag = os.environ.get("GITHUB_REF_NAME", "")
        if not tag:
            raise Release("this looked like a tag push but carries no GITHUB_REF_NAME")
        return by_tag(found, tag)
    if event != "workflow_dispatch":
        # A run whose event this script does not know is not "everything": that would publish packages nobody asked
        # about, and skip the tag cross-check while doing it.
        raise Release(f"this run was started by {event or 'nothing known'}; a release is a tag or a manual run")
    asked = os.environ.get("RELEASE_PACKAGE", "").strip()
    if asked:
        return by_directory(found, asked)
    if os.environ.get("RELEASE_ALL", "").strip().lower() == "true":
        return found
    raise Release("name a package in `package`, or tick `all`: a release run never publishes by accident")


def report(targets: list[dict[str, str]]) -> None:
    """Write the outputs the jobs read, and say what the run will do."""
    lines = ["| Package | Version |", "| --- | --- |"]
    lines += [f"| `{target['name']}` | {target['version']} |" for target in targets]
    if not targets:
        lines.append("| — | nothing new to publish |")
    print("\n".join(lines))

    outputs = os.environ.get("GITHUB_OUTPUT")
    if outputs:
        with open(outputs, "a", encoding="utf-8") as stream:
            stream.write(f"targets={json.dumps(targets)}\n")
            stream.write(f"any={'true' if targets else 'false'}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## Packages to publish\n\n" + "\n".join(lines) + "\n")


def main() -> int:
    found = discover()
    targets = []
    for package in choose(found):
        if published(package.name, package.version):
            print(f"{package.name} {package.version} is already on PyPI; skipping it")
        else:
            print(f"{package.name} {package.version} is not on PyPI; it will be published")
            targets.append({"dir": package.directory, "name": package.name, "version": package.version})
    report(targets)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Release as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
